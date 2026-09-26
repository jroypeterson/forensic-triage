"""Fable 5.1 judge: request shape + response parsing through the REAL SDK path (board #410).

No paid call is ever made. The SDK tests build a real `anthropic.Anthropic` client whose HTTP
transport is an in-process `httpx.MockTransport`, so the actual SDK request serialisation
(beta endpoint, `anthropic-beta` header, body) and response parsing (a `thinking` block FIRST,
as Fable always returns) run exactly as in production, minus the network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensic_triage import run_unattended, tier_batch  # noqa: E402
from forensic_triage.forensic_schema import FAMILIES  # noqa: E402

anthropic = pytest.importorskip("anthropic")
httpx = pytest.importorskip("httpx")


def _verdict_json(*fired):
    return json.dumps({
        "ticker": "ACME",
        "flags": {f: (1 if f in fired else 0) for f in FAMILIES},
        "critical_governance": False,
        "high_severity": False,
        "corporate_action": None,
        "concerns": ["DSO +30% YoY"] if fired else [],
        "flag_details": "",
    })


def _message(*, model="claude-fable-5-1", stop_reason="end_turn", text=None,
             extra_blocks=(), stop_details=None):
    """A Messages API response body in the shape Fable 5.1 returns: thinking block first."""
    content = list(extra_blocks) + [
        {"type": "thinking", "thinking": "", "signature": "sig-abc"},
    ]
    if text is not None:
        content.append({"type": "text", "text": text})
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": model,
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": 11000, "output_tokens": 3000},
    }


class _Wire:
    """In-process HTTP transport: records every request, replies from a script."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        status, body = self.replies.pop(0)
        return httpx.Response(status, json=body)

    def client(self):
        return anthropic.Anthropic(
            api_key="test-key", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )

    def body(self, i=0):
        return json.loads(self.requests[i].content)


# --- request builder ------------------------------------------------------------------
def test_request_is_valid_for_fable_5_1():
    kw = tier_batch.build_judge_request("rubric", {"ticker": "ACME"})
    assert kw["model"] == "claude-fable-5-1"
    # thinking: only adaptive is legal (disabled / budget_tokens 400 on Fable)
    assert kw["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in json.dumps(kw["thinking"])
    # no forced tool use, no sampling params, no assistant prefill
    for banned in ("tool_choice", "tools", "temperature", "top_p", "top_k"):
        assert banned not in kw
    assert kw["messages"][-1]["role"] == "user"
    # explicit effort for accuracy-critical scoring; structured output via output_config
    assert kw["output_config"]["effort"] == "high"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    # room for thinking + JSON, but under the SDK's non-streaming guard (~21,333)
    assert 16000 <= kw["max_tokens"] <= 21333


def test_policy_ids():
    assert tier_batch.MODEL_ID == "claude-fable-5-1"
    # the fallback must not be a DEPRECATED id (claude-opus-4-7 was)
    assert tier_batch.FALLBACK_MODEL == "claude-opus-4-8"


# --- real SDK path ----------------------------------------------------------------------
def test_sdk_sends_fallbacks_on_the_wire_and_parses_thinking_first():
    wire = _Wire((200, _message(text=_verdict_json("revenue"))))
    out = tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())
    assert out["flags"]["revenue"] == 1
    assert out["model_served"] == "claude-fable-5-1"
    req = wire.requests[0]
    assert "beta=true" in str(req.url)
    assert tier_batch.FALLBACK_BETA in req.headers.get("anthropic-beta", "")
    body = wire.body()
    # The regression: fallbacks was passed as an SDK kwarg the pinned SDK doesn't know,
    # the TypeError was swallowed, and the request went out WITHOUT it on every call.
    assert body["fallbacks"] == [{"model": "claude-opus-4-8"}]
    assert body["model"] == "claude-fable-5-1"
    assert body["output_config"]["effort"] == "high"
    assert "tool_choice" not in body


def test_sdk_refusal_is_loud_and_never_parsed():
    wire = _Wire((200, _message(stop_reason="refusal", text=None,
                                stop_details={"type": "refusal", "category": "cyber",
                                              "explanation": None})))
    with pytest.raises(tier_batch.JudgeValidationError, match="refusal"):
        tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())


def test_sdk_max_tokens_truncation_is_loud_and_never_parsed():
    # A truncated reply whose text happens to be VALID json must still be rejected.
    wire = _Wire((200, _message(stop_reason="max_tokens", text=_verdict_json())))
    with pytest.raises(tier_batch.JudgeValidationError, match="max_tokens"):
        tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())


