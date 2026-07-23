"""Thin root launcher — the logic lives in forensic_triage/run_unattended.py.

Kept at root per CONVENTIONS.md §3b (exactly one entry-point launcher at the
project root) so the CI workflow, scheduled invocations, and the documented
manual trigger `python run_unattended.py --batch-size 2` all keep working
unchanged. Other modules: `python -m forensic_triage.<module>`.
"""
from forensic_triage.run_unattended import main

if __name__ == "__main__":
    raise SystemExit(main())
