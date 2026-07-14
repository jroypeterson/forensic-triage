"""forensic_triage — coverage dashboard.

An ongoing "how far through the universe am I" view, modeled on the transcripts
daily digest. Forensic triage is a *standing process*, not a one-shot task: names
are screened a few per day, and this dashboard shows coverage + freshness across
JP's priority rings so progress (and gaps) are always visible.

Rings (disjoint, priority order — see coverage_cohorts.py):
    Portfolio -> Researching -> Core coverage -> S&P 500  (+ Other residual)

"Screened" = the name has a `flags_history.csv` row dated >= the cycle start with
status=complete (the exact done-definition next_batch.py uses). Per ring we show
screened/total, 🔴/🟡 flag tallies, pending, and (foreign filers) the Data-Gap count
that can't be EDGAR-screened. A day-over-day delta is persisted so the digest shows
motion, and an ETA projects the full-sweep finish at the batch rate.

Surfaces:
  python dashboard.py                 # plaintext to stdout (dry-run; no post, no snapshot)
  python dashboard.py --html          # also write reports/coverage_dashboard.html
  python dashboard.py --post          # post Slack digest (#forensic-flags) + save snapshot
  python dashboard.py --post --html   # both
  python dashboard.py --per-day 6 --cycle-start 2026-06-20
"""
from __future__ import annotations

import argparse
import csv
import html as _html
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import coverage_cohorts as cc

ROOT = Path(__file__).parent
WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"
FLAGS_HISTORY_CSV = ROOT / "data" / "flags_history.csv"
HEALTH_DIR = ROOT / ".health"
HISTORY_PATH = HEALTH_DIR / "dashboard_history.json"
HTML_OUT = ROOT / "reports" / "coverage_dashboard.html"
COHORT_TOTALS_JSON = ROOT / "data" / "cohort_totals.json"

DEFAULT_CYCLE_START = "2026-06-20"
DEFAULT_PER_DAY = 6

SLACK_WEBHOOK_ENV = "SLACK_WEBHOOK_FORENSIC"

# Cohorts shown in the dashboard, priority order.
COHORTS = ["portfolio", "researching", "core", "sp500", "other"]
ACTIONABLE = ("Red", "Yellow")  # the tiers worth surfacing by name


# ---------------------------------------------------------------- data reads

def load_watchlist() -> list[dict]:
    if not WATCHLIST_CSV.exists():
        return []
    with WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def latest_screens(cycle_start: str) -> dict[str, dict]:
    """{TICKER: {tier, flag_details, run_date}} for the LATEST complete screen
    since cycle_start. A status=fetch_failed row does not count (mirrors
    next_batch.screened_since); legacy rows with no status column are complete."""
    out: dict[str, dict] = {}
    if not FLAGS_HISTORY_CSV.exists():
        return out
    with FLAGS_HISTORY_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        has_status = "status" in (reader.fieldnames or [])
        for row in reader:
            rd = (row.get("run_date") or "").strip()
            tk = (row.get("ticker") or "").strip().upper()
            if not tk or rd < cycle_start:
                continue
            status = (row.get("status") or "").strip() if has_status else "complete"
            if status not in ("", "complete"):
                continue
            prev = out.get(tk)
            if prev is None or rd >= prev["run_date"]:
                out[tk] = {
                    "tier": (row.get("tier") or "").strip(),
                    "flag_details": (row.get("flag_details") or "").strip(),
                    "run_date": rd,
                }
    return out


# ---------------------------------------------------------------- gather

