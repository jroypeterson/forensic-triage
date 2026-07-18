"""Tests for the deterministic false-Green guard (forensic_tier.finalize_tier)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensic_schema import FAMILIES  # noqa: E402
from forensic_tier import finalize_tier, green_eligible  # noqa: E402


def _cov(subgroup="hc_services", **overrides):
    """All required families complete by default; override specific ones."""
    base = {f: "complete" for f in FAMILIES}
    base["sector"] = "complete" if subgroup != "general" else "not_applicable"
    base.update(overrides)
    return base


def _flags(*fired):
    return {f: (1 if f in fired else 0) for f in FAMILIES}


# --- Green eligibility (required vs optional matrix) ---

def test_green_eligible_full_coverage():
    assert green_eligible(_cov(), "hc_services") is True


def test_optional_family_not_evaluated_still_green_eligible():
    # market + text are OPTIONAL — not_evaluated must NOT block Green.
    assert green_eligible(_cov(market="not_evaluated", text="not_evaluated"), "hc_services") is True


def test_required_family_unavailable_blocks_green():
    assert green_eligible(_cov(balance_sheet="unavailable"), "hc_services") is False


def test_sector_required_for_hc_optional_for_general():
    assert green_eligible(_cov(subgroup="general", sector="not_evaluated"), "general") is True
    assert green_eligible(_cov(sector="unavailable"), "hc_services") is False


# --- Tiering ---

def test_green_zero_families_full_coverage():
    tier, _ = finalize_tier(flags=_flags(), coverage=_cov(), subgroup="hc_services")
    assert tier == "Green"


def test_one_benign_family_is_green():
    tier, _ = finalize_tier(flags=_flags("leverage"), coverage=_cov(), subgroup="hc_services")
    assert tier == "Green"  # 0-1 rule


def test_two_families_yellow():
    tier, _ = finalize_tier(flags=_flags("balance_sheet", "sector"), coverage=_cov(), subgroup="hc_services")
    assert tier == "Yellow"


def test_three_families_red():
    tier, _ = finalize_tier(flags=_flags("balance_sheet", "sector", "leverage"),
                            coverage=_cov(), subgroup="hc_services")
    assert tier == "Red"


def test_critical_governance_auto_red():
    tier, why = finalize_tier(flags=_flags(), coverage=_cov(), subgroup="hc_services",
                              critical_governance=True)
    assert tier == "Red" and "critical" in why.lower()


def test_critical_governance_overrides_datagap():
    # A known 4.02 must NOT be masked by incomplete coverage.
    tier, _ = finalize_tier(flags=_flags(), coverage=_cov(balance_sheet="unavailable"),
                            subgroup="hc_services", critical_governance=True)
    assert tier == "Red"


def test_single_high_severity_family_yellow():
    tier, _ = finalize_tier(flags=_flags("balance_sheet"), coverage=_cov(),
                            subgroup="hc_services", high_severity=True)
    assert tier == "Yellow"


def test_high_severity_plus_two_families_red():
    tier, _ = finalize_tier(flags=_flags("balance_sheet", "sector"), coverage=_cov(),
                            subgroup="hc_services", high_severity=True)
    assert tier == "Red"


def test_datagap_when_required_incomplete_and_no_signal():
    tier, why = finalize_tier(flags=_flags(), coverage=_cov(sector="unavailable"),
                              subgroup="hc_services")
    assert tier == "DataGap" and "sector" in why


def test_signal_with_incomplete_coverage_is_yellow_watch():
    # A fired family while required coverage is incomplete -> Yellow watch, not DataGap, not Green.
    tier, _ = finalize_tier(flags=_flags("revenue"), coverage=_cov(sector="unavailable"),
                            subgroup="hc_services")
    assert tier == "Yellow"


def test_corporate_action_only_without_accounting_concern():
    tier, _ = finalize_tier(flags=_flags(), coverage=_cov(), subgroup="medtech",
                            corporate_action="merger closed")
    assert tier == "CorporateAction"


def test_corporate_action_yields_to_accounting_concern():
    # Take-private + a critical governance signal -> Red wins (don't dismiss a real concern).
    tier, _ = finalize_tier(flags=_flags(), coverage=_cov(), subgroup="medtech",
                            corporate_action="merger closed", critical_governance=True)
    assert tier == "Red"


def test_new_name_auto_yellow():
    tier, _ = finalize_tier(flags=_flags(), coverage=_cov(), subgroup="hc_services", is_new=True)
    assert tier == "Yellow"


# --- "new flag this run" diff rule (F5) ---

def test_new_flag_since_clean_last_run_is_yellow():
    # A single family fires now that was CLEAN in the last complete run -> Yellow, not Green
    # (CLAUDE.md new-flag rule; would-be Green under the 0-1 rule without the diff).
    prior = _flags()  # last run: nothing fired
    tier, why = finalize_tier(flags=_flags("revenue"), coverage=_cov(), subgroup="hc_services",
                              prior_flags=prior)
    assert tier == "Yellow"
    assert "new flag" in why.lower() and "revenue" in why


def test_persisting_single_flag_stays_green():
    # The SAME single benign family fired last run and this run -> still Green (Diff > level: a
    # six-month-old flag is not news; only a NEW flag escalates).
    prior = _flags("revenue")
    tier, _ = finalize_tier(flags=_flags("revenue"), coverage=_cov(), subgroup="hc_services",
                            prior_flags=prior)
    assert tier == "Green"


def test_no_prior_baseline_single_flag_is_green():
    # No prior_flags baseline (None) must NOT spuriously escalate every flag — a genuinely
    # first-seen name is handled by is_new instead. One benign family, no baseline -> Green.
    tier, _ = finalize_tier(flags=_flags("revenue"), coverage=_cov(), subgroup="hc_services",
                            prior_flags=None)
    assert tier == "Green"


def test_new_flag_with_two_families_still_yellow_reason_prefers_count():
    # Two families already Yellow by count; prior baseline present shouldn't break that path.
    prior = _flags()
    tier, _ = finalize_tier(flags=_flags("revenue", "leverage"), coverage=_cov(),
                            subgroup="hc_services", prior_flags=prior)
    assert tier == "Yellow"


def test_missing_coverage_key_defaults_unavailable_not_green():
    # Defensive: absent coverage info must not be read as clean.
    cov = {f: "complete" for f in FAMILIES}
    del cov["governance"]
    assert green_eligible(cov, "hc_services") is False
