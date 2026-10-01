"""Confirmatory analysis for the sauce.ai/redteam study (RESEARCH.md §5).

This package is deliberately *separate* from the red-team service: the service
is pure stdlib, but the confirmatory models need the scientific Python stack
(pandas / statsmodels / lifelines). Nothing here is imported by the app. It
consumes the service's tidy per-turn export (`/export/tidy.csv`) and fits the
pre-registered models (PREREGISTRATION.md §5).

Only the data-handling layer (`schema`, `io`, `simulate`, `stats_utils`) is
pure stdlib and unit-tested in the service's environment. The model layer
(`models`, `sap`) imports the heavy stack lazily and is exercised by the
`analysis-ci` workflow, not the stdlib `redteam-ci` check.
"""
__all__ = ["schema", "io", "simulate", "stats_utils"]
