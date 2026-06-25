"""Tiering = Anthropic-API per-family judgment + deterministic guardrails (Path A).

Pipeline per ticker (PATH_A_PLAN step 5):
  1. Read rubrics/*.md + the fetched JSON (edgar_fetch.py output).
  2. Ask Claude (model `claude-fable-5`, MODEL_POLICY: Fable 5 for forensic_triage) for
     STRUCTURED per-family flags + concerns + governance/severity/corporate-action signals.
     Claude does NOT emit the final tier (codex R2): it judges families, code decides tier.
  3. Validate Claude's structured output (fail-closed: reject/retry on malformed; if it stays
     malformed, treat as a fetch-style failure, NOT a clean Green).
  4. Apply the DETERMINISTIC guardrails + precedence + Green-eligibility gate from
     forensic_tier.finalize_tier(), using the COVERAGE map from the fetched JSON.
  5. Run-level circuit breaker: if too many names fail to fetch / lack required coverage,
     FAIL the run loudly (caller alarms #status-reports) rather than commit false Data Gaps.

This module is import-safe without `anthropic` installed (the import is lazy) so the tests can
exercise the guardrails + validation with a MOCK judge and never spend API budget.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date
from pathlib import Path

from forensic_schema import (
    COVERAGE,
    FAMILIES,
    HISTORY_COLUMNS,
    SCHEMA_VERSION,
    required_families,
)
from forensic_tier import finalize_tier

ROOT = Path(__file__).parent
RUBRICS_DIR = ROOT / "rubrics"
FETCHED_DIR = ROOT / "data" / "fetched"
FLAGS_HISTORY_CSV = ROOT / "data" / "flags_history.csv"

# MODEL_POLICY designates Fable 5 for forensic_triage, but Fable 5 is API-access-gated
# (this account's key 404s: "Claude Fable 5 is not available. Please use Opus 4.8") and is
# above Opus-tier pricing + 30-day-retention-gated. Opus 4.8 is the API's own prescribed
# alternative and the fleet default — strong on this structured, rubric-grounded judgment.
# Revert to claude-fable-5 here if/when Fable 5 API access is granted to the account.
MODEL_ID = "claude-opus-4-8"
FALLBACK_MODEL = "claude-opus-4-7"
MAX_VALIDATION_RETRIES = 2

# Run-level circuit breaker: if more than this FRACTION of the batch could not be evaluated
# (fetch failure or required coverage missing), the run is presumed to be hitting a broad
# SEC/REST/Anthropic outage. Fail loudly rather than commit a batch of false Data Gaps.
CIRCUIT_BREAKER_FRACTION = 0.5
CIRCUIT_BREAKER_MIN_BATCH = 3  # don't trip on 1-2 name batches

RUBRIC_FILES = {
    "general": "general.md",
    "hc_services": "healthcare_services.md",
    "medtech": "medtech.md",
}

# JSON schema Claude must satisfy. Claude emits per-family flags + concerns + the
# governance/severity/corporate-action SIGNALS — NOT the final tier.
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ticker": {"type": "string"},
        "flags": {
            "type": "object",
            "additionalProperties": False,
            "properties": {f: {"type": "integer", "enum": [0, 1]} for f in FAMILIES},
            "required": list(FAMILIES),
        },
        "critical_governance": {"type": "boolean"},
        "high_severity": {"type": "boolean"},
        "corporate_action": {"type": ["string", "null"]},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "flag_details": {"type": "string"},
    },
    "required": [
        "ticker", "flags", "critical_governance", "high_severity",
        "corporate_action", "concerns", "flag_details",
    ],
}

SYSTEM_PROMPT = """You are a forensic-accounting analyst applying a fixed rubric to one company.
Today's date is {today}.

You are given: (1) the general forensic rubric, (2) the matching sector rubric, and (3) a JSON
record of fetched EDGAR data for ONE ticker (statements, ratios, 10-K note bodies, 8-K item codes,
insider activity, and a per-family data-coverage map).

