// Ligature graph schema — uniqueness constraints + supporting indexes.
// One constraint per node type from CLAUDE.md's schema, keyed on `id`.
// Idempotent: safe to run on every seed.
//
// `Physio` and `Outcome` aren't listed under CLAUDE.md's "Node types"
// section, but both appear as endpoints in the "Key edges" section
// (Physio-ADMINISTERED->Treatment, RehabSession-PRODUCED->Outcome), so
// minimal node types are declared here too.

CREATE CONSTRAINT athlete_id IF NOT EXISTS FOR (n:Athlete) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT session_id IF NOT EXISTS FOR (n:Session) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT session_metric_id IF NOT EXISTS FOR (n:SessionMetric) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT wellness_entry_id IF NOT EXISTS FOR (n:WellnessEntry) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT injury_id IF NOT EXISTS FOR (n:Injury) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT treatment_id IF NOT EXISTS FOR (n:Treatment) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT rehab_session_id IF NOT EXISTS FOR (n:RehabSession) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT clinical_note_id IF NOT EXISTS FOR (n:ClinicalNote) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT cluster_id IF NOT EXISTS FOR (n:Cluster) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT flag_id IF NOT EXISTS FOR (n:Flag) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT physio_id IF NOT EXISTS FOR (n:Physio) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT outcome_id IF NOT EXISTS FOR (n:Outcome) REQUIRE n.id IS UNIQUE;

// Range indexes for the time-based lookups the pattern engine and NL
// query layer will do most often (rolling windows, "since date X").
CREATE INDEX session_date IF NOT EXISTS FOR (n:Session) ON (n.date);
CREATE INDEX wellness_entry_date IF NOT EXISTS FOR (n:WellnessEntry) ON (n.date);
CREATE INDEX injury_date IF NOT EXISTS FOR (n:Injury) ON (n.date);
CREATE INDEX treatment_date IF NOT EXISTS FOR (n:Treatment) ON (n.date);