def test_sdk_server_side_fallback_is_reported(capsys):
    wire = _Wire((200, _message(
        model="claude-opus-4-8", text=_verdict_json(),
        extra_blocks=[{"type": "fallback", "from": {"model": "claude-fable-5-1"},
                       "to": {"model": "claude-opus-4-8"}}])))
    out = tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())
    assert out["model_served"] == "claude-opus-4-8"
    assert "WARNING" in capsys.readouterr().out


def test_sdk_404_retries_once_on_fallback_loudly(capsys):
    not_found = {"type": "error", "error": {"type": "not_found_error",
                                             "message": "model: claude-fable-5-1"}}
    wire = _Wire((404, not_found), (200, _message(model="claude-opus-4-8", text=_verdict_json())))
    out = tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())
    assert out["model_served"] == "claude-opus-4-8"
    assert wire.body(1)["model"] == "claude-opus-4-8"
    assert "404" in capsys.readouterr().out


def test_sdk_non_404_error_propagates():
    bad = {"type": "error", "error": {"type": "invalid_request_error",
                                       "message": "requires 30-day retention"}}
    wire = _Wire((400, bad))
    with pytest.raises(anthropic.BadRequestError):
        tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())
    assert len(wire.requests) == 1  # not swallowed into a silent second attempt


def test_snapshot_suffixed_id_is_not_a_fallback(capsys):
    wire = _Wire((200, _message(model="claude-fable-5-1-20260901", text=_verdict_json())))
    out = tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())
    assert out["model_served"] == "claude-fable-5-1"
    assert "WARNING" not in capsys.readouterr().out


# --- heartbeat surfacing ----------------------------------------------------------------
def test_heartbeat_note_names_degraded_judgments():
    ok = {"ticker": "AAA", "model_served": tier_batch.MODEL_ID}
    injected = {"ticker": "BBB", "model_served": None}
    assert run_unattended._model_note([ok, injected]) == "ok"
    off = {"ticker": "CCC", "model_served": "claude-opus-4-8"}
    note = run_unattended._model_note([ok, off])
    assert note.startswith("DEGRADED: 1/2") and "CCC=claude-opus-4-8" in note


# --- Codex round 2: resilience ------------------------------------------------------------
def test_sdk_fallback_beta_400_retries_without_it_and_is_reported():
    rejected = {"type": "error", "error": {"type": "invalid_request_error",
                                            "message": "fallbacks: unsupported beta"}}
    wire = _Wire((400, rejected), (200, _message(text=_verdict_json())))
    out = tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=wire.client())
    assert out["model_served"] == "claude-fable-5-1"
    assert out["judge_degraded"] and "refusal fallback unavailable" in out["judge_degraded"]
    retry = wire.body(1)
    assert "fallbacks" not in retry and retry["model"] == "claude-fable-5-1"
    assert "beta=true" not in str(wire.requests[1].url)
    note = run_unattended._model_note([{"ticker": "ACME", **out, "status": "complete"}])
    assert "refusal fallback unavailable" in note


def test_judge_failed_result_is_never_green_or_complete():
    rec = {"ticker": "ACME", "family_coverage": {f: "complete" for f in FAMILIES}}
    res = tier_batch.judge_failed_result(rec, subgroup="general",
                                         error=tier_batch.JudgeValidationError("refusal"))
    assert res["tier"] == "DataGap" and res["status"] == "judge_failed"
    row = tier_batch.result_to_history_row(res, run_id="t")
    assert row["status"] == "judge_failed" and row["tier"] == "DataGap"


def test_circuit_breaker_counts_judge_failures():
    rs = [{"status": "judge_failed"}] * 3 + [{"status": "complete"}]
    tripped, why = tier_batch.circuit_breaker_tripped(rs)
    assert tripped and "judge_failed" in why


