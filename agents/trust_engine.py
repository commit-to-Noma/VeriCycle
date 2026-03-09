from __future__ import annotations

from typing import Iterable

from models import VerificationSignal

SIGNAL_WEIGHTS = {
    "collector_submission": 0.5,
    "qr_scan": 0.4,
    "photo_proof": 0.3,
    "resident_confirmation": 0.2,
    "schedule_match": 0.2,
}

VERIFICATION_THRESHOLD = 0.7


def normalize_signal_weight(signal_type: str) -> float:
    return SIGNAL_WEIGHTS.get(signal_type, 0.0)


def compute_signal_score(signals: Iterable[VerificationSignal]) -> tuple[float, bool]:
    total = 0.0
    has_conflict = False

    seen_positive = set()
    seen_negative = set()

    for signal in signals:
        if signal.is_positive:
            total += float(signal.weight or 0.0)
            seen_positive.add(signal.signal_type)
        else:
            seen_negative.add(signal.signal_type)

    if seen_positive and seen_negative:
        has_conflict = True

    return round(min(total, 1.0), 3), has_conflict


def should_verify(score: float, has_conflict: bool) -> bool:
    return score >= VERIFICATION_THRESHOLD and not has_conflict
