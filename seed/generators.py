"""Synthetic data generation for the Ligature seed graph.

Produces one season (~40 weeks) for 5 athletes: a shared team session
calendar, per-athlete SessionMetric and WellnessEntry values generated
around a per-athlete baseline (individual variance matters more than a
population baseline — see CLAUDE.md's pattern engine section), a handful
of injuries, and treatment/rehab/outcome chains for a few of them.

Two of the injuries (both hamstring strains, different athletes) get a
deliberately engineered spike in load metrics and dip in wellness in the
7-10 days before onset. This module bakes that spike into the metric/
wellness values and records which SessionMetric ids were part of each
athlete's lead-up window; `hamstring_pattern.py` uses those ids to write
the PRECEDED / SIMILAR_PATTERN_TO edges that stand in for the pattern
engine's output (see that file's docstring).

All randomness is seeded, so re-running this module produces identical
output — that's what makes the seed script safely rerunnable.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import numpy as np
from faker import Faker

SEED = 42
SEASON_START = date(2024, 8, 6)  # a Tuesday
SEASON_WEEKS = 40

POSITIONS = ["Winger", "Centre-Back", "Striker", "Fullback", "Midfielder"]

# Weekday offsets (0=Mon) from the Tuesday that starts each week, and the
# session type run on that day. Wednesday gym sessions produce no
# SessionMetric (no GPS load data for a weights session).
WEEK_PATTERN = [
    (0, "training"),  # Tue
    (1, "gym"),  # Wed
    (2, "training"),  # Thu
    (4, "match"),  # Sat
]

SESSION_TYPE_SCALE = {"training": 1.0, "match": 1.35}
DRILLS_BY_TYPE = {
    "training": ["possession", "small-sided games", "pressing shape", "set pieces"],
    "match": ["league fixture"],
    "gym": ["lower-body strength", "upper-body strength", "mobility + core"],
}


# Sequential, not random — so IDs (not just values) are identical across
# reruns. Reset at the top of generate_all() so a fresh call starts clean.
_id_counters: dict[str, int] = {}


def _reset_ids() -> None:
    _id_counters.clear()


def _new_id(prefix: str) -> str:
    _id_counters[prefix] = _id_counters.get(prefix, 0) + 1
    return f"{prefix}-{_id_counters[prefix]:04d}"


def week_session_dates(week_idx: int) -> dict[str, date]:
    week_tuesday = SEASON_START + timedelta(weeks=week_idx)
    return {
        session_type: week_tuesday + timedelta(days=offset)
        for offset, session_type in WEEK_PATTERN
    }


def make_athletes(rng: random.Random, np_rng: np.random.Generator, faker: Faker) -> list[dict]:
    athletes = []
    for i, position in enumerate(POSITIONS):
        athlete_id = f"athlete-{i + 1}"
        athletes.append(
            {
                "id": athlete_id,
                "name": faker.name(),
                "position": position,
                "age": int(np_rng.integers(21, 30)),
                # Per-athlete baselines — this is the "own baseline, not
                # population baseline" data the pattern engine (step 3)
                # will later compute deviations against.
                "baseline": {
                    "hsr_distance_m": float(np_rng.uniform(450, 650)),
                    "sprint_count": float(np_rng.uniform(15, 25)),
                    "accel_decel_load": float(np_rng.uniform(60, 90)),
                    "total_distance_m": float(np_rng.uniform(5000, 7000)),
                    "sleep_hours": float(np_rng.uniform(6.8, 8.2)),
                    "sleep_quality": float(np_rng.uniform(3.0, 4.0)),
                    "hrv": float(np_rng.uniform(55, 85)),
                    "soreness": float(np_rng.uniform(2.0, 3.0)),
                    "mood": float(np_rng.uniform(3.0, 4.0)),
                },
            }
        )
    return athletes


def make_sessions() -> list[dict]:
    sessions = []
    for week_idx in range(SEASON_WEEKS):
        for session_date_type, session_date in week_session_dates(week_idx).items():
            sessions.append(
                {
                    "id": _new_id("session"),
                    "date": session_date.isoformat(),
                    "type": session_date_type,
                    "intensity": "high" if session_date_type == "match" else "moderate",
                    "drills": DRILLS_BY_TYPE[session_date_type],
                }
            )
    return sessions


def _spike_windows(injury_leadins: list[dict]) -> dict[str, list[tuple[date, date]]]:
    """athlete_id -> list of (start, end) date ranges to spike, from injury lead-ins."""
    windows: dict[str, list[tuple[date, date]]] = {}
    for leadin in injury_leadins:
        injury_date = leadin["injury_date"]
        start = injury_date - timedelta(days=leadin["lookback_days"])
        end = injury_date - timedelta(days=1)
        windows.setdefault(leadin["athlete_id"], []).append((start, end))
    return windows


def make_metrics_and_wellness(
    np_rng: np.random.Generator,
    athletes: list[dict],
    sessions: list[dict],
    injury_leadins: list[dict],
) -> tuple[list[dict], list[dict], dict[str, list[str]]]:
    """Returns (session_metrics, wellness_entries, spiked_metric_ids_by_injury).

    spiked_metric_ids_by_injury maps injury_leadins[i]['injury_id'] -> the
    SessionMetric ids generated inside that injury's lead-up window, for
    hamstring_pattern.py to wire PRECEDED edges from.
    """
    spike_windows = _spike_windows(injury_leadins)
    injury_id_by_window_key = {
        (leadin["athlete_id"], leadin["injury_date"]): leadin["injury_id"]
        for leadin in injury_leadins
    }

    metrics: list[dict] = []
    spiked_ids: dict[str, list[str]] = {leadin["injury_id"]: [] for leadin in injury_leadins}

    training_or_match_sessions = [s for s in sessions if s["type"] in SESSION_TYPE_SCALE]

    for athlete in athletes:
        baseline = athlete["baseline"]
        athlete_windows = spike_windows.get(athlete["id"], [])

        for session in training_or_match_sessions:
            session_date = date.fromisoformat(session["date"])
            scale = SESSION_TYPE_SCALE[session["type"]]

            in_spike_window = None
            for window_start, window_end in athlete_windows:
                if window_start <= session_date <= window_end:
                    in_spike_window = (window_start, window_end)
                    break

            if in_spike_window is not None:
                load_multiplier = np_rng.uniform(1.4, 1.6)
                noise_sd = 0.05
            else:
                load_multiplier = 1.0
                noise_sd = 0.12

            def value(key: str) -> float:
                noise = np_rng.normal(1.0, noise_sd)
                return round(baseline[key] * scale * load_multiplier * noise, 1)

            metric_id = _new_id("metric")
            metrics.append(
                {
                    "id": metric_id,
                    "session_id": session["id"],
                    "athlete_id": athlete["id"],
                    "hsr_distance_m": value("hsr_distance_m"),
                    "sprint_count": max(0, round(value("sprint_count"))),
                    "accel_decel_load": value("accel_decel_load"),
                    "total_distance_m": value("total_distance_m"),
                }
            )

            if in_spike_window is not None:
                # Find which injury this window belongs to.
                for (a_id, injury_date), injury_id in injury_id_by_window_key.items():
                    if a_id != athlete["id"]:
                        continue
                    window_start = injury_date - timedelta(
                        days=[l["lookback_days"] for l in injury_leadins if l["injury_id"] == injury_id][0]
                    )
                    if window_start == in_spike_window[0]:
                        spiked_ids[injury_id].append(metric_id)

    wellness: list[dict] = []
    season_days = SEASON_WEEKS * 7
    for athlete in athletes:
        baseline = athlete["baseline"]
        athlete_windows = spike_windows.get(athlete["id"], [])

        for day_offset in range(season_days):
            entry_date = SEASON_START + timedelta(days=day_offset)
            in_spike_window = any(start <= entry_date <= end for start, end in athlete_windows)

            noise_sd = 0.06 if in_spike_window else 0.12
            shift = -1.0 if in_spike_window else 0.0  # dip in recovery quality

            sleep_hours = baseline["sleep_hours"] + shift * 0.6 + np_rng.normal(0, noise_sd * baseline["sleep_hours"])
            sleep_quality = np.clip(
                baseline["sleep_quality"] + shift + np_rng.normal(0, noise_sd * baseline["sleep_quality"]), 1, 5
            )
            hrv = max(30.0, baseline["hrv"] + shift * 8 + np_rng.normal(0, noise_sd * baseline["hrv"]))
            soreness = np.clip(
                baseline["soreness"] - shift * 2.5 + np_rng.normal(0, noise_sd * baseline["soreness"]), 1, 10
            )
            mood = np.clip(baseline["mood"] + shift * 0.5 + np_rng.normal(0, noise_sd * baseline["mood"]), 1, 5)

            wellness.append(
                {
                    "id": _new_id("wellness"),
                    "athlete_id": athlete["id"],
                    "date": entry_date.isoformat(),
                    "sleep_hours": round(float(sleep_hours), 1),
                    "sleep_quality": round(float(sleep_quality), 1),
                    "hrv": round(float(hrv), 1),
                    "soreness": round(float(soreness), 1),
                    "mood": round(float(mood), 1),
                }
            )

    return metrics, wellness, spiked_ids


def make_injuries_and_treatment_chains(
    rng: random.Random, athletes: list[dict]
) -> dict:
    """Defines the 6 seed injuries and the treatment/rehab/outcome chains
    attached to 3 of them. Returns all the pieces `seed_data.py` needs,
    plus `injury_leadins` describing which two are the hamstring pair
    that `make_metrics_and_wellness` should spike load/wellness for.
    """
    a = {athlete["id"]: athlete for athlete in athletes}

    physios = [
        {"id": "physio-1", "name": "Dr. Amara Osei"},
        {"id": "physio-2", "name": "Dr. Liam Fitzgerald"},
    ]

    def week_date(week_idx: int, weekday_offset: int) -> date:
        return SEASON_START + timedelta(weeks=week_idx, days=weekday_offset)

    injuries = [
        {
            "id": "injury-athlete1-ankle",
            "athlete_id": "athlete-1",
            "type": "ankle sprain",
            "body_part": "left ankle",
            "date": week_date(6, 4).isoformat(),  # standalone, no lead-up spike
            "severity": "minor",
            "mechanism": "awkward landing during small-sided game",
        },
        {
            "id": "injury-athlete1-hamstring",
            "athlete_id": "athlete-1",
            "type": "hamstring strain",
            "body_part": "left biceps femoris",
            "date": week_date(22, 5).isoformat(),
            "severity": "moderate",
            "mechanism": "sprint deceleration during match",
        },
        {
            "id": "injury-athlete2-hamstring",
            "athlete_id": "athlete-2",
            "type": "hamstring strain",
            "body_part": "right biceps femoris",
            "date": week_date(27, 5).isoformat(),
            "severity": "moderate",
            "mechanism": "sprint deceleration during match",
        },
        {
            "id": "injury-athlete3-ankle",
            "athlete_id": "athlete-3",
            "type": "ankle sprain",
            "body_part": "right ankle",
            "date": week_date(12, 2).isoformat(),
            "severity": "minor",
            "mechanism": "tackle during training",
        },
        {
            "id": "injury-athlete4-groin",
            "athlete_id": "athlete-4",
            "type": "groin strain",
            "body_part": "adductor longus",
            "date": week_date(30, 2).isoformat(),
            "severity": "moderate",
            "mechanism": "change-of-direction during training",
        },
        {
            "id": "injury-athlete5-calf",
            "athlete_id": "athlete-5",
            "type": "calf strain",
            "body_part": "right gastrocnemius",
            "date": week_date(35, 0).isoformat(),
            "severity": "minor",
            "mechanism": "sprint during training",
        },
    ]

    # The deliberate hamstring lead-up: 8 days of spiked load/dipped
    # wellness before each onset. This is what make_metrics_and_wellness
    # bakes into the data, and what hamstring_pattern.py points PRECEDED
    # edges at.
    injury_leadins = [
        {
            "injury_id": "injury-athlete1-hamstring",
            "athlete_id": "athlete-1",
            "injury_date": date.fromisoformat(
                [i["date"] for i in injuries if i["id"] == "injury-athlete1-hamstring"][0]
            ),
            "lookback_days": 8,
        },
        {
            "injury_id": "injury-athlete2-hamstring",
            "athlete_id": "athlete-2",
            "injury_date": date.fromisoformat(
                [i["date"] for i in injuries if i["id"] == "injury-athlete2-hamstring"][0]
            ),
            "lookback_days": 8,
        },
    ]

    treatments = []
    rehab_sessions = []
    outcomes = []
    edges_administered = []
    edges_targets = []
    edges_followed_by = []
    edges_produced_outcome = []

    def add_treatment_chain(injury_id: str, physio_id: str, outcome_result: str, notes: str):
        injury = next(i for i in injuries if i["id"] == injury_id)
        injury_date = date.fromisoformat(injury["date"])

        treatment_id = _new_id("treatment")
        treatment_date = injury_date + timedelta(days=1)
        treatments.append(
            {
                "id": treatment_id,
                "injury_id": injury_id,
                "physio_id": physio_id,
                "type": "physio session",
                "date": treatment_date.isoformat(),
                "practitioner": next(p["name"] for p in physios if p["id"] == physio_id),
                "notes": notes,
            }
        )
        edges_administered.append({"physio_id": physio_id, "treatment_id": treatment_id})
        edges_targets.append({"treatment_id": treatment_id, "injury_id": injury_id})

        rehab_id = _new_id("rehab")
        rehab_date = treatment_date + timedelta(days=3)
        days_gap = (rehab_date - treatment_date).days
        rehab_sessions.append(
            {
                "id": rehab_id,
                "treatment_id": treatment_id,
                "date": rehab_date.isoformat(),
                "protocol": "graduated loading — eccentric hamstring/adductor program"
                if "hamstring" in injury["type"] or "groin" in injury["type"]
                else "graduated loading protocol",
                "load_prescribed": "60% 1RM, 3x8",
                "rpe_reported": round(rng.uniform(4.0, 7.0), 1),
                "completed": True,
            }
        )
        edges_followed_by.append({"treatment_id": treatment_id, "rehab_id": rehab_id, "days_gap": days_gap})

        outcome_id = _new_id("outcome")
        outcome_date = rehab_date + timedelta(days=14 if outcome_result == "clean_return" else 9)
        outcomes.append(
            {
                "id": outcome_id,
                "rehab_session_id": rehab_id,
                "result": outcome_result,
                "date": outcome_date.isoformat(),
            }
        )
        edges_produced_outcome.append({"rehab_id": rehab_id, "outcome_id": outcome_id})

    # athlete-1's hamstring: rushed back, re-aggravated.
    add_treatment_chain(
        "injury-athlete1-hamstring",
        "physio-1",
        "re_aggravation",
        "Return-to-play criteria met on strength testing but sprint mechanics not "
        "reassessed before full training resumed.",
    )
    # athlete-2's hamstring: same injury type/mechanism, clean return this time.
    add_treatment_chain(
        "injury-athlete2-hamstring",
        "physio-2",
        "clean_return",
        "Full graduated return-to-sprint protocol completed before training resumed.",
    )
    # athlete-4's groin: unrelated pattern, clean return.
    add_treatment_chain(
        "injury-athlete4-groin",
        "physio-1",
        "clean_return",
        "Adductor strength restored to within 10% of contralateral limb before clearance.",
    )

    # Note: tags are flattened to top-level properties (body_part, severity,
    # assessment) rather than a nested map, since Neo4j node properties
    # can't hold nested maps — only primitives and arrays of primitives.
    clinical_notes = [
        {
            "id": _new_id("note"),
            "injury_id": "injury-athlete1-hamstring",
            "text": "Player reported tightness building through the week leading into the match; "
            "onset during a late sprint. Palpation tender over mid-belly biceps femoris.",
            "body_part": "hamstring",
            "severity": "moderate",
            "assessment": "grade 2 strain",
        },
        {
            "id": _new_id("note"),
            "injury_id": "injury-athlete2-hamstring",
            "text": "Similar presentation to a prior squad case — fatigue and reduced sleep quality "
            "reported in the days before onset, load markedly above the player's own norm.",
            "body_part": "hamstring",
            "severity": "moderate",
            "assessment": "grade 2 strain",
        },
    ]
    edges_has_note = [{"injury_id": n["injury_id"], "note_id": n["id"]} for n in clinical_notes]

    return {
        "physios": physios,
        "injuries": injuries,
        "injury_leadins": injury_leadins,
        "treatments": treatments,
        "rehab_sessions": rehab_sessions,
        "outcomes": outcomes,
        "clinical_notes": clinical_notes,
        "edges": {
            "administered": edges_administered,
            "targets": edges_targets,
            "followed_by": edges_followed_by,
            "produced_outcome": edges_produced_outcome,
            "has_note": edges_has_note,
        },
    }


def generate_all() -> dict:
    _reset_ids()
    rng = random.Random(SEED)
    np_rng = np.random.default_rng(SEED)
    faker = Faker()
    Faker.seed(SEED)

    athletes = make_athletes(rng, np_rng, faker)
    sessions = make_sessions()

    injury_data = make_injuries_and_treatment_chains(rng, athletes)

    session_metrics, wellness_entries, spiked_metric_ids = make_metrics_and_wellness(
        np_rng, athletes, sessions, injury_data["injury_leadins"]
    )

    edges_participated_in = [
        {"athlete_id": athlete["id"], "session_id": session["id"]}
        for athlete in athletes
        for session in sessions
    ]
    edges_produced_metric = [
        {"session_id": m["session_id"], "metric_id": m["id"]} for m in session_metrics
    ]
    edges_reported = [{"athlete_id": w["athlete_id"], "wellness_id": w["id"]} for w in wellness_entries]
    edges_sustained = [
        {"athlete_id": injury["athlete_id"], "injury_id": injury["id"]} for injury in injury_data["injuries"]
    ]

    return {
        "athletes": athletes,
        "sessions": sessions,
        "session_metrics": session_metrics,
        "wellness_entries": wellness_entries,
        "physios": injury_data["physios"],
        "injuries": injury_data["injuries"],
        "treatments": injury_data["treatments"],
        "rehab_sessions": injury_data["rehab_sessions"],
        "outcomes": injury_data["outcomes"],
        "clinical_notes": injury_data["clinical_notes"],
        "spiked_metric_ids_by_injury": spiked_metric_ids,
        "edges": {
            "participated_in": edges_participated_in,
            "produced_metric": edges_produced_metric,
            "reported": edges_reported,
            "sustained": edges_sustained,
            **injury_data["edges"],
        },
    }