def gather(cycle_start: str = DEFAULT_CYCLE_START,
           per_day: int = DEFAULT_PER_DAY,
           today: str | None = None) -> dict:
    today = today or date.today().isoformat()
    watchlist = load_watchlist()
    rosters = cc.load_rosters()
    screens = latest_screens(cycle_start)

    def _cohort(row):
        c = (row.get("cohort") or "").strip()  # baked at sync (CI-safe)
        return c if c else cc.cohort_for(row.get("ticker", ""), rosters)

    # Per-cohort accumulators.
    blank = lambda: {
        "total": 0, "domestic": 0, "foreign": 0,
        "screened": 0, "pending": 0,
        "tiers": {"Red": 0, "Yellow": 0, "Green": 0,
                  "DataGap": 0, "CorporateAction": 0},
        "flagged": [],  # [{ticker, tier, concern}] for Red/Yellow
    }
    coh = {c: blank() for c in COHORTS}

    for r in watchlist:
        tk = (r.get("ticker") or "").strip().upper()
        if not tk:
            continue
        c = _cohort(r)
        b = coh[c]
        b["total"] += 1
        is_foreign = r.get("filer_type") == "foreign"
        if is_foreign:
            b["foreign"] += 1
        else:
            b["domestic"] += 1
        sc = screens.get(tk)
        if sc:
            b["screened"] += 1
            tier = sc["tier"] if sc["tier"] in b["tiers"] else "Green"
            b["tiers"][tier] = b["tiers"].get(tier, 0) + 1
            if sc["tier"] in ACTIONABLE:
                b["flagged"].append({
                    "ticker": tk, "tier": sc["tier"],
                    "concern": _first_concern(sc["flag_details"]),
                })
        elif not is_foreign:
            b["pending"] += 1

    # Disjoint roster sizes = what SHOULD be in each ring, INCLUDING names forensic
    # can't screen (biopharma is excluded at sync; foreign is Data-Gap). Surfacing
    # `excluded` keeps the denominator honest — a hidden 10-name gap on Portfolio
    # reads as "covered" otherwise.
    roster_size = _load_cohort_totals()
    if roster_size is None:  # no baked totals -> compute live from rosters
        p, rr, co, sp = (rosters["portfolio"], rosters["researching"],
                         rosters["core"], rosters["sp500"])
        roster_size = {
            "portfolio": len(p),
            "researching": len(rr - p),
            "core": len(co - rr - p),
            "sp500": len(sp - co - rr - p),
        }
    roster_size = dict(roster_size)
    roster_size["other"] = coh["other"]["total"]
    for c in COHORTS:
        rsize = roster_size.get(c, coh[c]["total"])
        coh[c]["roster"] = rsize
        in_wl = coh[c]["domestic"] + coh[c]["foreign"]
        coh[c]["excluded"] = max(0, rsize - in_wl)

    # Per-ring ETA. Screening runs top-down by priority, so a ring is only complete
    # once everything ABOVE it plus its own pending is screened -> cumulative days.
    # A ring with 0 pending is already complete now (regardless of rings above it).
    cum_pending = 0
    for c in COHORTS:
        b = coh[c]
        cum_pending += b["pending"]
        if b["pending"] == 0:
            b["eta_days"] = 0
            b["eta_date"] = None  # already complete
        elif per_day > 0:
            days = -(-cum_pending // per_day)  # ceil of cumulative pending
            b["eta_days"] = days
            b["eta_date"] = (date.fromisoformat(today) + timedelta(days=days)).isoformat()
        else:
            b["eta_days"] = None
            b["eta_date"] = None

    # Overall roll-up (domestic denominators — foreign are Data-Gap, not screenable).
    dom_total = sum(b["domestic"] for b in coh.values())
    dom_screened = sum(b["screened"] for b in coh.values())
    dom_pending = sum(b["pending"] for b in coh.values())
    red = sum(b["tiers"]["Red"] for b in coh.values())
    yellow = sum(b["tiers"]["Yellow"] for b in coh.values())
    foreign_total = sum(b["foreign"] for b in coh.values())

    eta_date = None
    eta_days = None
    if dom_pending > 0 and per_day > 0:
        eta_days = -(-dom_pending // per_day)  # ceil
        eta_date = (date.fromisoformat(today) + timedelta(days=eta_days)).isoformat()

    # Flagged names across cohorts, priority order then Red-before-Yellow.
    flagged = []
    for c in COHORTS:
        reds = [f for f in coh[c]["flagged"] if f["tier"] == "Red"]
        yels = [f for f in coh[c]["flagged"] if f["tier"] == "Yellow"]
        for f in reds + yels:
            flagged.append({**f, "cohort": c})

    data = {
        "today": today,
        "cycle_start": cycle_start,
        "per_day": per_day,
        "cohorts": coh,
        "totals": {
            "domestic": dom_total, "screened": dom_screened,
            "pending": dom_pending, "foreign": foreign_total,
            "red": red, "yellow": yellow,
            "excluded": sum(b["excluded"] for b in coh.values()),
            "pct": (100.0 * dom_screened / dom_total) if dom_total else 0.0,
        },
        "eta_date": eta_date,
        "eta_days": eta_days,
        "flagged": flagged,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    data["diff"] = _diff_vs_prior(data)
    return data


def _load_cohort_totals() -> dict | None:
    """Baked disjoint roster sizes (CI-safe). None if absent -> compute live."""
    if not COHORT_TOTALS_JSON.exists():
        return None
    try:
        return json.loads(COHORT_TOTALS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def _first_concern(flag_details: str, limit: int = 80) -> str:
    if not flag_details:
        return ""
    s = flag_details.split(";")[0].split("|")[0].strip()
    return (s[: limit - 1] + "…") if len(s) > limit else s


# ---------------------------------------------------------------- day-over-day

def _snapshot_row(data: dict) -> dict:
    return {
        "date": data["today"],
        "screened": data["totals"]["screened"],
        "pending": data["totals"]["pending"],
        "red": data["totals"]["red"],
        "yellow": data["totals"]["yellow"],
        "by_cohort": {c: data["cohorts"][c]["screened"] for c in COHORTS},
    }


def _load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _diff_vs_prior(data: dict) -> dict | None:
    """Compare to the most recent snapshot from a DIFFERENT date."""
    hist = _load_history()
    prior = next((h for h in reversed(hist) if h.get("date") != data["today"]), None)
    if not prior:
        return None
    return {
        "date": prior["date"],
        "screened": data["totals"]["screened"] - prior.get("screened", 0),
        "red": data["totals"]["red"] - prior.get("red", 0),
        "yellow": data["totals"]["yellow"] - prior.get("yellow", 0),
    }


def save_snapshot(data: dict) -> None:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    hist = _load_history()
    hist = [h for h in hist if h.get("date") != data["today"]]  # replace today
    hist.append(_snapshot_row(data))
    hist = hist[-120:]
    HISTORY_PATH.write_text(json.dumps(hist, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- rendering

def _fmt_done_by(iso: str | None, pending: int) -> str:
    if pending == 0:
        return "done"
    if not iso:
        return "-"
    try:
        return date.fromisoformat(iso).strftime("%b %d")  # e.g. "Oct 26"
    except Exception:
        return iso


def _fmt_days(days: int | None, pending: int) -> str:
    if pending == 0:
        return "-"
    return "?" if days is None else str(days)


def _cov_table(data: dict) -> list[str]:
    coh = data["cohorts"]
    head = (f"{'RING':<14}{'SCREENED':>10}  {'R / Y':>6}  {'PEND':>5}  "
            f"{'DAYS':>5}  {'DONE BY':>8}  {'GAP':>4}")
    lines = [head, "-" * len(head)]

    def _row(label, screened, domestic, red, yellow, pending, days, done_by, foreign):
        sc = f"{screened}/{domestic}"
        ry = f"{red} / {yellow}"
        return (f"{label:<14}{sc:>10}  {ry:>6}  {pending:>5}  "
                f"{days:>5}  {done_by:>8}  {foreign:>4}")

    for c in COHORTS:
        b = coh[c]
        if b["total"] == 0:
            continue
        lines.append(_row(cc.COHORT_LABEL[c], b["screened"], b["domestic"],
                          b["tiers"]["Red"], b["tiers"]["Yellow"], b["pending"],
                          _fmt_days(b.get("eta_days"), b["pending"]),
                          _fmt_done_by(b.get("eta_date"), b["pending"]), b["foreign"]))
    t = data["totals"]
    lines.append("-" * len(head))
    total_days = _fmt_days(data.get("eta_days"), t["pending"])
    total_done = _fmt_done_by(data.get("eta_date"), t["pending"])
    lines.append(_row("TOTAL", t["screened"], t["domestic"], t["red"], t["yellow"],
                      t["pending"], total_days, total_done, t["foreign"]))
    return lines


def _excluded_note(data: dict) -> str:
    """One-line per-cohort tally of roster names forensic can't screen (biopharma-
    excluded at sync + not-in-universe). Empty when nothing is excluded."""
    parts = []
    for c in COHORTS:
        n = data["cohorts"][c].get("excluded", 0)
        if n:
            parts.append(f"{cc.COHORT_LABEL[c]} {n}")
    if not parts:
        return ""
    return (f"Not screenable ({data['totals']['excluded']} small-cap biopharma / "
            f"not-in-universe — forensic screens large-cap (S&P 500) biopharma only): "
            + " · ".join(parts))


def to_plaintext(data: dict) -> str:
    t = data["totals"]
    out = []
    out.append(f"forensic_triage - coverage dashboard - {data['today']}")
    hdr = (f"cycle since {data['cycle_start']} - {t['screened']}/{t['domestic']} "
           f"screened ({t['pct']:.0f}%) - {t['red']} red / {t['yellow']} yellow")
    if data["eta_date"]:
        hdr += f" - full-sweep ETA ~{data['eta_date']} ({data['per_day']}/day)"
    out.append(hdr)
    d = data["diff"]
    if d:
        out.append(f"vs {d['date']}: +{d['screened']} screened, "
                   f"{d['red']:+d} red, {d['yellow']:+d} yellow")
    out.append("")
    out.extend(_cov_table(data))
    exc = _excluded_note(data)
    if exc:
        out.append("")
        out.append(exc)
    if data["flagged"]:
        out.append("")
        out.append("Flagged (this cycle):")
        for f in data["flagged"][:20]:
            mark = "R" if f["tier"] == "Red" else "Y"
            concern = f" - {f['concern']}" if f["concern"] else ""
            out.append(f"  [{mark}] {f['ticker']:<6} ({cc.COHORT_LABEL[f['cohort']]}){concern}")
        if len(data["flagged"]) > 20:
            out.append(f"  ... and {len(data['flagged']) - 20} more")
    return "\n".join(out)


def build_blocks(data: dict) -> tuple[list[dict], str]:
    t = data["totals"]
    header_line = (f":mag: *forensic_triage — coverage dashboard* · {data['today']}")
    sub = (f":dart: {t['screened']}/{t['domestic']} screened ({t['pct']:.0f}%) · "
           f":red_circle: {t['red']} · :large_yellow_circle: {t['yellow']}")
    if data["eta_date"]:
        sub += f" · :checkered_flag: full-sweep ETA ~{data['eta_date']} ({data['per_day']}/day)"
    d = data["diff"]
    if d:
        sub += f"\n:arrows_counterclockwise: *vs {d['date']}:* +{d['screened']} screened · {d['red']:+d} red · {d['yellow']:+d} yellow"

    table = "\n".join(_cov_table(data))
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_line}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": sub}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"```\n{table}\n```"}},
    ]
    exc = _excluded_note(data)
    if exc:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": exc}]})
    if data["flagged"]:
        lines = []
        for f in data["flagged"][:15]:
            emo = ":red_circle:" if f["tier"] == "Red" else ":large_yellow_circle:"
            concern = f" — {f['concern']}" if f["concern"] else ""
            lines.append(f"{emo} `{f['ticker']}` _{cc.COHORT_LABEL[f['cohort']]}_{concern}")
        if len(data["flagged"]) > 15:
            lines.append(f"_… and {len(data['flagged']) - 15} more_")
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": "*Flagged (this cycle):*\n" + "\n".join(lines)}})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": f"cohorts: Portfolio → Researching → Core → S&P 500 · "
                                   f"screened = complete forensic run since {data['cycle_start']} · "
                                   f"generated {data['generated_at']}"}]})

    fallback = (f"forensic coverage {data['today']}: {t['screened']}/{t['domestic']} screened, "
                f"{t['red']} red / {t['yellow']} yellow")
    return blocks, fallback