Decide, FOR EACH of these nine flag families, whether it FIRED (1) or not (0):
  accruals, revenue, capex, balance_sheet, leverage, governance, market, text, sector.

A family fires ONLY when the rubric's combination rules trigger — single noisy ratios do not fire.
Honor the rubric's calibration notes and exclusions exactly (e.g. the CFO/NI materiality floor, the
goodwill double-count rule, soft-vs-critical governance).

CRITICAL RULES:
- You do NOT assign the final tier. You only judge per-family flags and signals; code computes the tier.
- If a family's data coverage is `unavailable`/`partial`/`not_evaluated`, you may STILL set its flag to 1
  if a present signal clearly fires it, but DO NOT invent a flag from absent data — absence is not a flag.
- `critical_governance` = true ONLY for a genuine 8-K Item 4.02 / restatement / auditor-resignation-with-
  disagreement / NT late-filing in the data (general.md 6a). Routine churn (6b) is NOT critical.
- `high_severity` = true for a single high-severity accounting family (revenue/inventory collapse, fresh
  FCA/qui-tam) per the Yellow rule.
- `corporate_action` = a short string (e.g. "8-K item 5.01 take-private") ONLY for a non-accounting
  structural exit (merger/take-private/delisting); else null.
- `concerns` = short, specific bullet strings a human can act on (quote the note language when present).

