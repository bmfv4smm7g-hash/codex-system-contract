"""Regression coverage for the Codex turn-metadata representation boundary."""

from __future__ import annotations

from test_codex_wire_audit_v10 import C
from test_codex_wire_audit_v10 import MachineContractTests


MCP_PROJECTION_KEYS = {
    "model",
    "codex_version",
    "reasoning_effort",
    "user_input_requested_during_turn",
    "node_repl_disabled",
}


def test_mcp_projection_keys_are_not_fixed_codex_turn_payload_fields() -> None:
    """MCP mutator keys must not be attributed to the Rust payload struct.

    Codex first serializes ``CodexTurnMetadataPayload`` and then mutates that
    JSON object for MCP ``_meta``. Responses may still carry caller-provided
    string extras with the same names through the flattened-extra channel, but
    that does not make them declared ``CodexTurnMetadataPayload`` members.
    """

    report = MachineContractTests().upgrade()
    documents = C.protocol_schema_documents(report)

    responses_schema = documents["codex-turn-metadata-full.schema.json"]
    mcp_schema = documents["codex-turn-metadata-mcp.schema.json"]

    responses_properties = set(responses_schema["properties"])
    mcp_properties = set(mcp_schema["properties"])

    assert MCP_PROJECTION_KEYS.isdisjoint(responses_properties)
    assert MCP_PROJECTION_KEYS <= mcp_properties
    assert responses_schema["additionalProperties"] == {"type": "string"}
    assert {"model", "codex_version", "node_repl_disabled"} <= set(
        mcp_schema["required"]
    )