def render_html(data: dict) -> str:
    t = data["totals"]
    rows = []
    for c in COHORTS:
        b = data["cohorts"][c]
        if b["total"] == 0:
            continue
        pct = (100.0 * b["screened"] / b["domestic"]) if b["domestic"] else 0.0
        days = _fmt_days(b.get("eta_days"), b["pending"])
        done_by = _fmt_done_by(b.get("eta_date"), b["pending"])
        done_cls = "dim" if b["pending"] == 0 else ""
        rows.append(
            f"<tr><td class='ring'>{_html.escape(cc.COHORT_LABEL[c])}</td>"
            f"<td class='num'>{b['screened']}/{b['domestic']}</td>"
            f"<td class='bar'><div class='track'><div class='fill' style='width:{pct:.0f}%'></div></div>"
            f"<span class='pct'>{pct:.0f}%</span></td>"
            f"<td class='num red'>{b['tiers']['Red']}</td>"
            f"<td class='num yel'>{b['tiers']['Yellow']}</td>"
            f"<td class='num'>{b['pending']}</td>"
            f"<td class='num {done_cls}'>{days}</td>"
            f"<td class='num {done_cls}'>{done_by}</td>"
            f"<td class='num dim'>{b['foreign']}</td></tr>"
        )
    flagged_rows = []
    for f in data["flagged"]:
        cls = "red" if f["tier"] == "Red" else "yel"
        flagged_rows.append(
            f"<tr><td class='{cls}'>{f['tier']}</td><td class='tk'>{_html.escape(f['ticker'])}</td>"
            f"<td class='dim'>{_html.escape(cc.COHORT_LABEL[f['cohort']])}</td>"
            f"<td>{_html.escape(f['concern'])}</td></tr>"
        )
    flagged_section = ""
    if flagged_rows:
        flagged_section = (
            "<h2>Flagged this cycle</h2><table class='flags'>"
            "<tr><th>Tier</th><th>Ticker</th><th>Ring</th><th>Concern</th></tr>"
            + "".join(flagged_rows) + "</table>"
        )
    diff_line = ""
    if data["diff"]:
        d = data["diff"]
        diff_line = (f"<p class='diff'>vs {d['date']}: +{d['screened']} screened · "
                     f"{d['red']:+d} red · {d['yellow']:+d} yellow</p>")
    eta_line = (f" · full-sweep ETA ~{data['eta_date']} ({data['per_day']}/day)"
                if data["eta_date"] else "")
    return _HTML_TMPL.format(
        today=data["today"], cycle_start=data["cycle_start"],
        screened=t["screened"], domestic=t["domestic"], pct=f"{t['pct']:.0f}",
        red=t["red"], yellow=t["yellow"], eta_line=eta_line, diff_line=diff_line,
        rows="".join(rows), flagged_section=flagged_section,
        generated_at=data["generated_at"],
    )