Return ONLY the structured object."""


# --------------------------------------------------------------------------------------
# rubric + record loading
# --------------------------------------------------------------------------------------
def load_rubric(subgroup: str) -> str:
    parts = []
    gen = RUBRICS_DIR / RUBRIC_FILES["general"]
    if gen.exists():
        parts.append(f"# GENERAL RUBRIC\n\n{gen.read_text(encoding='utf-8')}")
    sector_file = RUBRIC_FILES.get(subgroup)
    if sector_file and subgroup != "general":
        sp = RUBRICS_DIR / sector_file
        if sp.exists():
            parts.append(f"# SECTOR RUBRIC ({subgroup})\n\n{sp.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(parts)


def load_record(ticker: str) -> dict:
    path = FETCHED_DIR / f"{ticker}.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------------------
# structured-output validation (fail-closed)
# --------------------------------------------------------------------------------------
class JudgeValidationError(Exception):
    """Claude's structured output didn't satisfy the contract."""


def validate_judge_output(obj, ticker: str) -> dict:
    """Strictly validate Claude's structured output. Raise JudgeValidationError on any deviation.

    Fail-closed: a malformed judge response must NOT be silently coerced into a clean Green.
    """
    if not isinstance(obj, dict):
        raise JudgeValidationError("judge output is not an object")
    flags = obj.get("flags")
    if not isinstance(flags, dict):
        raise JudgeValidationError("flags missing or not an object")
    clean_flags = {}
    for fam in FAMILIES:
        v = flags.get(fam)
        if v not in (0, 1):
            raise JudgeValidationError(f"flag '{fam}' is not 0/1 (got {v!r})")
        clean_flags[fam] = int(v)
    for key in ("critical_governance", "high_severity"):
        if not isinstance(obj.get(key), bool):
            raise JudgeValidationError(f"'{key}' is not a boolean")
    ca = obj.get("corporate_action")
    if ca is not None and not isinstance(ca, str):
        raise JudgeValidationError("'corporate_action' is not str|null")
    concerns = obj.get("concerns")
    if not isinstance(concerns, list) or not all(isinstance(c, str) for c in concerns):
        raise JudgeValidationError("'concerns' is not a list[str]")
    return {
        "ticker": str(obj.get("ticker") or ticker),
        "flags": clean_flags,
        "critical_governance": bool(obj["critical_governance"]),
        "high_severity": bool(obj["high_severity"]),
        "corporate_action": ca,
        "concerns": concerns,
        "flag_details": str(obj.get("flag_details") or ""),
    }


# --------------------------------------------------------------------------------------
# the Anthropic judge (lazy import; mockable)
# --------------------------------------------------------------------------------------
def _extract_json_text(response) -> str:
    """Pull the first text block out of an Anthropic response object."""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    raise JudgeValidationError("no text block in model response")


def call_judge(rubric: str, record: dict, *, client=None, model: str = MODEL_ID) -> dict:
    """Call Claude for the structured per-family judgment. Returns the VALIDATED dict.

    `client` is injectable for tests (a mock with .messages.create). In production it's an
    anthropic.Anthropic() built lazily so importing this module never requires the package.
    Fail-closed: after MAX_VALIDATION_RETRIES malformed responses, raise JudgeValidationError
    (the caller treats that as 'could not evaluate', NEVER as a clean Green).
    """
    if client is None:
        import anthropic  # lazy
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    ticker = record.get("ticker", "?")
    system = SYSTEM_PROMPT.format(today=date.today().isoformat())
    user = (
        f"{rubric}\n\n---\n\n# FETCHED DATA FOR {ticker}\n\n"
        f"```json\n{json.dumps(record, indent=2, default=str)[:120000]}\n```\n\n"
        "Apply the rubric and return the structured per-family judgment."
    )

    # Opus 4.8: adaptive thinking (the build was written for Fable 5's always-on thinking —
    # preserve that on Opus 4.8 since forensic tiering is accuracy-critical; Opus omits thinking
    # by default otherwise). No sampling params (they 400 on Opus 4.8). Structured output via
    # output_config.format (GA on Opus 4.8 — no tool-use needed). max_tokens 16000 leaves room
    # for thinking + the small JSON judgment without truncating (truncation -> max_tokens stop
    # -> our fail-closed guard rejects it). Server-side fallbacks stay opt-in for a refusal.
    base_kwargs = dict(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": JUDGE_SCHEMA},
        },
    )

    last_err = None
    for _ in range(MAX_VALIDATION_RETRIES + 1):
        response = _create_with_fallback(client, base_kwargs)
        # Fail CLOSED on ANY abnormal stop, not just refusal: max_tokens (truncated JSON),
        # pause_turn, etc. mean the structured output did not complete normally, so accepting
        # it could tier on a partial judgment (codex P1). Tolerate None (test fakes / older SDK
        # that don't surface stop_reason); reject any present value other than end_turn.
        sr = getattr(response, "stop_reason", None)
        if sr is not None and sr != "end_turn":
            raise JudgeValidationError(f"abnormal model stop_reason={sr!r}")
        try:
            text = _extract_json_text(response)
            obj = json.loads(text)
            return validate_judge_output(obj, ticker)
        except (JudgeValidationError, json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue
    raise JudgeValidationError(f"judge output invalid after retries: {last_err}")


def _create_with_fallback(client, kwargs: dict):
    """messages.create with server-side refusal fallback when available, else plain.

    Fallbacks are a beta param; if the SDK/endpoint rejects it we degrade to a plain create
    (still safe — a refusal is then caught by the stop_reason check upstream).
    """
    beta = getattr(client, "beta", None)
    if beta is not None and hasattr(getattr(beta, "messages", None), "create"):
        try:
            return beta.messages.create(
                betas=["server-side-fallback-2026-06-01"],
                fallbacks=[{"model": FALLBACK_MODEL}],
                **kwargs,
            )
        except TypeError:
            pass  # SDK too old for fallbacks/betas kwargs
        except Exception:
            pass  # beta endpoint unavailable -> fall through to plain create
    return client.messages.create(**kwargs)


# --------------------------------------------------------------------------------------
# coverage + tiering glue
# --------------------------------------------------------------------------------------
def _coverage_from_record(record: dict, subgroup: str) -> dict:
    cov = record.get("family_coverage") or {}
    out = {}
    for fam in FAMILIES:
        v = cov.get(fam)
        out[fam] = v if v in COVERAGE else "unavailable"
    return out


def _required_incomplete(coverage: dict, subgroup: str) -> bool:
    for fam in required_families(subgroup):
        if coverage.get(fam, "unavailable") not in ("complete", "not_applicable"):
            return True
    return False


def tier_one(
    record: dict,
    *,
    subgroup: str | None = None,
    is_new: bool = False,
    client=None,
    judge=None,
    model: str = MODEL_ID,
) -> dict:
    """Tier one fetched record. Returns a result dict (tier, reason, flags, concerns, status).

    `judge` lets tests inject the per-family verdict directly (skipping the API). In production
    `judge` is None and we call the Anthropic API via call_judge.
    """
    subgroup = subgroup or record.get("_subgroup") or _guess_subgroup(record)
    ticker = record.get("ticker", "?")
    coverage = _coverage_from_record(record, subgroup)

    # A transient fetch failure (source_errors AND nothing usable) must NOT be finalized as a
    # clean tier — it's "incomplete this run, retry next run". Foreign/stale = STRUCTURAL gap = done.
    fetch_failed = _is_transient_fetch_failure(record, coverage, subgroup)

    if judge is None:
        rubric = load_rubric(subgroup)
        verdict = call_judge(rubric, record, client=client, model=model)
    else:
        verdict = validate_judge_output(judge, ticker)

    tier, reason = finalize_tier(
        flags=verdict["flags"],
        coverage=coverage,
        subgroup=subgroup,
        critical_governance=verdict["critical_governance"],
        high_severity=verdict["high_severity"],
        corporate_action=verdict["corporate_action"],
        is_new=is_new,
    )

    # Idempotency status (codex R2): a structural Data Gap (foreign/stale/not-disclosed) IS
    # complete; a transient fetch failure with no overriding signal is NOT (retry next run).
    has_signal = verdict["critical_governance"] or verdict["high_severity"] or any(verdict["flags"].values())
    if fetch_failed and not has_signal:
        status = "fetch_failed"
    else:
        status = "complete"

    return {
        "ticker": ticker,
        "subgroup": subgroup,
        "tier": tier,
        "reason": reason,
        "flags": verdict["flags"],
        "critical_governance": verdict["critical_governance"],
        "high_severity": verdict["high_severity"],
        "corporate_action": verdict["corporate_action"],
        "concerns": verdict["concerns"],
        "flag_details": verdict["flag_details"] or reason,
        "coverage": coverage,
        "status": status,
    }


def _is_transient_fetch_failure(record: dict, coverage: dict, subgroup: str) -> bool:
    """True when the record represents a transient fetch failure rather than a structural gap.

    Structural (NOT transient): foreign filer, genuinely stale 10-K, legitimately not-disclosed
    notes. Transient: REST/edgartools errored such that required families came back `unavailable`
    while the filer is domestic and not stale.
    """
    if record.get("filer_type") == "foreign":
        return False
    if (record.get("staleness") or {}).get("is_stale") and (record.get("staleness") or {}).get("reason", "").startswith("latest 10-K"):
        return False  # genuinely stale -> structural Data Gap
    # Any REQUIRED family `unavailable` (a fetch failure, per the schema) with source_errors present.
    any_unavailable = any(
        coverage.get(f) == "unavailable" for f in required_families(subgroup)
    )
    return bool(any_unavailable and record.get("source_errors"))


def _guess_subgroup(record: dict) -> str:
    # Records don't carry subgroup; default to general. The batch driver passes it explicitly.
    return "general"


# --------------------------------------------------------------------------------------
# run-level circuit breaker
# --------------------------------------------------------------------------------------
def circuit_breaker_tripped(results: list[dict]) -> tuple[bool, str]:
    """Trip if too much of the batch could not be evaluated (broad outage)."""
    n = len(results)
    if n < CIRCUIT_BREAKER_MIN_BATCH:
        return False, ""
    failed = sum(1 for r in results if r.get("status") == "fetch_failed")
    frac = failed / n
    if frac > CIRCUIT_BREAKER_FRACTION:
        return True, f"{failed}/{n} names fetch_failed ({frac:.0%} > {CIRCUIT_BREAKER_FRACTION:.0%}) — likely broad outage"
    return False, ""


# --------------------------------------------------------------------------------------
# history rows
# --------------------------------------------------------------------------------------
def result_to_history_row(result: dict, *, run_id: str, run_date: str | None = None) -> dict:
    run_date = run_date or date.today().isoformat()
    flags = result["flags"]
    row = {
        "run_date": run_date,
        "ticker": result["ticker"],
        "tier": result["tier"],
        "flag_details": result.get("flag_details", ""),
        "run_id": run_id,
        "status": result.get("status", "complete"),
        "schema_version": SCHEMA_VERSION,
    }
    for fam in FAMILIES:
        row[f"{fam}_flag"] = int(flags.get(fam, 0))
    return {col: row.get(col, "") for col in HISTORY_COLUMNS}


def append_history(rows: list[dict], path: Path = FLAGS_HISTORY_CSV) -> None:
    """Append rows to flags_history.csv, migrating the header to the v16 column set if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_header = None
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            r = csv.reader(f)
            existing_header = next(r, None)
    write_header = (existing_header != HISTORY_COLUMNS)

    if existing_header is not None and write_header:
        _migrate_history_header(path)
        write_header = False

    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        if write_header or not path.exists():
            w.writeheader()
        for row in rows:
            w.writerow({col: row.get(col, "") for col in HISTORY_COLUMNS})


