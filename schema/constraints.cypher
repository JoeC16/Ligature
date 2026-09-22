// Ligature graph schema — uniqueness constraints + supporting indexes.
// One constraint per node type from CLAUDE.md's schema, keyed on `id`.
// Idempotent to run against a fresh database (every seed/deploy starts
// from one — see run_constraints()'s callers).
//
// `Physio` and `Outcome` aren't listed under CLAUDE.md's "Node types"
// section, but both appear as endpoints in the "Key edges" section
// (Physio-ADMINISTERED->Treatment, RehabSession-PRODUCED->Outcome), so
// minimal node types are declared here too.
//
// Memgraph DDL syntax (CREATE CONSTRAINT ... ASSERT / CREATE INDEX ON
// :Label(prop)), not Neo4j 5's FOR ... REQUIRE ... IF NOT EXISTS — this
// project runs on Memgraph everywhere now, local dev included (see
// docker-compose.yml and the main README's Setup section).

CREATE CONSTRAINT ON (n:Athlete) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:Session) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:SessionMetric) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:WellnessEntry) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:Injury) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:Treatment) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:RehabSession) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:ClinicalNote) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:Cluster) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:Flag) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:Physio) ASSERT n.id IS UNIQUE;
CREATE CONSTRAINT ON (n:Outcome) ASSERT n.id IS UNIQUE;

// Range indexes for the time-based lookups the pattern engine and NL
// query layer do most often (rolling windows, "since date X").
CREATE INDEX ON :Session(date);
CREATE INDEX ON :WellnessEntry(date);
CREATE INDEX ON :Injury(date);
CREATE INDEX ON :Treatment(date);