def test_run_screen_keeps_judged_names_when_one_judgment_fails(monkeypatch, tmp_path):
    """Before: one JudgeValidationError escaped run_screen and discarded the whole batch."""
    written = {}
    monkeypatch.setattr(run_unattended, "_load_watchlist", lambda: {})
    monkeypatch.setattr(run_unattended, "_pick_batch", lambda n, cs: ["AAA", "BBB", "CCC", "DDD"])
    monkeypatch.setattr(tier_batch, "_new_names", lambda: set())
    monkeypatch.setattr(tier_batch, "_prior_flags", lambda: {})
    monkeypatch.setattr(run_unattended.edgar_fetch, "fetch_ticker",
                        lambda t, cik, **kw: {"ticker": t, "family_coverage": {}})
    monkeypatch.setattr(run_unattended.edgar_fetch, "write_record", lambda rec, d: None)

    def fake_tier_one(rec, **kw):
        if rec["ticker"] == "BBB":
            raise tier_batch.JudgeValidationError("abnormal model stop_reason='max_tokens'")
        return {"ticker": rec["ticker"], "subgroup": "general", "tier": "Green", "reason": "",
                "flags": {f: 0 for f in FAMILIES}, "concerns": [], "status": "complete",
                "coverage": {}, "model_served": tier_batch.MODEL_ID, "judge_degraded": None,
                "flag_details": ""}
    monkeypatch.setattr(tier_batch, "tier_one", fake_tier_one)
    monkeypatch.setattr(tier_batch, "append_history",
                        lambda rows: written.setdefault("rows", rows))
    monkeypatch.setattr(run_unattended, "REPORTS", tmp_path)
    monkeypatch.setattr(run_unattended, "_write_last_run",
                        lambda **kw: written.setdefault("last", kw))

    rc = run_unattended.run_screen(batch_size=4, run_id="t", cycle_start="2026-06-20")
    assert rc == 0
    statuses = {r["ticker"]: r["status"] for r in written["rows"]}
    assert statuses == {"AAA": "complete", "BBB": "judge_failed",
                        "CCC": "complete", "DDD": "complete"}
    assert "JUDGE FAILED" in written["last"]["note"] and "BBB" in written["last"]["note"]
    assert written["last"]["degraded"] is True
    report = next(tmp_path.glob("forensic_*.md")).read_text(encoding="utf-8")
    assert "JUDGE FAILED" in report  # committed record, not only the heartbeat


# --- Codex round 3: downstream consumers ----------------------------------------------------
def test_failed_rows_do_not_spend_the_new_name_yellow(tmp_path):
    hist = tmp_path / "h.csv"
    hist.write_text("run_date,ticker,status" + chr(10)
                    + "2026-09-24,NEWCO,judge_failed" + chr(10)
                    + "2026-09-24,FETCHY,fetch_failed" + chr(10)
                    + "2026-09-24,OLDCO,complete" + chr(10), encoding="utf-8")
    wl = tmp_path / "wl.csv"
    wl.write_text(chr(10).join(["ticker", "NEWCO", "FETCHY", "OLDCO"]) + chr(10),
                  encoding="utf-8")
    assert tier_batch._new_names(hist, wl) == {"NEWCO", "FETCHY"}


def test_heartbeat_shows_degraded_not_healthy():
    from forensic_triage import notify
    txt = json.dumps(notify.build_heartbeat_blocks(
        run_id="t", run_date="2026-09-25", n_screened=5, counts={}, missing_required=0,
        ok=True, degraded=True, note="JUDGE FAILED (not screened, retry next run): BBB"))
    assert "DEGRADED" in txt and "healthy" not in txt


def test_notify_only_excludes_judge_failed_from_screened(monkeypatch):
    seen = {}
    monkeypatch.setattr(run_unattended, "_read_last_run", lambda: {
        "ok": True, "degraded": True, "note": "JUDGE FAILED: BBB", "results": [
            {"ticker": "AAA", "tier": "Green", "status": "complete", "coverage": {}},
            {"ticker": "BBB", "tier": "DataGap", "status": "judge_failed", "coverage": {}}]})
    monkeypatch.setattr(run_unattended, "_git_head", lambda: "")
    monkeypatch.setattr(run_unattended.notify, "post_forensic", lambda *a, **k: (True, ""))
    monkeypatch.setattr(run_unattended.notify, "post_heartbeat",
                        lambda **k: (seen.update(k), (True, ""))[1])
    run_unattended.notify_only(run_id="t")
    assert seen["n_screened"] == 1 and seen["degraded"] is True


# --- Codex round 4: wrong-ticker verdict ----------------------------------------------------
def test_wrong_ticker_verdict_fails_closed_never_green():
    wrong = json.loads(_verdict_json())
    wrong["ticker"] = "WRONG"
    body = json.dumps(wrong)
    wire = _Wire(*[(200, _message(text=body))] * (tier_batch.MAX_VALIDATION_RETRIES + 1))
    with pytest.raises(tier_batch.JudgeValidationError, match="WRONG"):
        tier_batch.call_judge("rubric", {"ticker": "RIGHT"}, client=wire.client())


def test_class_punctuation_is_the_same_ticker():
    v = json.loads(_verdict_json())
    v["ticker"] = "brk.b"
    wire = _Wire((200, _message(text=json.dumps(v))))
    out = tier_batch.call_judge("rubric", {"ticker": "BRK-B"}, client=wire.client())
    assert out["flags"]["revenue"] == 0
