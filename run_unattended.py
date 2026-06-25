"""Per-run orchestrator for the unattended (Path A) forensic screen.

Ties the pipeline together (PATH_A_PLAN step 5):
  next_batch  ->  edgar_fetch (per ticker)  ->  tier_batch (Anthropic judge + guardrails)
              ->  append flags_history       ->  write a compact report
              ->  (separately) notify Slack.

The git commit/push happens in the WORKFLOW between the screen step and the notify step (so the
commit hash is known); this script writes a small `data/last_run.json` the notify step reads for
the commit + results. The script NEVER spends API budget when run with --notify-only / --failure-alarm.

Modes:
  (default)         run the screen: fetch + tier + history + report, write last_run.json
  --notify-only     read last_run.json + post #forensic-flags result + #status-reports heartbeat
  --failure-alarm   post a loud failure alarm to #status-reports (the if: failure() path)

Run-level circuit breaker: if the batch can't be evaluated (broad outage), exit non-zero so the
workflow's `if: failure()` alarm fires and NO batch of false Data Gaps is committed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import edgar_fetch  # noqa: E402
import notify  # noqa: E402
import tier_batch  # noqa: E402
from forensic_schema import FAMILIES  # noqa: E402

DATA = ROOT / "data"
REPORTS = ROOT / "reports"
LAST_RUN = DATA / "last_run.json"
WATCHLIST = DATA / "watchlist.csv"
DEFAULT_CYCLE_START = "2026-06-20"


def _load_watchlist() -> dict[str, dict]:
    import csv
    out = {}
    if WATCHLIST.exists():
        with WATCHLIST.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                out[(row.get("ticker") or "").upper()] = row
    return out


def _pick_batch(n: int, cycle_start: str) -> list[str]:
    """Next n un-screened domestic names (reuse next_batch's selection logic)."""
    import next_batch as nb
    watch = nb.load_watchlist()
    domestic = [r for r in watch if r.get("filer_type", "domestic") != "foreign"]
    done = nb.screened_since(cycle_start)
    pending = [r for r in domestic if r["ticker"].strip() not in done]
    pending.sort(key=nb.sort_key)
    return [r["ticker"].strip().upper() for r in pending[:n]]


def run_screen(*, batch_size: int, run_id: str, cycle_start: str) -> int:
    wl = _load_watchlist()
    tickers = _pick_batch(batch_size, cycle_start)
    if not tickers:
        print("Cycle complete — no pending domestic names. Nothing to screen.")
        _write_last_run(run_id=run_id, results=[], note="cycle complete (no pending names)")
        return 0

    print(f"Run {run_id}: screening {len(tickers)} names: {', '.join(tickers)}")
    new_set = tier_batch._new_names()

    results = []
    for ticker in tickers:
        row = wl.get(ticker, {})
        cik = (row.get("cik") or "").strip()
        subgroup = row.get("sector_subgroup") or "general"
        filer_type = row.get("filer_type") or "domestic"

        # 1. fetch (never raises)
        rec = edgar_fetch.fetch_ticker(
            ticker, cik, subgroup=subgroup, filer_type=filer_type, run_id=run_id,
        )
        edgar_fetch.write_record(rec, edgar_fetch.DEFAULT_OUT_DIR)

        # 2. tier (Anthropic judge + deterministic guardrails)
        res = tier_batch.tier_one(rec, subgroup=subgroup, is_new=(ticker in new_set))
        results.append(res)
        print(f"  {ticker:<6} {res['tier']:<16} status={res['status']}  {res['reason']}")

    # 3. run-level circuit breaker (broad outage -> fail loudly, commit nothing)
    tripped, why = tier_batch.circuit_breaker_tripped(results)
    if tripped:
        print(f"\nCIRCUIT BREAKER TRIPPED: {why}")
        _write_last_run(run_id=run_id, results=results, note=f"CIRCUIT BREAKER: {why}", ok=False)
        # Non-zero exit so the workflow alarms and skips the commit.
        return 2

    # 4. append history (only complete + fetch_failed rows; fetch_failed retries next run)
    rows = [tier_batch.result_to_history_row(r, run_id=run_id) for r in results]
    tier_batch.append_history(rows)

    # 5. compact report
    report_path = _write_report(results, run_id=run_id)
    print(f"\nWrote report {report_path}; appended {len(rows)} history rows.")

    _write_last_run(run_id=run_id, results=results, note="ok", ok=True)
    return 0


def _counts(results: list[dict]) -> dict:
    c: dict[str, int] = {}
    for r in results:
        c[r["tier"]] = c.get(r["tier"], 0) + 1
    return c


def _missing_required(results: list[dict]) -> int:
    n = 0
    for r in results:
        cov = r.get("coverage", {})
        if any(cov.get(f) not in ("complete", "not_applicable", None) for f in FAMILIES):
            # any non-complete required-ish family -> count as a name with a coverage gap
            from forensic_schema import required_families
            sg = r.get("subgroup", "general")
            if any(cov.get(f, "unavailable") not in ("complete", "not_applicable")
                   for f in required_families(sg)):
                n += 1
    return n


def _write_report(results: list[dict], *, run_id: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = REPORTS / f"forensic_{today}.md"
    lines = [f"# Forensic Triage — {today}", "", f"_run_id {run_id}_", ""]

    def section(tier: str, title: str):
        names = [r for r in results if r["tier"] == tier]
        if not names:
            return
        lines.append(f"## {title}")
        lines.append("| Ticker | Subgroup | Flags fired | Reason | Concerns |")
        lines.append("|---|---|---|---|---|")
        for r in names:
            fired = ", ".join(f for f in r["flags"] if r["flags"].get(f)) or "-"
            concerns = "; ".join((r.get("concerns") or [])[:3]).replace("|", "/")
            lines.append(f"| {r['ticker']} | {r['subgroup']} | {fired} | {r['reason']} | {concerns} |")
        lines.append("")

    section("Red", "Red (deep dive)")
    section("Yellow", "Yellow (watch)")
    section("DataGap", "Data Gap (manual review — NOT screened)")
    section("CorporateAction", "Corporate Action (flag for removal)")
    greens = [r["ticker"] for r in results if r["tier"] == "Green"]
    if greens:
        lines.append(f"## Green (evaluated clean)\n\n{', '.join(greens)}\n")
    # Append (don't overwrite a same-day earlier run)
    mode = "a" if path.exists() else "w"
    with path.open(mode, encoding="utf-8") as f:
        if mode == "a":
            f.write("\n\n---\n\n")
        f.write("\n".join(lines))
    return path


def _write_last_run(*, run_id: str, results: list[dict], note: str = "", ok: bool = True) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    # Strip the bulky coverage map down for the notify payload; keep what the cards need.
    slim = [
        {
            "ticker": r["ticker"], "subgroup": r["subgroup"], "tier": r["tier"],
            "reason": r["reason"], "flags": r["flags"], "concerns": r.get("concerns", []),
            "status": r.get("status", "complete"), "coverage": r.get("coverage", {}),
        }
        for r in results
    ]
    payload = {
        "run_id": run_id, "run_date": date.today().isoformat(),
        "ok": ok, "note": note, "results": slim,
    }
    with LAST_RUN.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _read_last_run() -> dict:
    if not LAST_RUN.exists():
        return {}
    with LAST_RUN.open(encoding="utf-8") as f:
        return json.load(f)


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return ""


def notify_only(*, run_id: str) -> int:
    data = _read_last_run()
    results = data.get("results", [])
    run_date = data.get("run_date", date.today().isoformat())
    commit = _git_head()

    ok_f, det_f = notify.post_forensic(results, run_id=run_id, run_date=run_date, commit=commit)
    counts = _counts(results)
    missing = _missing_required(results)
    ok_h, det_h = notify.post_heartbeat(
        run_id=run_id, run_date=run_date, n_screened=len(results), counts=counts,
        missing_required=missing, commit=commit, ok=data.get("ok", True), note=data.get("note", ""),
    )
    print(f"forensic post: ok={ok_f} {det_f}")
    print(f"heartbeat post: ok={ok_h} {det_h}")
    # Don't fail the workflow if Slack is flaky — the data is already committed.
    return 0


def failure_alarm(*, run_id: str, error: str) -> int:
    ok, det = notify.post_failure_alarm(
        run_id=run_id, run_date=date.today().isoformat(), error=error,
    )
    print(f"failure alarm: ok={ok} {det}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-size", type=int, default=int(os.environ.get("BATCH_SIZE", "6")))
    p.add_argument("--run-id", default="manual")
    p.add_argument("--cycle-start", default=DEFAULT_CYCLE_START)
    p.add_argument("--notify-only", action="store_true")
    p.add_argument("--failure-alarm", action="store_true")
    p.add_argument("--error", default="run failed")
    args = p.parse_args(argv)

    if args.notify_only:
        return notify_only(run_id=args.run_id)
    if args.failure_alarm:
        return failure_alarm(run_id=args.run_id, error=args.error)
    return run_screen(batch_size=args.batch_size, run_id=args.run_id, cycle_start=args.cycle_start)


if __name__ == "__main__":
    raise SystemExit(main())