def _migrate_history_header(path: Path) -> None:
    """Rewrite an old (13-col) flags_history.csv to the v16 schema, defaulting the new columns."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            row.setdefault("run_id", "legacy")
            row.setdefault("status", "complete")
            row.setdefault("schema_version", "")
            w.writerow({col: row.get(col, "") for col in HISTORY_COLUMNS})


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("tickers", nargs="*", help="Tickers to tier (default: all in data/fetched/)")
    p.add_argument("--run-id", default="manual")
    p.add_argument("--append", action="store_true", help="Append results to flags_history.csv")
    p.add_argument("--subgroup-from-watchlist", action="store_true", default=True)
    args = p.parse_args(argv)

    tickers = args.tickers or [p.stem for p in sorted(FETCHED_DIR.glob("*.json"))]
    if not tickers:
        print("No fetched records found.")
        return 0

    subgroups = _load_subgroups()
    new_set = _new_names()
    results = []
    for t in tickers:
        t = t.upper()
        try:
            rec = load_record(t)
        except FileNotFoundError:
            print(f"  {t}: no fetched record (skipped)")
            continue
        sg = subgroups.get(t, "general")
        res = tier_one(rec, subgroup=sg, is_new=(t in new_set))
        results.append(res)
        print(f"  {t:<6} {res['tier']:<16} status={res['status']}  {res['reason']}")

    tripped, why = circuit_breaker_tripped(results)
    if tripped:
        print(f"\nCIRCUIT BREAKER: {why}")
        print("Refusing to commit a batch of false Data Gaps. Investigate the data sources.")
        return 2

    if args.append:
        rows = [result_to_history_row(r, run_id=args.run_id) for r in results]
        append_history(rows)
        print(f"\nAppended {len(rows)} rows to {FLAGS_HISTORY_CSV}")
    return 0


def _load_subgroups() -> dict:
    wl = ROOT / "data" / "watchlist.csv"
    out = {}
    if wl.exists():
        with wl.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                out[(row.get("ticker") or "").upper()] = row.get("sector_subgroup", "general")
    return out


def _new_names() -> set:
    """Tickers in the watchlist that have no prior flags_history row (first appearance -> auto-Yellow)."""
    wl = ROOT / "data" / "watchlist.csv"
    seen_hist = set()
    if FLAGS_HISTORY_CSV.exists():
        with FLAGS_HISTORY_CSV.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                seen_hist.add((row.get("ticker") or "").upper())
    new = set()
    if wl.exists():
        with wl.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").upper()
                if t and t not in seen_hist:
                    new.add(t)
    return new


if __name__ == "__main__":
    raise SystemExit(main())
