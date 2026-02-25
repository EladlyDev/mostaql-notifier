"""Mostaql Notifier — Scorer Package.

Scoring logic for ranking job opportunities based on AI analysis
combined with configurable weights, bonuses, and penalties.
"""

from src.scorer.scoring import ScoringEngine, ScoredJob

__all__ = [
    "ScoringEngine",
    "ScoredJob",
]
