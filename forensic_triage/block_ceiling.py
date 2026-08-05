"""Slack Block Kit ceiling guard — VENDORED, deliberately, not a shim to `_shared/`.

This project runs in GitHub Actions (`.github/workflows/forensic_triage.yml`), and
`<workspace>/_shared/` is a Dropbox sibling that is NOT checked out there. A `sys.path`
shim would import fine on JP's laptop and fail on every CI run — degrading to "post
unchunked" exactly where the guard is needed, while the fleet docs claimed this project
was covered. A guard that is silently inert in production is worse than no guard,
because it stops anyone looking again.

WHY THIS LANE NEEDS IT. `build_forensic_blocks` appends **one section block per ticker**
across four tiers. Today that is fine — the lane posts only the day's incremental batch,
and `#forensic-flags` shows 14–16 blocks per run, which is why this was NOT treated as a
live failure. The risk is conditional and real: `pending` is 541 and drains ~4/day, so a
**backfill or catch-up run that processes the queue in one pass** would build ~550 blocks
and Slack would reject the entire digest with `invalid_blocks` — an error that names
nothing — on the run carrying the most findings.

Canonical implementation + tests: `<workspace>/_shared/slack_blocks/`. If the ceilings
change, that is the copy to fix first; this one is a follower.

Ceilings are Slack's documented Block Kit limits as of 2026-08.
"""
from __future__ import annotations

MAX_BLOCKS = 50
MAX_SECTION_CHARS = 3000
MAX_HEADER_CHARS = 150
MAX_CONTEXT_ELEMENTS = 10


def problems(blocks: list[dict]) -> list[str]:
    """Every ceiling this payload breaks. Empty list == fine.

    Returns rather than raises: the caller's job is to deliver the digest, and the
    decision about what to do with a violation belongs to it.
    """
    out: list[str] = []
    if len(blocks) > MAX_BLOCKS:
        out.append(f"{len(blocks)} blocks exceeds Slack's limit of {MAX_BLOCKS} "
                   f"per message")
    for i, b in enumerate(blocks):
        kind = b.get("type")
        if kind == "section":
            txt = ((b.get("text") or {}).get("text") or "")
            if len(txt) > MAX_SECTION_CHARS:
                out.append(f"block {i} (section) text is {len(txt)} chars, "
                           f"limit {MAX_SECTION_CHARS}")
            if not txt.strip() and not b.get("fields"):
                out.append(f"block {i} (section) has empty text")
        elif kind == "header":
            txt = ((b.get("text") or {}).get("text") or "")
            if len(txt) > MAX_HEADER_CHARS:
                out.append(f"block {i} (header) text is {len(txt)} chars, "
                           f"limit {MAX_HEADER_CHARS}")
        elif kind == "context":
            els = b.get("elements")
            if not isinstance(els, list) or not els:
                # A `text` field on a context block makes Slack reject the WHOLE
                # payload with invalid_blocks. This has bitten the fleet before.
                out.append(f"block {i} (context) must have a non-empty elements[]")
            elif len(els) > MAX_CONTEXT_ELEMENTS:
                out.append(f"block {i} (context) has {len(els)} elements, "
                           f"limit {MAX_CONTEXT_ELEMENTS}")
    return out


def chunk(blocks: list[dict], *, max_blocks: int = MAX_BLOCKS) -> list[list[dict]]:
    """Split into deliverable messages, preferring a divider seam.

    SPLITS, NEVER TRUNCATES. A shorter digest silently drops flagged tickers, which is
    the same class of loss the guard exists to prevent — and the dropped ones would be
    the tail tiers (DataGap, CorporateAction), not the Reds, so the loss would be
    invisible to a reader scanning the top.
    """
    if len(blocks) <= max_blocks:
        return [blocks]
    out, cur = [], []
    for b in blocks:
        cur.append(b)
        if len(cur) >= max_blocks:
            # Prefer to break at the last divider so a tier is not split mid-list.
            seam = max((i for i, x in enumerate(cur) if x.get("type") == "divider"),
                       default=-1)
            if 0 < seam < len(cur) - 1:
                out.append(cur[:seam])
                cur = cur[seam:]
            else:
                out.append(cur)
                cur = []
    if cur:
        out.append(cur)
    return out
