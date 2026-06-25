"""Slack notifications for the unattended forensic screen (Path A).

Two destinations:
  - #forensic-flags  (SLACK_WEBHOOK_FORENSIC)        — the screen results, Block Kit.
  - #status-reports  (SLACK_WEBHOOK_STATUS_REPORTS)  — a v1 health heartbeat.

Block Kit GOTCHA (memory: reference_slack_context_block_elements): a `context` block uses
`elements[]`, NOT a `text` field — a `text` field there => webhook HTTP 400 invalid_blocks.
This module only ever builds context blocks with `elements[]`.

Webhook URLs come from the environment; NO hardcoded secrets, and we never log a URL.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

FORENSIC_ENV = "SLACK_WEBHOOK_FORENSIC"
STATUS_ENV = "SLACK_WEBHOOK_STATUS_REPORTS"

TIER_EMOJI = {
    "Red": ":red_circle:",
    "Yellow": ":large_yellow_circle:",
    "Green": ":large_green_circle:",
    "DataGap": ":black_circle:",
    "CorporateAction": ":arrows_counterclockwise:",
}


def _post(webhook_url: str, payload: dict, *, timeout: int = 15) -> tuple[bool, str]:
    """POST a Block Kit payload. Returns (ok, detail). NEVER raises, NEVER logs the URL."""
    if not webhook_url:
        return False, "no webhook url configured"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return (resp.status == 200, f"HTTP {resp.status}: {body[:200]}")
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
    except Exception as exc:  # noqa: BLE001 — never let a Slack failure crash the run
        return False, f"{type(exc).__name__}: {exc}"


def _context(*lines: str) -> dict:
    """A context block — ALWAYS elements[] (never a top-level text field)."""
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": line} for line in lines]}


# --------------------------------------------------------------------------------------
# #forensic-flags result card
# --------------------------------------------------------------------------------------
def build_forensic_blocks(results: list[dict], *, run_id: str, run_date: str, commit: str = "") -> list[dict]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
    summary = "  ".join(f"{TIER_EMOJI.get(t, '')} {t}: {counts.get(t, 0)}" for t in
                        ("Red", "Yellow", "Green", "DataGap", "CorporateAction"))

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Forensic Triage — {run_date}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    ]

    def section_for(tier: str, title: str):
        names = [r for r in results if r["tier"] == tier]
        if not names:
            return
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}})
        for r in names:
            fired = [f for f in r["flags"] if r["flags"].get(f)]
            line = f"• *{r['ticker']}* ({r['subgroup']}) — {r.get('reason', '')}"
            if fired:
                line += f"\n   flags: {', '.join(fired)}"
            concerns = r.get("concerns") or []
            if concerns:
                line += "\n   " + "; ".join(c for c in concerns[:3])
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line[:2900]}})

    section_for("Red", "Red — deep dive")
    section_for("Yellow", "Yellow — watch")
    section_for("DataGap", "Data Gap — manual review (NOT screened)")
    section_for("CorporateAction", "Corporate Action — flag for removal")
    # Green names listed compactly (no per-name section).
    greens = [r["ticker"] for r in results if r["tier"] == "Green"]
    if greens:
        blocks.append({"type": "divider"})
        blocks.append(_context(f"Green ({len(greens)}): " + ", ".join(greens)))

    foot = f"run_id `{run_id}`"
    if commit:
        foot += f" · commit `{commit[:8]}`"
    blocks.append(_context(foot))
    return blocks


def post_forensic(results: list[dict], *, run_id: str, run_date: str, commit: str = "",
                  webhook_url: str | None = None) -> tuple[bool, str]:
    url = webhook_url if webhook_url is not None else os.environ.get(FORENSIC_ENV, "")
    blocks = build_forensic_blocks(results, run_id=run_id, run_date=run_date, commit=commit)
    return _post(url, {"blocks": blocks})


# --------------------------------------------------------------------------------------
# #status-reports heartbeat (v1; Block Kit, context uses elements[])
# --------------------------------------------------------------------------------------
def build_heartbeat_blocks(*, run_id: str, run_date: str, n_screened: int, counts: dict,
                           missing_required: int, commit: str = "", ok: bool = True,
                           note: str = "") -> list[dict]:
    status = ":white_check_mark: healthy" if ok else ":rotating_light: FAILED"
    tier_line = "  ".join(f"{t}: {counts.get(t, 0)}" for t in
                          ("Red", "Yellow", "Green", "DataGap", "CorporateAction"))
    lines = [
        f"*forensic_triage* — {status}",
        f"{run_date} · run_id `{run_id}` · screened {n_screened}",
        tier_line,
        f"missing-required-family names: {missing_required}",
    ]
    if commit:
        lines.append(f"commit `{commit[:8]}`")
    if note:
        lines.append(note)
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Forensic Triage heartbeat*"}},
        _context(*lines),
    ]


def post_heartbeat(*, run_id: str, run_date: str, n_screened: int, counts: dict,
                   missing_required: int, commit: str = "", ok: bool = True, note: str = "",
                   webhook_url: str | None = None) -> tuple[bool, str]:
    url = webhook_url if webhook_url is not None else os.environ.get(STATUS_ENV, "")
    blocks = build_heartbeat_blocks(
        run_id=run_id, run_date=run_date, n_screened=n_screened, counts=counts,
        missing_required=missing_required, commit=commit, ok=ok, note=note,
    )
    return _post(url, {"blocks": blocks})


def post_failure_alarm(*, run_id: str, run_date: str, error: str,
                       webhook_url: str | None = None) -> tuple[bool, str]:
    """Loud failure alarm to #status-reports (the if: failure() path)."""
    url = webhook_url if webhook_url is not None else os.environ.get(STATUS_ENV, "")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": ":rotating_light: *forensic_triage run FAILED*"}},
        _context(f"{run_date} · run_id `{run_id}`", f"error: {error[:400]}"),
    ]
    return _post(url, {"blocks": blocks})


if __name__ == "__main__":  # pragma: no cover — manual smoke (prints blocks, posts nothing)
    import argparse

    ap = argparse.ArgumentParser(description="Print the Block Kit payloads (no Slack post).")
    ap.add_argument("--demo", action="store_true")
    ap.parse_args()
    demo = [
        {"ticker": "ACME", "subgroup": "hc_services", "tier": "Red", "reason": "critical governance (auto-Red)",
         "flags": {f: 0 for f in __import__("forensic_schema").FAMILIES}, "concerns": ["8-K 4.02 non-reliance filed 2026-05"]},
    ]
    print(json.dumps({"blocks": build_forensic_blocks(demo, run_id="demo", run_date="2026-06-24")}, indent=2))
    print(json.dumps({"blocks": build_heartbeat_blocks(run_id="demo", run_date="2026-06-24",
          n_screened=1, counts={"Red": 1}, missing_required=0)}, indent=2))
