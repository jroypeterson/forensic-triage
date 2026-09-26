"""Tiering = Anthropic-API per-family judgment + deterministic guardrails (Path A).

Pipeline per ticker (PATH_A_PLAN step 5):
  1. Read rubrics/*.md + the fetched JSON (edgar_fetch.py output).
  2. Ask Claude (model `MODEL_ID` below, MODEL_POLICY: Fable for forensic_triage) for
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

from .forensic_schema import (
    COVERAGE,
    FAMILIES,
    HISTORY_COLUMNS,
    SCHEMA_VERSION,
    required_families,
)
from .forensic_tier import finalize_tier

ROOT = Path(__file__).resolve().parents[1]  # package file -> project root
RUBRICS_DIR = ROOT / "rubrics"
FETCHED_DIR = ROOT / "data" / "fetched"
FLAGS_HISTORY_CSV = ROOT / "data" / "flags_history.csv"

# MODEL_POLICY.md routes forensic_triage to Fable ("false negatives costly"). This lane ran on
# Opus 4.8 from the 2026-06-25 Fable outage until 2026-09-25 because the comment here said
# Fable 404s on this key; MODEL_POLICY records Fable live again since 2026-07-10, so that
# comment was stale for 77 days (board #410). Do not restate availability here: the
# SessionStart model check / `check_model_policy.py --scan` is the authority, and a 404 at
# runtime degrades LOUDLY to FALLBACK_MODEL (see _create_judge_message), never silently.
# Fable 5.1 request rules honoured below: no `thinking: disabled` / budget_tokens, no forced
# tool_choice, no assistant prefill, refusal is a stop_reason (checked before content), and
# content[0] may be a thinking/fallback block (we scan for the text block).
MODEL_ID = "claude-fable-5-1"
# Server-side refusal fallback + 404 fallback. Must be in Fable 5.1's allowed_fallback_models
# (claude-opus-4-8 / claude-opus-5) AND in MODEL_POLICY's ALLOWED set.
FALLBACK_MODEL = "claude-opus-4-8"
# Array-form fallbacks require exactly this header (the "-07-01" header is for fallbacks="default").
FALLBACK_BETA = "server-side-fallback-2026-06-01"
# Accuracy-critical scoring: MODEL_POLICY puts forensic_triage on Fable precisely because a
# false negative is costly, so run it at `high` (the documented floor for intelligence-sensitive
# work) rather than the `low` the Opus 4.8 stopgap used.
JUDGE_EFFORT = "high"
# Thinking shares the max_tokens cap. 20,000 leaves room for high-effort thinking plus the small
# JSON judgment while staying under the SDK's non-streaming guard (~21,333 tokens at its
# 128k-tokens/hour estimate). Non-streaming on purpose: a mid-output refusal fallback then
# omits the declined partial entirely, so the returned text block is always one whole answer.
JUDGE_MAX_TOKENS = 20000
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
    """Pull the answer text out of an Anthropic response object.

    On Fable (thinking always on) content[0] is a `thinking` block, and a server-side fallback
    adds a `fallback` block, so never index content[0]. Structured output returns exactly one
    text block; more than one means the shape is not what we contracted for -> fail closed.
    """
    texts = [b for b in (getattr(response, "content", []) or [])
             if getattr(b, "type", None) == "text"]
    if not texts:
        raise JudgeValidationError("no text block in model response")
    if len(texts) > 1:
        raise JudgeValidationError(f"expected 1 text block, got {len(texts)}")
    return texts[0].text


def build_judge_request(rubric: str, record: dict, *, model: str = MODEL_ID) -> dict:
    """The Messages API kwargs for one judgment (pure; unit-tested for Fable 5.1 validity)."""
    ticker = record.get("ticker", "?")
    system = SYSTEM_PROMPT.format(today=date.today().isoformat())
    user = (
        f"{rubric}\n\n---\n\n# FETCHED DATA FOR {ticker}\n\n"
        f"```json\n{json.dumps(record, indent=2, default=str)[:120000]}\n```\n\n"
        "Apply the rubric and return the structured per-family judgment."
    )
    # `thinking: adaptive` is explicit (not omitted) on purpose: Fable accepts it, and the
    # server-side fallback re-runs THIS request on FALLBACK_MODEL, where an omitted `thinking`
    # would mean NO thinking on Opus 4.8. No sampling params, no prefill, no tool_choice.
    return dict(
        model=model,
        max_tokens=JUDGE_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={
            "effort": JUDGE_EFFORT,
            "format": {"type": "json_schema", "schema": JUDGE_SCHEMA},
        },
    )


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
    base_kwargs = build_judge_request(rubric, record, model=model)

    last_err = None
    for _ in range(MAX_VALIDATION_RETRIES + 1):
        response, degraded = _create_judge_message(client, base_kwargs)
        # Fail CLOSED on ANY abnormal stop, checked BEFORE content is read: `refusal` (content
        # empty or partial), `max_tokens` (thinking + JSON hit the cap -> truncated JSON),
        # pause_turn, etc. mean the structured output did not complete normally, so accepting
        # it could tier on a partial judgment (codex P1). Tolerate None (test fakes that don't
        # surface stop_reason); reject any present value other than end_turn.
        sr = getattr(response, "stop_reason", None)
        if sr is not None and sr != "end_turn":
            detail = getattr(response, "stop_details", None)
            cat = getattr(detail, "category", None) if detail is not None else None
            raise JudgeValidationError(
                f"abnormal model stop_reason={sr!r}"
                + (f" (refusal category={cat!r})" if sr == "refusal" else "")
                + (f" (max_tokens={base_kwargs['max_tokens']} exhausted by thinking+output)"
                   if sr == "max_tokens" else "")
            )
        try:
            text = _extract_json_text(response)
            obj = json.loads(text)
            verdict = validate_judge_output(obj, ticker)
            # A judgment about a different company must never be filed under this one (a
            # zero-flag verdict for the wrong ticker would publish a false Green). Compare
            # class-punctuation-folded (BRK.B == BRK-B); a mismatch retries, then fails closed.
            if _tkey(obj.get("ticker")) != _tkey(ticker):
                raise JudgeValidationError(
                    f"judge answered for ticker {obj.get('ticker')!r}, asked about {ticker!r}")
        except (JudgeValidationError, json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue
        verdict["model_served"] = _served_model(response, base_kwargs["model"], ticker)
        verdict["judge_degraded"] = degraded
        usage = getattr(response, "usage", None)
        if usage is not None:
            # One line per name in the Actions log, so the per-run cost of the Fable routing is
            # measured from real runs instead of estimated (output includes thinking tokens).
            print(f"  usage {ticker}: model={verdict['model_served']} "
                  f"in={getattr(usage, 'input_tokens', '?')} "
                  f"out={getattr(usage, 'output_tokens', '?')}", flush=True)
        return verdict
    raise JudgeValidationError(f"judge output invalid after retries: {last_err}")


def _tkey(t) -> str:
    return str(t or "").strip().upper().replace(".", "-").replace("/", "-")


def _served_model(response, requested: str, ticker: str) -> str:
    """Which model actually produced the judgment; WARN loudly when it isn't the requested one
    (a server-side refusal fallback served it, or the 404 fallback fired)."""
    served = getattr(response, "model", None)
    served = served if isinstance(served, str) and served else requested
    if served.startswith(requested):
        # The API may echo a snapshot-suffixed id for an alias; that is still the policy
        # model, and warning on it would make this warning always-true.
        served = requested
    fell_back = any(getattr(b, "type", None) == "fallback"
                    for b in (getattr(response, "content", []) or []))
    if served != requested or fell_back:
        print(f"WARNING [forensic_triage] {ticker}: judgment served by {served!r}, "
              f"not {requested!r} (fallback fired)", flush=True)
    return served


def _create_judge_message(client, kwargs: dict):
    """One judgment request. Production path: beta endpoint with the server-side refusal
    fallback to FALLBACK_MODEL. `fallbacks` goes in extra_body because the pinned SDK
    (anthropic 0.86.0) has no typed `fallbacks` kwarg: the previous code passed it as a kwarg,
    got a TypeError, and silently dropped to a plain create on every call, so the fallback
    was never actually on.

    Returns (response, degraded) where `degraded` is None on the normal path, else a short
    reason the caller surfaces in the heartbeat and the committed report:
      - a 404 (the model pulled, as in the 2026-06-25 Fable outage) retries ONCE on
        FALLBACK_MODEL;
      - a 400 that names the fallback feature (the beta changed or was withdrawn server-side)
        retries ONCE on the policy model WITHOUT the refusal fallback, so an optional safety
        net going away cannot take the whole lane down.
    Every other error propagates (fail loudly, never swallow)."""
    beta = getattr(client, "beta", None)
    beta_msgs = getattr(beta, "messages", None) if beta is not None else None
    if beta_msgs is None or not hasattr(beta_msgs, "create"):
        # Minimal clients (test doubles) without the beta surface.
        return client.messages.create(**kwargs), None
    try:
        return beta_msgs.create(
            betas=[FALLBACK_BETA],
            extra_body={"fallbacks": [{"model": FALLBACK_MODEL}]},
            **kwargs,
        ), None
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is one of the two cases
        status = getattr(exc, "status_code", None)
        if status == 404 and kwargs.get("model") != FALLBACK_MODEL:
            print(f"WARNING [forensic_triage] model {kwargs.get('model')!r} returned 404 "
                  f"({exc}); retrying on {FALLBACK_MODEL!r}. MODEL_POLICY restoration needed.",
                  flush=True)
            return (beta_msgs.create(**{**kwargs, "model": FALLBACK_MODEL}),
                    f"404 on {kwargs.get('model')}")
        if status == 400 and "fallback" in str(exc).lower():
            print(f"WARNING [forensic_triage] refusal-fallback beta rejected ({exc}); "
                  f"retrying WITHOUT refusal fallback on {kwargs.get('model')!r}.", flush=True)
            return client.messages.create(**kwargs), "refusal fallback unavailable (beta 400)"
        raise


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
    prior_flags: dict | None = None,
    client=None,
    judge=None,
    model: str = MODEL_ID,
) -> dict:
    """Tier one fetched record. Returns a result dict (tier, reason, flags, concerns, status).

    `judge` lets tests inject the per-family verdict directly (skipping the API). In production
    `judge` is None and we call the Anthropic API via call_judge.

    `prior_flags` = the family vector from this ticker's last COMPLETE run (or None); a family
    firing now that was clean then escalates a would-be Green to Yellow (the CLAUDE.md new-flag
    diff rule). The batch drivers load it via `_prior_flags()`.
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
        verdict["model_served"] = None
        verdict["judge_degraded"] = None

    tier, reason = finalize_tier(
        flags=verdict["flags"],
        coverage=coverage,
        subgroup=subgroup,
        critical_governance=verdict["critical_governance"],
        high_severity=verdict["high_severity"],
        corporate_action=verdict["corporate_action"],
        is_new=is_new,
        prior_flags=prior_flags,
    )

    # Idempotency status (codex R2 + 2026-07-17): a structural Data Gap (foreign/stale/
    # not-disclosed) IS complete; a transient fetch failure is NOT (retry next run) UNLESS a
    # signal strong enough to close the evaluation fired. Only a CRITICAL-governance or
    # HIGH-SEVERITY signal closes it — those are actionable on their own (auto-Red / Yellow
    # watch) and worth committing even with statements missing. A mere SOFT one-family flag
    # (e.g. routine 5.02 churn) must NOT mark the name `complete` while its required accounting
    # families never loaded, or `next_batch` would drop it from the cycle and it's never
    # re-screened (codex F6: `any(flags)` was silently closing partially-fetched names).
    has_signal = verdict["critical_governance"] or verdict["high_severity"]
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
        # Which model produced the judgment (None when a verdict was injected). The runner
        # surfaces any name not served by MODEL_ID in the heartbeat note.
        "model_served": verdict.get("model_served"),
        "judge_degraded": verdict.get("judge_degraded"),
    }