_HTML_TMPL = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>forensic_triage — coverage dashboard</title>
<style>
:root{{--bg:#0f1115;--card:#171a21;--ink:#e6e9ef;--dim:#8b93a3;--line:#252a34;
--red:#e5534b;--yel:#e0b341;--accent:#4c8dff;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:28px}}
.wrap{{max-width:900px;margin:0 auto}}
h1{{font-size:20px;margin:0 0 4px}}
.sub{{color:var(--dim);margin:0 0 2px}}
.diff{{color:var(--accent);margin:6px 0 0;font-size:14px}}
.tscroll{{overflow-x:auto;margin:20px 0}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;
overflow:hidden;margin:20px 0}}
.tscroll table{{margin:0;min-width:640px}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line)}}
th{{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--dim)}}
tr:last-child td{{border-bottom:none}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.ring{{font-weight:600}}
.red{{color:var(--red);font-weight:600}} .yel{{color:var(--yel);font-weight:600}}
.dim{{color:var(--dim)}}
.bar{{width:34%}}
.track{{display:inline-block;width:calc(100% - 44px);height:8px;background:var(--line);
border-radius:5px;vertical-align:middle;overflow:hidden}}
.fill{{height:100%;background:var(--accent)}}
.pct{{display:inline-block;width:38px;text-align:right;color:var(--dim);font-size:13px}}
.tk{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600}}
.flags td{{font-size:14px}}
footer{{color:var(--dim);font-size:12px;margin-top:24px}}
@media(prefers-color-scheme:light){{:root{{--bg:#f6f7f9;--card:#fff;--ink:#1a1d24;
--dim:#6b7280;--line:#e5e7eb}}}}
</style></head><body><div class="wrap">
<h1>forensic_triage — coverage dashboard</h1>
<p class="sub">{today} · cycle since {cycle_start} · {screened}/{domestic} screened ({pct}%) · {red} red / {yellow} yellow{eta_line}</p>
{diff_line}
<div class="tscroll"><table><tr><th>Ring</th><th class="num">Screened</th><th>Progress</th>
<th class="num">🔴</th><th class="num">🟡</th><th class="num">Pending</th>
<th class="num">Days</th><th class="num">Complete by</th><th class="num">Data-gap</th></tr>
{rows}</table></div>
{flagged_section}
<footer>Rings are disjoint, priority order: Portfolio → Researching → Core → S&amp;P 500. “Screened” = a completed forensic run since the cycle start. Data-gap = foreign filers (20-F/IFRS) the 10-K rubric can’t evaluate. Biopharma is screened only when large-cap (S&amp;P 500). Generated {generated_at}.</footer>
</div></body></html>"""


def post(blocks: list[dict], fallback: str) -> None:
    url = os.environ.get(SLACK_WEBHOOK_ENV, "")
    if not url:
        raise RuntimeError(f"{SLACK_WEBHOOK_ENV} not set — cannot post coverage dashboard")
    payload = json.dumps({"blocks": blocks, "text": fallback}).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Slack post failed: HTTP {resp.status}")


# ---------------------------------------------------------------- CLI

def main() -> int:
    # Windows consoles default to cp1252; forensic flag_details can carry unicode
    # (arrows, ellipses). CI (Linux) is already utf-8. Best-effort reconfigure.
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cycle-start", default=DEFAULT_CYCLE_START)
    p.add_argument("--per-day", type=int, default=DEFAULT_PER_DAY,
                   help="Batch rate for the full-sweep ETA")
    p.add_argument("--post", action="store_true", help="Post to Slack + save day-over-day snapshot")
    p.add_argument("--html", action="store_true", help="Write reports/coverage_dashboard.html")
    args = p.parse_args()

    data = gather(cycle_start=args.cycle_start, per_day=args.per_day)
    print(to_plaintext(data))

    if args.html:
        HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
        HTML_OUT.write_text(render_html(data), encoding="utf-8")
        print(f"\n[html] wrote {HTML_OUT}")

    if args.post:
        blocks, fallback = build_blocks(data)
        post(blocks, fallback)
        save_snapshot(data)
        print("\n[slack] posted to #forensic-flags + saved snapshot")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
