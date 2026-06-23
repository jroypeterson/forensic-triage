"""Shared constants for the unattended (Path A) screen — the false-Green guard's vocabulary.

Single source of truth for: the flag families, the per-subgroup required-vs-optional matrix,
the coverage enum, and the tier names. Both the data fetcher (edgar_fetch.py) and the
deterministic finalizer (forensic_tier.py) import from here so the rules can't drift.
"""
from __future__ import annotations

SCHEMA_VERSION = 1

# The nine flag families (mirrors rubrics/general.md + the sector rubrics' `sector` family).
FAMILIES = [
    "accruals", "revenue", "capex", "balance_sheet", "leverage",
    "governance", "market", "text", "sector",
]

# Per-family data coverage for a given name in an unattended run.
#   complete       — fully evaluated from available data
#   partial        — some inputs present, some missing (treated as incomplete for Green)
#   unavailable    — required inputs could not be fetched (a FETCH FAILURE; blocks Green)
#   not_evaluated  — inputs are structurally unreachable unattended (e.g. short interest); for an
#                    OPTIONAL family this does NOT block Green, for a REQUIRED family it does
#   not_applicable — family doesn't apply to this name (e.g. no sector rubric for `general`)
COVERAGE = {"complete", "partial", "unavailable", "not_evaluated", "not_applicable"}
COVERAGE_OK_FOR_GREEN = {"complete", "not_applicable"}  # everything else blocks Green on a REQUIRED family

# Required-vs-optional family matrix (codex R2). A name is Green-eligible only when every
# REQUIRED family is complete/not_applicable. OPTIONAL families may be not_evaluated/partial
# without blocking Green (their inputs — short interest, FDA recalls, transcripts, peer medians —
# are not reachable unattended; interactive runs used WebSearch for them).
#
# Required everywhere: the financial families + governance + the note-backed sector checks.
# Optional everywhere: market (short-interest/borrow) + text (MD&A diffs).
_REQUIRED_BASE = {"accruals", "revenue", "capex", "balance_sheet", "leverage", "governance"}
_OPTIONAL_BASE = {"market", "text"}

# `sector` is REQUIRED for the HC/medtech subgroups (its note-backed checks ARE reachable), and
# not_applicable for `general` (no sector rubric).
REQUIRED_FAMILIES = {
    "hc_services": _REQUIRED_BASE | {"sector"},
    "medtech": _REQUIRED_BASE | {"sector"},
    "general": _REQUIRED_BASE,  # sector is not_applicable
}
OPTIONAL_FAMILIES = {
    "hc_services": _OPTIONAL_BASE,
    "medtech": _OPTIONAL_BASE,
    "general": _OPTIONAL_BASE | {"sector"},
}

TIERS = ("Red", "Yellow", "Green", "DataGap", "CorporateAction")

# flags_history.csv column order (now carries run_id / status / schema_version per codex R2).
HISTORY_COLUMNS = [
    "run_date", "ticker", "tier",
    "accruals_flag", "revenue_flag", "capex_flag", "balance_sheet_flag",
    "leverage_flag", "governance_flag", "market_flag", "text_flag", "sector_flag",
    "flag_details", "run_id", "status", "schema_version",
]


def required_families(subgroup: str) -> set[str]:
    return REQUIRED_FAMILIES.get(subgroup, _REQUIRED_BASE)
