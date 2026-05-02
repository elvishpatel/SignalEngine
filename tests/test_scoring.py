from __future__ import annotations

import pytest

from signal_engine.scoring.engine import SignalScorer


def test_confidence_formula_with_known_inputs():
    scorer = SignalScorer(
        settings={
            "signal_weights": {
                "VOLUME_SPIKE": 0.30,
                "BULK_DEAL": 0.35,
                "SECTOR_ROTATION": 0.20,
                "PROMOTER_CHANGE": 0.15,
            },
            "risk_filter": {"signal_validity_days": 2},
        }
    )
    events = [
        {
            "event_id": "1",
            "symbol": "SBIN",
            "event_type": "VOLUME_SPIKE",
            "timestamp": "2024-01-15T16:00:00",
            "raw_signal_strength": 4.0,
            "source": "nse_bhavcopy",
            "quality_score": 1.0,
            "metadata": {"diversity_factor": 1.2},
        },
        {
            "event_id": "2",
            "symbol": "SBIN",
            "event_type": "BULK_DEAL",
            "timestamp": "2024-01-15T16:00:00",
            "raw_signal_strength": 2.0,
            "source": "nse_bulk_deals",
            "quality_score": 0.8,
            "metadata": {"diversity_factor": 1.2},
        },
    ]
    signal = scorer.score(events)
    assert signal["confidence"] == pytest.approx(2.052, rel=1e-6)
    assert signal["drivers"] == ["VOLUME_SPIKE", "BULK_DEAL"]
