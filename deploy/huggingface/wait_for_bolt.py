"""Blocks until Memgraph accepts Bolt connections, or exits non-zero after
~120s. Shared by build_seed.sh (build-time, seeding a throwaway instance)
and entrypoint.sh (runtime, the real container's instance) -- both need
the exact same "poll until the driver can connect" loop, and two copies
of it drifting out of sync is how the last version of this logic ended up
duplicated inline in a bash heredoc.
"""

from __future__ import annotations

import os
import sys
import time

from neo4j import GraphDatabase

uri = os.environ.get("GRAPH_DB_URI", "bolt://localhost:7687")
user = os.environ.get("GRAPH_DB_USER", "memgraph")
password = os.environ.get("GRAPH_DB_PASSWORD", "unused")

for attempt in range(60):
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        driver.close()
        print("Memgraph is up.")
        sys.exit(0)
    except Exception as exc:
        if attempt == 59:
            print(f"Memgraph never came up after 120s: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