def judge_failed_result(record: dict, *, subgroup: str, error: Exception) -> dict:
    """Result for a name whose judgment could not be obtained (refusal through the whole
    fallback chain, max_tokens truncation, malformed output after retries).

    Never Green and never `complete`: it is tiered DataGap (manual review) with status
    `judge_failed`, so next_batch re-screens it next run and the circuit breaker counts it.
    This replaces letting the exception escape, which discarded every name already judged in
    the batch and re-picked the same batch the next day."""
    ticker = record.get("ticker", "?")
    coverage = _coverage_from_record(record, subgroup)
    return {
        "ticker": ticker,
        "subgroup": subgroup,
        "tier": "DataGap",
        "reason": f"judge failed - NOT screened, retries next run ({error})",
        "flags": {fam: 0 for fam in FAMILIES},
        "critical_governance": False,
        "high_severity": False,
        "corporate_action": None,
        "concerns": [],
        "flag_details": f"judge failed: {error}",
        "coverage": coverage,
        "status": "judge_failed",
        "model_served": None,
        "judge_degraded": None,
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
    # judge_failed counts too: a batch where most judgments fail is an API/model problem, and
    # committing it as a page of DataGaps would hide that.
    failed = sum(1 for r in results if r.get("status") in ("fetch_failed", "judge_failed"))
    frac = failed / n
    if frac > CIRCUIT_BREAKER_FRACTION:
        return True, f"{failed}/{n} names fetch_failed/judge_failed ({frac:.0%} > {CIRCUIT_BREAKER_FRACTION:.0%}) — likely broad outage"
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
    prior = _prior_flags()
    results = []
    for t in tickers:
        t = t.upper()
        try:
            rec = load_record(t)
        except FileNotFoundError:
            print(f"  {t}: no fetched record (skipped)")
            continue
        sg = subgroups.get(t, "general")
        res = tier_one(rec, subgroup=sg, is_new=(t in new_set), prior_flags=prior.get(t))
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


def _new_names(path: Path = FLAGS_HISTORY_CSV, wl: Path | None = None) -> set:
    """Tickers in the watchlist with no prior COMPLETE flags_history row (first appearance ->
    auto-Yellow). A fetch_failed / judge_failed row is not a screen, so it must not spend the
    name's first-appearance Yellow (mirrors _prior_flags, which also ignores those rows)."""
    wl = wl or (ROOT / "data" / "watchlist.csv")
    seen_hist = set()
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            has_status = "status" in (reader.fieldnames or [])
            for row in reader:
                status = (row.get("status") or "").strip() if has_status else "complete"
                if status not in ("", "complete"):
                    continue
                seen_hist.add((row.get("ticker") or "").upper())
    new = set()
    if wl.exists():
        with wl.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").upper()
                if t and t not in seen_hist:
                    new.add(t)
    return new


def _prior_flags(path: Path = FLAGS_HISTORY_CSV) -> dict:
    """Latest COMPLETE prior-run family-flag vector per ticker, for the "new flag -> Yellow" rule.

    Returns {TICKER: {family: 0/1}} taken from each ticker's most recent `status=complete` row
    (a `fetch_failed` row is a partial screen, not a reliable baseline; legacy rows without a
    `status` column count as complete). A family firing this run that was clean in this baseline
    escalates a would-be Green to Yellow (see finalize_tier). Rows are read in file order; the
    latest run_date wins (ties -> later row in the file)."""
    out: dict[str, dict] = {}
    latest_date: dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        has_status = "status" in (reader.fieldnames or [])
        for row in reader:
            t = (row.get("ticker") or "").strip().upper()
            if not t:
                continue
            status = (row.get("status") or "").strip() if has_status else "complete"
            if status not in ("", "complete"):
                continue
            rd = (row.get("run_date") or "").strip()
            if t in latest_date and rd < latest_date[t]:
                continue
            latest_date[t] = rd
            out[t] = {fam: (1 if str(row.get(f"{fam}_flag") or "0").strip() in ("1", "1.0")
                            else 0)
                      for fam in FAMILIES}
    return out


if __name__ == "__main__":
    raise SystemExit(main())
