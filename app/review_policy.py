"""Existing supported-record review scopes shared by validation and release gates."""

SUPPORTED_REVIEW_SCOPES = {
    "source_passage": frozenset({
        "schema", "source_authority", "source_freshness", "jurisdiction",
        "legal_information_boundary",
    }),
    "source": frozenset({"schema", "source_authority", "source_freshness", "jurisdiction"}),
    "workflow": frozenset(
        {"schema", "jurisdiction", "legal_information_boundary", "safety", "evaluation"}
    ),
    "process_step": frozenset(
        {"schema", "jurisdiction", "legal_information_boundary", "safety", "evaluation"}
    ),
    "legal_document": frozenset(
        {
            "schema",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "privacy",
            "evaluation",
        }
    ),
    "intake": frozenset(
        {
            "schema",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "privacy",
            "evaluation",
        }
    ),
    "legal_rule": frozenset(
        {
            "schema",
            "source_authority",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "evaluation",
        }
    ),
    "risk": frozenset({"schema", "safety", "evaluation"}),
    "response": frozenset(
        {
            "schema",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "privacy",
            "evaluation",
        }
    ),
    "evaluation_fixture": frozenset({"schema", "evaluation"}),
}
