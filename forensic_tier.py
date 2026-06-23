"""Deterministic final tiering — the false-Green guard (codex R1/R2).

Claude (in tier_batch.py) supplies *per-family* judgment: which families fired, the specific
concerns, and whether a governance signal is critical vs soft. This module turns that —
together with the data-coverage map from edgar_fetch.py — into the FINAL tier, deterministically.
Keeping the final decision in code (not the model) guarantees the precedence rules hold every
time: a name is never Green unless every REQUIRED family was actually evaluable, and a known
critical signal (8-K 4.02, high-severity accounting) can never be masked by a data gap.

Precedence (highest first):
  CorporateAction  — a non-accounting structural exit (merger/take-private/delisting) AND no
                     accounting concern at all.
  Red              — critical governance (4.02/restatement/auditor-resignation/NT), OR 3+ families
                     fired, OR a high-severity family corroborated by a second.
  Yellow           — 2 families, OR a single high-severity family, OR a new name (baseline), OR a
                     signal present while required coverage is incomplete ("watch").
  DataGap          — required coverage incomplete AND no positive signal (couldn't evaluate, nothing fired).
  Green            — required coverage complete AND 0-1 (benign) families AND no critical signal.

Critical-governance and high-severity OUTRANK DataGap, so an unevaluable run can still go Red on a
known signal; and "incomplete required coverage" can never land Green.
"""
from __future__ import annotations

from forensic_schema import (
    COVERAGE_OK_FOR_GREEN,
    FAMILIES,
    required_families,
)


def green_eligible(coverage: dict, subgroup: str) -> bool:
    """True only when EVERY required family for this subgroup is complete/not_applicable.

    A missing family defaults to 'unavailable' (the safe assumption — absence of coverage info
    is treated as not-evaluable, never as clean)."""
    for fam in required_families(subgroup):
        if coverage.get(fam, "unavailable") not in COVERAGE_OK_FOR_GREEN:
            return False
    return True


def finalize_tier(
    *,
    flags: dict,
    coverage: dict,
    subgroup: str,
    critical_governance: bool = False,
    high_severity: bool = False,
    corporate_action: str | None = None,
    is_new: bool = False,
) -> tuple[str, str]:
    """Return (tier, reason). `flags` = {family: 0/1} from Claude's judgment."""
    fired = [f for f in FAMILIES if flags.get(f)]
    n = len(fired)
    accounting_concern = bool(critical_governance or high_severity or n)

    # 1. Corporate action only when there is NO accounting concern (else the concern wins).
    if corporate_action and not accounting_concern:
        return "CorporateAction", f"non-accounting corporate action: {corporate_action}"

    # 2. Red — critical signals outrank everything below (incl. DataGap).
    if critical_governance:
        return "Red", "critical governance signal (auto-Red)"
    if n >= 3:
        return "Red", f"{n} flag families fired ({', '.join(fired)})"
    if high_severity and n >= 2:
        return "Red", f"high-severity + {n} families ({', '.join(fired)})"

    coverage_ok = green_eligible(coverage, subgroup)

    # 3. Required coverage incomplete: a present signal -> Yellow (watch); nothing -> DataGap.
    if not coverage_ok:
        if n >= 1 or high_severity:
            return "Yellow", f"signal present but required coverage incomplete -> watch ({', '.join(fired) or 'high-severity'})"
        if is_new:
            return "Yellow", "new name, coverage incomplete -> baseline watch"
        missing = [f for f in required_families(subgroup)
                   if coverage.get(f, "unavailable") not in COVERAGE_OK_FOR_GREEN]
        return "DataGap", f"required coverage incomplete ({', '.join(sorted(missing))}); no signal"

    # 4. Coverage complete -> normal tiering.
    if n >= 2:
        return "Yellow", f"{n} flag families fired ({', '.join(fired)})"
    if high_severity:
        return "Yellow", f"single high-severity family ({', '.join(fired) or '?'})"
    if is_new:
        return "Yellow", "new name (first appearance) -> baseline read"
    # 0 or 1 benign family, fully evaluated.
    return "Green", ("0 families, fully evaluated" if n == 0
                     else f"1 family fired ({fired[0]}), no critical signal -> Green per 0-1 rule")
