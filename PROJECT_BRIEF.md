# Project Brief — read this first (for reviewers, human or AI)

> 🚧 **Maturity: Work in progress.** This project is partially built / not yet in routine production use. Review it for **direction and approach, not production hardening** — don't over-invest in edge-case, test-coverage, or polish feedback. §2 (status) and §5 (gaps) mark what's intentionally unbuilt.

This file exists so a reviewer can (1) judge how close the project is to its
intended goal and (2) understand the key design decisions **before** giving
feedback. For mechanics — the full workflow, tier system, rubrics, CSV formats,
and the Edgar-Tools tier/quota notes — see `CLAUDE.md` and `README.md`.

> When reviewing, weigh findings against the **success criteria** and the
> **non-goals / accepted tradeoffs** below. This is a **Claude-driven** project:
> Claude is the runtime, the rubrics (`rubrics/*.md`) are the "code," and the
> only compiled artifact is one deterministic ETL script (`sync_watchlist.py`).
> So "where are the tests?" mostly resolves to "is the rubric reasoning sound
> and the workflow well-specified?" — assess it that way. Several "obvious
> improvements" (a single Beneish/F-score number, an unattended pipeline) were
> considered and deliberately declined or deferred; engage the stated rationale.

---

## 1. Intended goal (the "why")

Give the user a **recurring forensic-accounting screen over their coverage
universe** that surfaces US-listed names with accounting irregularities or
quality-of-earnings concerns *worth a deep dive* — and, crucially, surfaces
**the specific concerns**, not just a verdict. The deliverable is a triage list
(Red / Yellow / Green) plus, for each flagged name, *which flag families fired
and the underlying values*, so the user knows where to dig.

Context: the user is a solo, part-time, healthcare-focused investor automating
"signal from noise." Healthcare Services and MedTech are the focus subgroups;
biopharma accounting is explicitly de-prioritized (excluded at sync). The screen
is meant to run on the same coverage universe that feeds the rest of the
workspace (Coverage Manager is the source of truth for *which* names).

## 2. Success criteria — and current status

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Output is **flagged names + specific concerns**, never a single composite score | ✅ Done | Flag-family model in `CLAUDE.md`; Beneish/Dechow/Altman/Sloan computed only as *inputs*; `flags_history.csv` has per-family 0/1 columns + free-text `flag_details` |
| 2 | Watchlist derived from CM universe, re-syncable, US-listed only, biopharma excluded | ✅ Done | `sync_watchlist.py` (CIK-gated, biopharma-excluded, `Sector (JP)`→subgroup map); `--dry-run` reports without writing; preserves `notes` + `added_date` |
| 3 | Sector-aware rubrics (HC services, medtech) on top of a universal base | ✅ Done | `rubrics/general.md` (8 universal families) + `healthcare_services.md` (9) + `medtech.md` (9); routed by `sector_subgroup` in Step 3 |
| 4 | Tiering is **diff-driven**, not just absolute level | ✅ Done (logic) | Tier rules + "Diff > level" doctrine in `CLAUDE.md`; `flags_history.csv` exists to make Green→Yellow / Yellow→Red diffs cheap; new names auto-Yellow on first appearance |
| 5 | Runs end-to-end interactively on the real data surface | ✅ Done | Calibrated 2026-04-17 on an 8-ticker smoke test (AAPL/CVNA/AHCO/CVS/HIMS/JNJ/DXCM/TMDX) via Edgar-Tools MCP; report + history + ratios written |
| 6 | Call-budget discipline (Edgar-Tools Pro = 500/day; full run ≫ cap) | 🟡 Designed | Auto-escalation triggers + 3-call baseline + `core=true` batching documented and calibrated, but **not yet exercised on a real full-universe run** |
| 7 | Unattended weekly run produces a usable report | 🟢 Built 2026-06-24 (Path A) | **GitHub Actions cron + Anthropic-API tiering**, hybrid data layer (paid Edgar REST primary + free `edgartools` for note bodies, REST-down fallback). `edgar_fetch.py` / `tier_batch.py` / `notify.py` / `run_unattended.py` / `.github/workflows/forensic_triage.yml` all built; 48 tests pass. **NOT yet enabled** — awaits Codex review + 5 GH secrets + 1 live smoke. Supersedes the degraded claude.ai trigger |
| 8 | Notify the user when flags change | 🟢 Built 2026-06-24 | `notify.py`: #forensic-flags Block Kit result card + #status-reports v1 heartbeat (context blocks use `elements[]`) + `if: failure()` alarm. Needs a NEW `SLACK_WEBHOOK_FORENSIC` webhook created + set as a repo secret |
| 9 | First real triage run over the universe | ⬜ Not yet | `flags_history.csv` still holds the recalibration baseline; the unattended pipeline has not yet made a LIVE EDGAR/Fable-5 run (deliberately — no API spend during the build). Idempotent "a few/day" cadence: `next_batch.py` reports 266/274 domestic still pending |

**Overall: the framework AND the unattended Path A automation are now built and
test-covered (48 tests); the screen is not yet in routine production.** The rubric
reasoning, tier logic, and flag-family approach all worked in calibration (AHCO
Red-tier caught even on the degraded fallback). What's pending is *operational*:
a Codex review of the Path A build, provisioning 5 GH Actions secrets (incl. a new
#forensic-flags webhook), one LIVE smoke run (real EDGAR fetch + real Fable-5 tier
on 1-2 names), then flipping the cron on and disabling the old claude.ai trigger.

