"""The one hand-authored pattern-engine example in the seed data.

CLAUDE.md is explicit that `PRECEDED` and `SIMILAR_PATTERN_TO` edges are
normally *computed by the pattern engine* (build order step 3), never
manually entered. That engine doesn't exist yet, so this module writes a
single, deliberately constructed example instead: two athletes (athlete-1
and athlete-2) each sustain a hamstring strain after 8 days of load
spiking against their own baseline and wellness dipping — the exact shape
of deviation CLAUDE.md's pattern-engine section describes it looking for.

`generators.py` already baked that spike into the SessionMetric and
WellnessEntry values and recorded which SessionMetric ids fall inside each
athlete's lead-up window (`spiked_metric_ids_by_injury`). This module just
draws the edges:

  (SessionMetric)-[:PRECEDED {lag_days, correlation_strength}]->(Injury)
  (Injury)-[:SIMILAR_PATTERN_TO {shared_metrics, confidence}]->(Injury)

Treat this as a fixture, not a general algorithm — it doesn't compute
correlation or deviation from the data, it just labels the spike that was
generated on purpose.
"""

from __future__ import annotations

from datetime import date


def build_pattern_edges(generated: dict) -> dict:
    injuries_by_id = {i["id"]: i for i in generated["injuries"]}
    metrics_by_id = {m["id"]: m for m in generated["session_metrics"]}
    spiked = generated["spiked_metric_ids_by_injury"]

    preceded_edges = []
    for injury_id, metric_ids in spiked.items():
        injury = injuries_by_id[injury_id]
        injury_date = date.fromisoformat(injury["date"])
        for metric_id in metric_ids:
            metric = metrics_by_id[metric_id]
            session_date = _session_date_for_metric(generated, metric)
            lag_days = (injury_date - session_date).days
            preceded_edges.append(
                {
                    "metric_id": metric_id,
                    "injury_id": injury_id,
                    "lag_days": lag_days,
                    # Closer to onset = stronger correlation, in this fixture.
                    "correlation_strength": round(max(0.55, 0.9 - 0.03 * lag_days), 2),
                }
            )

    injury_a, injury_b = "injury-athlete1-hamstring", "injury-athlete2-hamstring"
    similar_pattern_edges = [
        {
            "injury_id_from": injury_a,
            "injury_id_to": injury_b,
            "shared_metrics": ["hsr_distance_m", "accel_decel_load", "sleep_quality"],
            "confidence": 0.82,
        }
    ]

    return {"preceded": preceded_edges, "similar_pattern_to": similar_pattern_edges}


def _session_date_for_metric(generated: dict, metric: dict) -> date:
    sessions_by_id = {s["id"]: s for s in generated["sessions"]}
    return date.fromisoformat(sessions_by_id[metric["session_id"]]["date"])
