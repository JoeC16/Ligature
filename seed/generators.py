"""Synthetic data generation for the Ligature seed graph.

Produces one season (~40 weeks) for a 30-player squad: a shared team
session calendar, per-athlete SessionMetric and WellnessEntry values
generated around a per-athlete baseline (individual variance matters more
than a population baseline — see CLAUDE.md's pattern engine section), and
a deliberate mix of three scenarios across the squad:

- injury-free (12 athletes) — no Injury node at all. Five of these carry
  a deliberately engineered load-spike + wellness-dip echo in the final
  ~12 days of the season with no injury following it — the "currently
  healthy but showing the same signature as a prior injury" case the
  flagging agent (build order step 6) exists to catch.
- injured and returned (12 athletes) — one injury each, a multi-session
  rehab program, and a final Outcome (clean_return or re_aggravation).
- still injured, ongoing rehab (6 athletes) — one injury each and a
  multi-session rehab program with NO Outcome yet, dated late enough in
  the season that the most recent session reads as "still in progress,"
  not abandoned.

Five athletes (four returned, one still in rehab) share the same
hamstring-strain-preceded-by-a-load-spike signature — a real cross-
athlete cluster for pattern_engine's SIMILAR_PATTERN_TO to find, not a
single isolated pair. This module bakes the spike into the metric/
wellness values (and the injury-free echo cohort's, separately) and
records which SessionMetric ids were part of each lead-in window, for
tests to check the engine's PRECEDED output against.

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

ATHLETE_COUNT = 30
# A realistic squad composition, not an even split.
SQUAD_POSITIONS = (
    ["Goalkeeper"] * 2
    + ["Centre-Back"] * 5
    + ["Fullback"] * 5
    + ["Midfielder"] * 8
    + ["Winger"] * 5
    + ["Striker"] * 5
)
assert len(SQUAD_POSITIONS) == ATHLETE_COUNT

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

# Non-hamstring injury variety, cycled across the "other returned" and
# "still injured" athletes. (type, body_part, mechanism); a "{side}"
# placeholder in body_part gets filled with left/right alternating by
# athlete index, for the limb-specific ones.
INJURY_CATALOG = [
    ("ankle sprain", "{side} ankle", "awkward landing during small-sided game"),
    ("groin strain", "{side} adductor longus", "change-of-direction sprint"),
    ("calf strain", "{side} gastrocnemius", "explosive sprint during training"),
    ("quad strain", "{side} rectus femoris", "kicking motion during a match"),
    ("knee sprain", "{side} medial collateral ligament", "twisting tackle"),
    ("shoulder sprain", "{side} acromioclavicular joint", "fall on outstretched arm"),
    ("hip flexor strain", "{side} iliopsoas", "sprint acceleration"),
    ("achilles tendinopathy", "{side} achilles tendon", "repeated high-speed running load"),
]


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


def week_date(week_idx: int, weekday_offset: int) -> date:
    return SEASON_START + timedelta(weeks=week_idx, days=weekday_offset)


def make_athletes(np_rng: np.random.Generator, faker: Faker) -> list[dict]:
    athletes = []
    for i, position in enumerate(SQUAD_POSITIONS):
        athlete_id = f"athlete-{i + 1}"
        athletes.append(
            {
                "id": athlete_id,
                "name": faker.name(),
                "position": position,
                "age": int(np_rng.integers(19, 34)),
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


def _spike_windows(spike_specs: list[dict]) -> dict[str, list[tuple[date, date]]]:
    """athlete_id -> list of (start, end) date ranges to spike. Each spec
    is either a real injury lead-in (has injury_id) or a standalone
    "at risk but not yet injured" echo (injury_id is None) -- both spike
    the underlying metric/wellness values identically; only the former
    also gets PRECEDED ground-truth bookkeeping (see make_metrics_and_wellness)."""
    windows: dict[str, list[tuple[date, date]]] = {}
    for spec in spike_specs:
        windows.setdefault(spec["athlete_id"], []).append((spec["window_start"], spec["window_end"]))
    return windows


def make_metrics_and_wellness(
    np_rng: np.random.Generator,
    athletes: list[dict],
    sessions: list[dict],
    spike_specs: list[dict],
) -> tuple[list[dict], list[dict], dict[str, list[str]]]:
    """spike_specs: [{"athlete_id", "window_start", "window_end", "injury_id" (or None)}, ...]

    Returns (session_metrics, wellness_entries, spiked_metric_ids_by_injury) --
    spiked_metric_ids_by_injury maps injury_id -> the SessionMetric ids
    generated inside that injury's lead-up window (only for specs that
    have a real injury_id), the ground truth pattern_engine/'s own
    PRECEDED computation is checked against in tests, since neither reads
    the other.
    """
    spike_windows = _spike_windows(spike_specs)
    spec_by_window_key = {(spec["athlete_id"], spec["window_start"]): spec for spec in spike_specs}

    metrics: list[dict] = []
    spiked_ids: dict[str, list[str]] = {
        spec["injury_id"]: [] for spec in spike_specs if spec["injury_id"] is not None
    }

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
                spec = spec_by_window_key[(athlete["id"], in_spike_window[0])]
                if spec["injury_id"] is not None:
                    spiked_ids[spec["injury_id"]].append(metric_id)

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


def _side(i: int) -> str:
    return "right" if i % 2 == 0 else "left"


def make_injuries_and_treatment_chains(rng: random.Random, athletes: list[dict]) -> dict:
    """Defines every seed injury and its treatment/rehab/outcome chain,
    across the three scenario groups described at the top of this module.
    Returns all the pieces `seed_data.py` needs, plus `spike_specs`
    describing which athletes/windows `make_metrics_and_wellness` should
    spike load/wellness for (real lead-ins and the injury-free echo cohort
    alike)."""
    physios = [
        {"id": "physio-1", "name": "Dr. Amara Osei"},
        {"id": "physio-2", "name": "Dr. Liam Fitzgerald"},
        {"id": "physio-3", "name": "Dr. Priya Chandran"},
    ]

    injuries: list[dict] = []
    spike_specs: list[dict] = []

    treatments: list[dict] = []
    rehab_sessions: list[dict] = []
    outcomes: list[dict] = []
    edges_administered: list[dict] = []
    edges_targets: list[dict] = []
    edges_followed_by: list[dict] = []
    edges_produced_outcome: list[dict] = []

    def add_injury(athlete_idx: int, injury_type: str, body_part: str, mechanism: str, week: int, weekday: int, severity: str) -> dict:
        injury = {
            "id": f"injury-athlete{athlete_idx + 1}-{injury_type.split()[0]}",
            "athlete_id": f"athlete-{athlete_idx + 1}",
            "type": injury_type,
            "body_part": body_part,
            "date": week_date(week, weekday).isoformat(),
            "severity": severity,
            "mechanism": mechanism,
        }
        injuries.append(injury)
        return injury

    def add_lead_in(athlete_idx: int, injury: dict, lookback_days: int) -> None:
        injury_date = date.fromisoformat(injury["date"])
        spike_specs.append(
            {
                "athlete_id": f"athlete-{athlete_idx + 1}",
                "window_start": injury_date - timedelta(days=lookback_days),
                "window_end": injury_date - timedelta(days=1),
                "injury_id": injury["id"],
            }
        )

    def add_treatment_chain(
        injury: dict,
        physio_id: str,
        n_rehab_sessions: int,
        outcome_result: str | None,
        notes: str,
    ) -> None:
        """A treatment plus a *series* of rehab sessions -- for a resolved
        case, the series ends in an Outcome (attached to the last session
        only, per CLAUDE.md's schema: one Outcome per chain). For a still-
        ongoing case, outcome_result is None and the series just stops at
        however many sessions have happened so far -- no Outcome node at
        all, which is exactly what "still in rehab, not resolved yet"
        means in this graph."""
        injury_id = injury["id"]
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

        protocol = (
            "graduated loading — eccentric hamstring/adductor program"
            if "hamstring" in injury["type"] or "groin" in injury["type"]
            else "graduated loading protocol"
        )

        last_rehab_id = None
        last_session_date = treatment_date
        for session_idx in range(n_rehab_sessions):
            last_session_date = last_session_date + timedelta(days=int(rng.randint(4, 7)))
            rehab_id = _new_id("rehab")
            days_gap = (last_session_date - treatment_date).days
            progress = (session_idx + 1) / n_rehab_sessions  # 0 < progress <= 1, increasing load across the series
            sets = 3
            reps = 6 + round(4 * progress)
            pct_1rm = round(40 + 40 * progress)
            rehab_sessions.append(
                {
                    "id": rehab_id,
                    "treatment_id": treatment_id,
                    "date": last_session_date.isoformat(),
                    "protocol": protocol,
                    "load_prescribed": f"{pct_1rm}% 1RM, {sets}x{reps}",
                    "rpe_reported": round(3.0 + 4.0 * progress + rng.uniform(-0.4, 0.4), 1),
                    "completed": True,
                }
            )
            edges_followed_by.append({"treatment_id": treatment_id, "rehab_id": rehab_id, "days_gap": days_gap})
            last_rehab_id = rehab_id

        if outcome_result is not None:
            outcome_id = _new_id("outcome")
            outcome_date = last_session_date + timedelta(days=14 if outcome_result == "clean_return" else 9)
            outcomes.append(
                {
                    "id": outcome_id,
                    "rehab_session_id": last_rehab_id,
                    "result": outcome_result,
                    "date": outcome_date.isoformat(),
                }
            )
            edges_produced_outcome.append({"rehab_id": last_rehab_id, "outcome_id": outcome_id})

    # --- Scenario group 1: the hamstring cluster (athletes 1-5, idx 0-4) ---
    # Same injury type, same mechanism, same engineered load-spike +
    # wellness-dip lead-in -- a real cross-athlete cluster for
    # SIMILAR_PATTERN_TO to find, spanning every outcome this graph can
    # represent: re-aggravation, clean return (x3), and still-ongoing.
    hamstring_weeks = [14, 18, 22, 27, 34]
    hamstring_outcomes = ["re_aggravation", "clean_return", "clean_return", "clean_return", None]
    hamstring_rehab_counts = [4, 3, 4, 3, 5]
    hamstring_notes = [
        "Return-to-play criteria met on strength testing but sprint mechanics not "
        "reassessed before full training resumed.",
        "Full graduated return-to-sprint protocol completed before training resumed.",
        "Eccentric strength restored to within 5% of contralateral limb before clearance.",
        "Graduated return-to-sprint protocol completed; no recurrence at 4-week follow-up.",
        "Early-stage loading progressing on schedule; sprint mechanics reassessment "
        "planned before any return-to-sprint work begins.",
    ]
    for idx, (week, outcome, n_sessions, notes) in enumerate(
        zip(hamstring_weeks, hamstring_outcomes, hamstring_rehab_counts, hamstring_notes)
    ):
        injury = add_injury(
            idx,
            "hamstring strain",
            f"{_side(idx)} biceps femoris",
            "sprint deceleration during match",
            week,
            5,
            "moderate",
        )
        add_lead_in(idx, injury, lookback_days=8)
        physio_id = physios[idx % len(physios)]["id"]
        add_treatment_chain(injury, physio_id, n_sessions, outcome, notes)

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
        {
            "id": _new_id("note"),
            "injury_id": "injury-athlete5-hamstring",
            "text": "Third squad case this season with the same lead-in signature. Squad-wide "
            "load review requested for the winger/fullback rotation group.",
            "body_part": "hamstring",
            "severity": "moderate",
            "assessment": "grade 2 strain, early-stage rehab",
        },
    ]

    # --- Scenario group 2: 8 more "injured and returned" athletes
    # (idx 5-12), varied injury types, no engineered lead-in -- an
    # ordinary, unremarkable-in-hindsight injury, same as the non-
    # hamstring injuries in earlier versions of this dataset. ---
    other_returned_weeks = [10, 13, 16, 19, 24, 29, 31, 36]
    other_returned_outcomes = [
        "clean_return", "clean_return", "re_aggravation", "clean_return",
        "clean_return", "clean_return", "re_aggravation", "clean_return",
    ]
    for offset, week in enumerate(other_returned_weeks):
        idx = 5 + offset
        injury_type, body_part_tpl, mechanism = INJURY_CATALOG[offset % len(INJURY_CATALOG)]
        injury = add_injury(
            idx, injury_type, body_part_tpl.format(side=_side(idx)), mechanism, week, 2, "minor" if offset % 3 else "moderate"
        )
        outcome = other_returned_outcomes[offset]
        notes = (
            "Return-to-play criteria met on strength/movement testing before clearance."
            if outcome == "clean_return"
            else "Cleared on strength testing but symptoms recurred within the first full "
            "training week back."
        )
        physio_id = physios[idx % len(physios)]["id"]
        add_treatment_chain(injury, physio_id, n_rehab_sessions=int(rng.choice([3, 4])), outcome_result=outcome, notes=notes)

    # --- Scenario group 3: 5 more "still injured, ongoing rehab" athletes
    # (idx 13-17), onset late enough in the season that a several-session
    # program lands right up near the most recent generated data -- reads
    # as "in progress right now," not a stale, abandoned record.
    #
    # Staggered at different points in the treatment pipeline, not all
    # identically "mid-program" -- this is also what keeps GET
    # /injuries/open, /treatments/open and /rehab-sessions/open (the
    # dropdowns behind the README's "log a treatment" walkthrough)
    # non-empty: idx13 is freshly sustained and not yet seen by a physio at
    # all, idx14 has been assessed but rehab hasn't started, idx15-17 are
    # at increasing points into an active program. ---
    still_injured = [
        # (week, n_rehab_sessions or None for "no treatment logged yet")
        (38, None),  # freshly sustained, awaiting assessment
        (30, 0),  # assessed, rehab not started yet
        (31, 1),  # just begun
        (32, 3),  # early-mid program
        (33, 5),  # well into the program
    ]
    for offset, (week, n_sessions) in enumerate(still_injured):
        idx = 13 + offset
        injury_type, body_part_tpl, mechanism = INJURY_CATALOG[offset % len(INJURY_CATALOG)]
        injury = add_injury(idx, injury_type, body_part_tpl.format(side=_side(idx)), mechanism, week, 0, "moderate")
        if n_sessions is None:
            continue  # not yet treated -- no Treatment node at all
        physio_id = physios[idx % len(physios)]["id"]
        add_treatment_chain(
            injury,
            physio_id,
            n_rehab_sessions=n_sessions,
            outcome_result=None,
            notes="Graduated loading in progress; next reassessment scheduled before any "
            "return-to-sprint work begins.",
        )

    # --- Scenario group 4: injury-free (idx 18-29). Five of these (18, 20,
    # 22, 24, 26) get the same load-spike + wellness-dip signature as the
    # hamstring cluster in the final ~12 days of the season, with no
    # injury following -- "currently fine, but showing the same pattern
    # that led to a hamstring strain elsewhere in the squad." This is what
    # the flagging agent's default (no --as-of override) run is meant to
    # catch: a real echo landing inside every athlete's own most-recent
    # rolling window, not a fixed calendar date rewound into the past. ---
    season_days = SEASON_WEEKS * 7
    echo_window_start = SEASON_START + timedelta(days=season_days - 12)
    echo_window_end = SEASON_START + timedelta(days=season_days - 1)
    for idx in (18, 20, 22, 24, 26):
        spike_specs.append(
            {
                "athlete_id": f"athlete-{idx + 1}",
                "window_start": echo_window_start,
                "window_end": echo_window_end,
                "injury_id": None,
            }
        )

    edges_has_note = [{"injury_id": n["injury_id"], "note_id": n["id"]} for n in clinical_notes]

    return {
        "physios": physios,
        "injuries": injuries,
        "spike_specs": spike_specs,
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

    athletes = make_athletes(np_rng, faker)
    sessions = make_sessions()

    injury_data = make_injuries_and_treatment_chains(rng, athletes)

    session_metrics, wellness_entries, spiked_metric_ids = make_metrics_and_wellness(
        np_rng, athletes, sessions, injury_data["spike_specs"]
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