## 3. Key design decisions (and why)

1. **Flagged list, not a composite score.** The single most load-bearing
   decision. A Beneish M / Dechow F / Altman Z / Sloan number *hides the why*,
   and the why is what tells the user where to dig. So composites are computed
   as **inputs to flag rules**, never as the headline. (If a reviewer wants to
   re-propose a scalar score, engage this rationale directly.)
2. **Flag *families*, fired in combination — not single-ratio triggers.** A
   company is flagged when *multiple* families fire (or one critical governance
   signal). Single-ratio flags are noisy; combinations are signal.
3. **Diff over level.** A name moving Green→Yellow this week is more interesting
   than one Yellow for six months. The whole point of persisting
   `flags_history.csv` is cheap run-over-run diffs.
4. **Claude is the runtime; rubrics are markdown; data is CSV.** Same philosophy
   as `biotech_triage/`. The only Python is `sync_watchlist.py` (deterministic
   ETL). Analytical judgment that resists clean codification (reading note text,
   weighing combinations) stays in the model + rubric, not in brittle code.
5. **CM is the universe authority; this tool only screens.** Ticker adds/removes
   happen in Coverage Manager and flow in via sync — `watchlist.csv` is not
   hand-edited for membership (only the `notes` column is). Keeps one source of
   truth for "what do I cover."
6. **Edgar-Tools MCP over web search for anything financial.** It bundles many
   signals into `company_brief`, which is what makes the call budget tractable;
   WebSearch is reserved for what EDGAR lacks (short interest, borrow, recent press).
7. **Auto-escalation instead of always-pull.** Rather than 6 calls/ticker
   blindly, a cheap 3-call baseline runs first and only escalates to
   `financial_statements` / `edgar_notes` when a trigger fires — to stay under
   the 500/day Pro cap on a multi-hundred-name universe.

## 4. Non-goals / accepted tradeoffs

- **Not** a buy/sell or valuation tool — it's a *triage* that says "go look
  here," nothing more. No position sizing, no price targets.
- **Not** a biopharma accounting screen — biopharma is excluded at sync by
  design (de-prioritized for this user's accounting concerns).
- **Not** a real-time monitor — batch, weekly (or on demand). The machine must
  be on for interactive runs.
- **Not** committed to full unattended automation. The trigger exists but runs
  degraded; staying interactive-as-source-of-truth is an accepted v1 stance
  (see §5). Don't treat the partial trigger as a bug to "fix" without weighing
  the Path A/B decision below.
- **Not** independent of Edgar-Tools Pro — the rubric needs ~80% of fields gated
  behind Pro ($24.99/mo). Free tier returns `upgrade_required` for most ratios
  and TOC-only note bodies; that dependency is accepted.

## 5. Known gaps / candidate next steps (feedback welcome here)

- **No full-universe run has happened yet (§2 #9).** The biggest open item is
  simply *operational* — prove the screen on real names, not just calibration.
- **The unattended trigger is degraded.** claude.ai MCP connectors don't reach
  scheduled triggers, so the Saturday run can't use Edgar-Tools or post to Slack.
  Two paths, undecided: **Path A** — build an `edgartools` Python helper that
  pulls per-ticker JSON + add a Slack webhook (restores full quality unattended);
  **Path B** — drop the trigger, keep interactive-only. A hybrid (interactive
  proves value, decide later) was the standing recommendation. *Which path is
  worth it is the single most useful judgment a reviewer can offer.*
- **No automated tests and no health heartbeat.** There is no `tests/` dir
  (`.pytest_cache` is empty) — acceptable for a rubric-driven tool, but
  `sync_watchlist.py` (the one deterministic piece) is untested, and there's no
  `#status-reports` heartbeat like the rest of the fleet, so a silent
  trigger failure is invisible.
- **`Core` flag is propagated but unused.** Could weight tiering toward core
  names; currently inert.
- **`financial_trends` data quirks** (missing `revenue`/`gross_profit` arrays on
  some names) require a fallback call — documented in `CLAUDE.md`, not yet hardened.
- **No ratio-computation helper.** If computing Beneish/Dechow/Sloan across the
  universe becomes a bottleneck, a Python helper was floated but deferred.

## 6. How to evaluate

- **Core "logic" = the rubrics.** Read `rubrics/general.md`,
  `rubrics/healthcare_services.md`, `rubrics/medtech.md`, plus the workflow +
  tier system in `CLAUDE.md`. Judge whether the flag families, thresholds, and
  combination rules would actually catch real accounting problems without
  excessive false positives.
- **Only deterministic code:** `sync_watchlist.py` (CM→watchlist ETL, US/CIK
  gate, biopharma exclusion, subgroup mapping, notes preservation). Run
  `python sync_watchlist.py --dry-run` to see adds/removes without writing.
  There are no unit tests to run.
- **Worked example:** `reports/forensic_2026-04-17_smoketest.md` and the
  matching rows in `data/flags_history.csv` show the screen's output on the
  8-ticker calibration (note the AHCO Red-tier and the DXCM/TMDX accruals
  catches).
- **Most useful feedback:**
  1. Are the rubric thresholds/combinations well-calibrated, or will they over-
     or under-fire on a real ~329-name universe?
  2. Path A vs. Path B on the unattended trigger (§5) — is restoring full-quality
     automation worth the helper-script build, or is interactive-only fine?
  3. Is the auto-escalation / call-budget scheme realistic against the 500/day
     Pro cap, or will a full run blow through it?
