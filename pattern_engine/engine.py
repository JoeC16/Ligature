"""Pattern engine — pure computation, no Neo4j.

For every injury, looks back LOOKBACK_DAYS across that athlete's own
SessionMetric and WellnessEntry history, scores which fields deviated from
*that athlete's own* baseline (never a population baseline), and:

- writes a PRECEDED edge from every SessionMetric in the window that
  deviated, to the injury (schema only puts SessionMetric on the source
  side of PRECEDED — WellnessEntry deviation feeds the signature below,
  but never gets its own PRECEDED edge)
- builds a "deviation signature" (which fields deviated, in which
  direction) per injury, then clusters injuries across the whole athlete
  pool by shared-signature overlap into SIMILAR_PATTERN_TO edges

Every function here takes and returns plain dicts/lists — no Neo4j driver
objects — so it can be tested against seed/generators.py's real synthetic
output directly, without a live database.
"""

from __future__ import annotations

from datetime import date, timedelta

LOOKBACK_DAYS = 14
Z_THRESHOLD = 2.0
SIMILARITY_THRESHOLD = 0.5

# A single field crossing Z_THRESHOLD by chance isn't rare enough to act
# on alone — with ~4 metric fields x ~4 sessions, or 5 wellness fields x 14
# days in a lookback window, *something* clears even 2 std devs on pure
# noise more often than feels safe (multiple-comparisons problem, confirmed
# empirically against seed/generators.py's own noise before picking these
# numbers). Requiring
# >=2 fields to co-deviate on the same day cuts a single-field ~6-7% hit
# rate to a two-field joint rate an order of magnitude smaller; requiring
# a wellness field to reappear on >=2 separate flagged days on top of that
# controls the many-trials wellness window specifically.
MIN_METRIC_FIELDS = 2
MIN_WELLNESS_FIELDS = 2
MIN_WELLNESS_OCCURRENCES = 2

# Fields where a rise vs. the athlete's own baseline is the concerning
# direction (load), vs. fields where a fall is concerning (recovery).
METRIC_FIELDS_UP = ["hsr_distance_m", "sprint_count", "accel_decel_load", "total_distance_m"]
WELLNESS_FIELDS_DOWN = ["sleep_hours", "sleep_quality", "hrv", "mood"]
WELLNESS_FIELDS_UP = ["soreness"]


def _d(value: str) -> date:
    return date.fromisoformat(value)


def _baseline_stats(values: list[float]) -> tuple[float, float]:
    """(mean, std) with a small floor on std so a near-constant baseline
    doesn't produce absurd z-scores from tiny noise."""
    values = [v for v in values if v is not None]
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    mean = sum(values) / n
    if n < 2:
        return (mean, 0.0)
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std = variance**0.5
    std = max(std, abs(mean) * 0.02, 1e-6)
    return (mean, std)


def _zscore(value: float | None, mean: float, std: float) -> float | None:
    if value is None or std == 0:
        return None
    return (value - mean) / std


def _confidence_from_zs(abs_zs: list[float]) -> float:
    """Smooth 0-1 mapping from deviation magnitude — bounded, monotonic,
    no arbitrary per-case constants beyond the threshold itself."""
    if not abs_zs:
        return 0.0
    mean_abs_z = sum(abs_zs) / len(abs_zs)
    return round(1 - 1 / (1 + mean_abs_z), 2)


def _split_window(rows: list[dict], injury_date: date, date_key: str = "date"):
    """(window_rows, baseline_rows) — baseline excludes the lookback
    window AND anything on/after the injury date itself (retrospective:
    nothing after onset should inform either the window or the baseline)."""
    window_start = injury_date - timedelta(days=LOOKBACK_DAYS)
    window, baseline = [], []
    for row in rows:
        d = _d(row[date_key])
        if d >= injury_date:
            continue
        if window_start <= d < injury_date:
            window.append(row)
        else:
            baseline.append(row)
    return window, baseline


def _metric_baselines_by_type(baseline_metrics: list[dict]) -> dict[str, dict[str, tuple[float, float]]]:
    by_type: dict[str, dict[str, list[float]]] = {}
    for m in baseline_metrics:
        bucket = by_type.setdefault(m["type"], {f: [] for f in METRIC_FIELDS_UP})
        for f in METRIC_FIELDS_UP:
            if m.get(f) is not None:
                bucket[f].append(m[f])
    return {t: {f: _baseline_stats(vals) for f, vals in fields.items()} for t, fields in by_type.items()}


def _wellness_baseline(baseline_wellness: list[dict]) -> dict[str, tuple[float, float]]:
    fields = WELLNESS_FIELDS_DOWN + WELLNESS_FIELDS_UP
    return {f: _baseline_stats([w.get(f) for w in baseline_wellness if w.get(f) is not None]) for f in fields}


def _deviating_metric_fields(m: dict, baselines: dict[str, tuple[float, float]]) -> dict[str, float]:
    deviating = {}
    for f in METRIC_FIELDS_UP:
        mean, std = baselines.get(f, (0.0, 0.0))
        z = _zscore(m.get(f), mean, std)
        if z is not None and z >= Z_THRESHOLD:  # concerning direction: up
            deviating[f] = z
    return deviating


