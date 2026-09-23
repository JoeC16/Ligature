"""GPS/session export -> Session + SessionMetric.

One row per athlete per session is the normal shape of a GPS vendor export
(Catapult, Statsports, ...) — several rows share the same session date/type,
so Session identity is keyed on (date, type) only, letting every athlete's
row for that session MERGE onto the one Session node.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from normalize import clean_str, missing_required_columns, parse_date, parse_float, row_get, stable_id  # noqa: E402

_EMPTY_RESULT = {
    "sessions": [],
    "session_metrics": [],
    "edges": {"participated_in": [], "produced_metric": []},
    "stats": {"read": 0, "loaded": 0, "skipped": 0},
    "skipped_rows": [],
}


def import_gps(path: str | Path, roster) -> dict:
    sessions: dict[str, dict] = {}
    metrics: list[dict] = []
    participated_in: list[dict] = []
    produced_metric: list[dict] = []
    skipped: list[dict] = []
    read = 0

    # utf-8-sig, not utf-8 -- see roster.py's load_roster for why (Excel's
    # BOM otherwise breaks the first column's row_get() lookup on every row).
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Checked once against the header, not per-row: a file with no
        # athlete/date/type column would otherwise skip every single row
        # with the exact same confusing reason, reading as N different
        # problems instead of the one real one.
        missing = missing_required_columns(
            reader.fieldnames,
            [
                ("athlete name", ["Player Name", "Player", "athlete", "name"]),
                ("session date", ["Session Date", "date"]),
                ("session type", ["Session Type", "type"]),
            ],
        )
        if missing:
            found = ", ".join(reader.fieldnames or []) or "(no header row found)"
            return {
                **_EMPTY_RESULT,
                "file_error": f"Missing required column(s): {', '.join(missing)}. Found columns: {found}",
            }

        for line_no, row in enumerate(reader, start=2):
            read += 1

            date = parse_date(row_get(row, "Session Date", "date"))
            session_type = clean_str(row_get(row, "Session Type", "type"))
            player_name = row_get(row, "Player Name", "Player", "athlete", "name")
            athlete_id = roster.resolve(player_name)

            if athlete_id is None:
                reason = f"unmatched athlete '{player_name}'"
                suggestion = roster.suggest(player_name)
                if suggestion:
                    reason += f" -- closest roster match: '{suggestion}' (not applied automatically)"
                skipped.append({"line": line_no, "reason": reason})
                continue
            if date is None:
                skipped.append({"line": line_no, "reason": "unparseable or missing session date"})
                continue
            if not session_type:
                skipped.append({"line": line_no, "reason": "missing session type"})
                continue

            session_id = stable_id("session", date, session_type)
            if session_id not in sessions:
                sessions[session_id] = {"id": session_id, "date": date, "type": session_type}

            metric_id = stable_id("metric", athlete_id, session_id)
            metrics.append(
                {
                    "id": metric_id,
                    "hsr_distance_m": parse_float(row_get(row, "HSR Distance (m)", "HSR", "hsr_distance_m")),
                    "sprint_count": parse_float(row_get(row, "Sprints", "Sprint Count", "sprint_count")),
                    "accel_decel_load": parse_float(row_get(row, "Accel/Decel Load", "accel_decel_load")),
                    "total_distance_m": parse_float(row_get(row, "Total Distance (m)", "total_distance_m")),
                }
            )
            participated_in.append({"athlete_id": athlete_id, "session_id": session_id})
            produced_metric.append({"session_id": session_id, "metric_id": metric_id})

    return {
        "sessions": list(sessions.values()),
        "session_metrics": metrics,
        "edges": {"participated_in": participated_in, "produced_metric": produced_metric},
        "stats": {"read": read, "loaded": read - len(skipped), "skipped": len(skipped)},
        "skipped_rows": skipped,
        "file_error": None,
    }
