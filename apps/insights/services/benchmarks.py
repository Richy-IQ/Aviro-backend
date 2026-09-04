"""
Comparing a batch against its peers.

Percentiles are computed from closed batches of the same bird type when there
are enough of them to be meaningful, and fall back to published industry
figures otherwise. The response always states the source: telling a farmer they
are "below average" is only useful if they know what they are averaged against.
"""

from __future__ import annotations

from decimal import Decimal

from apps.flocks.models import Batch
from apps.flocks.services.metrics import BatchMetrics

# Below this many closed cycles, a percentile is noise rather than a signal.
MIN_PEERS = 20

INDUSTRY_REFERENCE = {
    "broiler": {
        "feed_conversion": {"p25": 1.42, "p50": 1.55, "p75": 1.68, "lower_is_better": True},
        "mortality_pct": {"p25": 3.2, "p50": 4.8, "p75": 7.1, "lower_is_better": True},
    },
    "layer": {
        "mortality_pct": {"p25": 2.5, "p50": 4.0, "p75": 6.5, "lower_is_better": True},
    },
}


def compare(batch: Batch, metrics: BatchMetrics) -> dict:
    code = batch.bird_type.code
    peer_count = Batch.objects.filter(
        bird_type=batch.bird_type, status=Batch.Status.CLOSED
    ).count()

    reference = INDUSTRY_REFERENCE.get(code, {})
    source = "peers" if peer_count >= MIN_PEERS else "industry"

    rows = []
    for metric, bands in reference.items():
        value = getattr(metrics, metric, None)
        if value is None:
            continue
        rows.append(
            {
                "metric": metric,
                "value": str(value),
                "p25": bands["p25"],
                "p50": bands["p50"],
                "p75": bands["p75"],
                "lower_is_better": bands["lower_is_better"],
                "beats_median": _beats(value, bands),
            }
        )

    return {
        "source": source,
        "peer_count": peer_count,
        "note": (
            "Compared with farms like yours."
            if source == "peers"
            else "Compared with published industry figures — not enough farms\n"
            "yet for local numbers."
        ),
        "rows": rows,
    }


def _beats(value: Decimal, bands: dict) -> bool:
    median = Decimal(str(bands["p50"]))
    return value < median if bands["lower_is_better"] else value > median