def _deviating_wellness_fields(w: dict, baselines: dict[str, tuple[float, float]]) -> dict[str, float]:
    deviating = {}
    for f in WELLNESS_FIELDS_DOWN:
        mean, std = baselines.get(f, (0.0, 0.0))
        z = _zscore(w.get(f), mean, std)
        if z is not None and -z >= Z_THRESHOLD:  # concerning direction: down
            deviating[f] = z
    for f in WELLNESS_FIELDS_UP:
        mean, std = baselines.get(f, (0.0, 0.0))
        z = _zscore(w.get(f), mean, std)
        if z is not None and z >= Z_THRESHOLD:  # concerning direction: up
            deviating[f] = z
    return deviating


def compute_injury_pattern(injury: dict, athlete_metrics: list[dict], athlete_wellness: list[dict]) -> dict:
    """Returns {"preceded": [...], "signature": {field: avg_z}} for one injury."""
    injury_date = _d(injury["date"])

    window_metrics, baseline_metrics = _split_window(athlete_metrics, injury_date)
    window_wellness, baseline_wellness = _split_window(athlete_wellness, injury_date)

    metric_baselines = _metric_baselines_by_type(baseline_metrics)
    wellness_baselines = _wellness_baseline(baseline_wellness)

    preceded = []
    metric_signature: dict[str, list[float]] = {}

    for m in window_metrics:
        deviating = _deviating_metric_fields(m, metric_baselines.get(m["type"], {}))
        if len(deviating) < MIN_METRIC_FIELDS:
            continue
        lag_days = (injury_date - _d(m["date"])).days
        preceded.append(
            {
                "metric_id": m["id"],
                "injury_id": injury["id"],
                "lag_days": lag_days,
                "correlation_strength": _confidence_from_zs([abs(z) for z in deviating.values()]),
            }
        )
        for f, z in deviating.items():
            metric_signature.setdefault(f, []).append(z)

    # Wellness fields never get their own PRECEDED edge (schema only puts
    # SessionMetric on that side) — they only feed the signature, and only
    # once a field has shown up on >=MIN_WELLNESS_OCCURRENCES separate
    # co-deviating days, not from a single noisy night.
    wellness_occurrences: dict[str, list[float]] = {}
    for w in window_wellness:
        deviating = _deviating_wellness_fields(w, wellness_baselines)
        if len(deviating) < MIN_WELLNESS_FIELDS:
            continue
        for f, z in deviating.items():
            wellness_occurrences.setdefault(f, []).append(z)

    signature = dict(metric_signature)
    for f, zs in wellness_occurrences.items():
        if len(zs) >= MIN_WELLNESS_OCCURRENCES:
            signature[f] = zs

    avg_signature = {f: sum(zs) / len(zs) for f, zs in signature.items()}
    return {"preceded": preceded, "signature": avg_signature}


def cluster_injuries(injuries: list[dict], signatures: dict[str, dict[str, float]]) -> list[dict]:
    """Pairwise Jaccard similarity of deviating-field sets -> SIMILAR_PATTERN_TO
    edges for pairs clearing SIMILARITY_THRESHOLD. One edge per pair,
    earlier-onset injury first."""
    ordered = sorted(injuries, key=lambda i: i["date"])
    edges = []
    for idx, i in enumerate(ordered):
        sig_i = set(signatures.get(i["id"], {}))
        if not sig_i:
            continue
        for j in ordered[idx + 1 :]:
            sig_j = set(signatures.get(j["id"], {}))
            if not sig_j:
                continue
            shared = sig_i & sig_j
            union = sig_i | sig_j
            if not union:
                continue
            confidence = round(len(shared) / len(union), 2)
            if confidence >= SIMILARITY_THRESHOLD and shared:
                edges.append(
                    {
                        "injury_id_from": i["id"],
                        "injury_id_to": j["id"],
                        "shared_metrics": sorted(shared),
                        "confidence": confidence,
                    }
                )
    return edges


def compute_all(pulled: dict) -> dict:
    """pulled = {"injuries": [...], "metrics_by_athlete": {...}, "wellness_by_athlete": {...}}
    (exactly what pattern_engine/queries.py pulls from Neo4j, or what
    seed/generators.py's output reshapes into for testing)."""
    preceded_all = []
    signatures: dict[str, dict[str, float]] = {}

    for injury in pulled["injuries"]:
        athlete_metrics = pulled["metrics_by_athlete"].get(injury["athlete_id"], [])
        athlete_wellness = pulled["wellness_by_athlete"].get(injury["athlete_id"], [])
        result = compute_injury_pattern(injury, athlete_metrics, athlete_wellness)
        preceded_all.extend(result["preceded"])
        signatures[injury["id"]] = result["signature"]

    similar_pattern_to = cluster_injuries(pulled["injuries"], signatures)

    return {"preceded": preceded_all, "similar_pattern_to": similar_pattern_to, "signatures": signatures}
