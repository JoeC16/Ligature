"""Step 1: question -> Cypher, via Claude with a structured output schema
(never free-text parsing — see the loaded claude-api skill's guidance on
`client.messages.parse` + Pydantic `output_format`)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from schema_context import SCHEMA_DESCRIPTION

MODEL = "claude-opus-5"


class CypherTranslation(BaseModel):
    cypher: str | None = Field(
        default=None,
        description="A single read-only Cypher query that answers the question using only the given schema, or null if it can't be answered.",
    )
    refusal_reason: str | None = Field(
        default=None,
        description="If cypher is null, a brief plain-language reason why (e.g. the question needs data or a write not in this schema).",
    )


def translate(client, question: str) -> CypherTranslation:
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        system=SCHEMA_DESCRIPTION,
        messages=[{"role": "user", "content": question}],
        output_format=CypherTranslation,
    )
    return response.parsed_output
