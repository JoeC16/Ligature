"""Step 4: (question, cypher, results) -> plain-language answer.

The model is only ever shown the exact rows the query returned — never
asked to answer from its own knowledge — which is what makes CLAUDE.md's
"never infers or invents a correlation itself" an enforced property of
this pipeline rather than just a prompt instruction.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

MODEL = "claude-opus-5"


class Answer(BaseModel):
    summary: str = Field(description="Plain-language answer based only on the given query results.")


def explain(client, question: str, cypher: str, rows: list[dict]) -> Answer:
    prompt = (
        f"Question: {question}\n\n"
        f"Cypher query that was run against the graph:\n{cypher}\n\n"
        f"Exact query results (JSON):\n{json.dumps(rows, default=str)}\n\n"
        "Summarize what these results show, in plain language, for a physio "
        "who will verify it against the graph directly. State only what the "
        "results actually show above — never add outside facts or your own "
        "medical knowledge. If the results are empty, say so plainly rather "
        "than guessing why."
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        output_format=Answer,
    )
    return response.parsed_output
