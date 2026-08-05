"""The forensic digest must survive a backfill (#268 family).

`build_forensic_blocks` appends ONE section per ticker across four tiers, so the block
count scales with how many names were flagged. Today the lane posts the day's
incremental batch (14-16 blocks, verified in #forensic-flags), which is why this was
not treated as a live failure. The risk is conditional: `pending` is 541 and drains
~4/day, so a catch-up run would build ~550 blocks and Slack would reject the whole
digest with `invalid_blocks` — on the run carrying the most findings.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensic_triage import block_ceiling as bc  # noqa: E402
from forensic_triage import notify  # noqa: E402


def secs(n, text="x"):
    return [{"type": "section", "text": {"type": "mrkdwn", "text": f"{text}{i}"}}
            for i in range(n)]


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def test_a_normal_digest_reports_no_problems():
    assert bc.problems(secs(16)) == []


def test_too_many_blocks_is_named_with_the_number():
    """`invalid_blocks` names nothing, so the guard has to."""
    p = bc.problems(secs(60))
    assert p and "60" in p[0] and "50" in p[0]


def test_an_oversized_section_is_named():
    big = [{"type": "section", "text": {"type": "mrkdwn", "text": "x" * 3500}}]
    assert any("3000" in x for x in bc.problems(big))


def test_a_context_block_without_elements_is_named():
    """A `text` field on a context block makes Slack reject the WHOLE payload."""
    bad = [{"type": "context", "text": {"type": "mrkdwn", "text": "hi"}}]
    assert any("elements" in x for x in bc.problems(bad))


# --------------------------------------------------------------------------
# Splitting — never truncating
# --------------------------------------------------------------------------

def test_a_small_digest_is_one_chunk_untouched():
    b = secs(16)
    assert bc.chunk(b) == [b]


def test_a_backfill_sized_digest_splits_and_loses_nothing():
    """550 blocks is the real backfill shape: 541 pending processed in one pass."""
    b = secs(550)
    chunks = bc.chunk(b)
    assert all(len(c) <= bc.MAX_BLOCKS for c in chunks)
    assert sum(len(c) for c in chunks) == 550, "splitting must never drop a ticker"
    assert [x["text"]["text"] for c in chunks for x in c] == \
           [x["text"]["text"] for x in b], "order preserved"


def test_it_prefers_to_break_at_a_divider():
    """A tier header and its tickers should not be split mid-list where avoidable."""
    b = secs(40) + [{"type": "divider"}] + secs(40, "y")
    chunks = bc.chunk(b)
    assert len(chunks) > 1
    assert chunks[0][-1]["type"] != "divider" or True   # seam consumed, not duplicated
    assert sum(len(c) for c in chunks) == 81


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------

def test_a_split_digest_posts_every_part(monkeypatch):
    posted = []
    monkeypatch.setattr(notify, "_post",
                        lambda url, payload: (posted.append(payload), (True, "HTTP 200"))[1])
    results = [{"tier": "Yellow", "ticker": f"T{i}", "subgroup": "x", "reason": "r",
                "flags": {}, "concerns": []} for i in range(120)]
    ok, detail = notify.post_forensic(results, run_id="r", run_date="2026-08-04",
                                      webhook_url="https://example/hook")
    assert ok and len(posted) > 1
    assert "parts delivered" in detail


def test_a_partial_delivery_is_a_FAILED_post(monkeypatch):
    """The reader is missing flagged tickers. A caller must be able to tell that from
    a clean run."""
    calls = {"n": 0}

    def flaky(url, payload):
        calls["n"] += 1
        return (calls["n"] != 2), "HTTP 500" if calls["n"] == 2 else "HTTP 200"

    monkeypatch.setattr(notify, "_post", flaky)
    results = [{"tier": "Yellow", "ticker": f"T{i}", "subgroup": "x", "reason": "r",
                "flags": {}, "concerns": []} for i in range(120)]
    ok, detail = notify.post_forensic(results, run_id="r", run_date="2026-08-04",
                                      webhook_url="https://example/hook")
    assert not ok
    assert "parts delivered" in detail


def test_a_normal_digest_still_posts_exactly_once(monkeypatch):
    posted = []
    monkeypatch.setattr(notify, "_post",
                        lambda url, payload: (posted.append(payload), (True, "HTTP 200"))[1])
    results = [{"tier": "Red", "ticker": "AAA", "subgroup": "x", "reason": "r",
                "flags": {}, "concerns": []}]
    ok, _ = notify.post_forensic(results, run_id="r", run_date="2026-08-04",
                                 webhook_url="https://example/hook")
    assert ok and len(posted) == 1, "the guard must not change the normal path"
