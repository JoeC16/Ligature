// Memgraph-syntax equivalent of constraints.cypher, for the bundled free-tier
// demo deploy only (see deploy/render/README.md) — real local development
// still runs against Neo4j via docker-compose.yml + constraints.cypher,
// unchanged. Memgraph uses older-style Cypher DDL (CREATE CONSTRAINT ON
// ... ASSERT / CREATE INDEX ON :Label(prop)) rather than Neo4j 5's
// FOR ... REQUIRE ... IF NOT EXISTS syntax, so this can't be the same file.
// Selected at runtime by common/db.py's run_constraints() via the
// GRAPH_ENGINE env var, set to "memgraph" only in the deploy Dockerfile.
//
// Not a concern here that this isn't itself idempotent the way the Neo4j
// file's IF NOT EXISTS guards are: the deploy container's Memgraph instance
// is always freshly started (no persistent volume, ephemeral storage), so
// every run already starts from a blank database.

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

CREATE INDEX ON :Session(date);
CREATE INDEX ON :WellnessEntry(date);
CREATE INDEX ON :Injury(date);
CREATE INDEX ON :Treatment(date);
