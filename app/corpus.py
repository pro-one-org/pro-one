"""Shared structural checks for curated passages; no legal approval is inferred."""

import hashlib
from typing import Any


def passage_relationship_errors(
    passage: dict[str, Any],
    *,
    sources: dict[str, dict[str, Any]],
    workflows: dict[str, dict[str, Any]],
    legal_rules: dict[str, dict[str, Any]],
    process_steps: dict[str, dict[str, Any]],
) -> list[str]:
    """Check links, source fit, exact jurisdiction scope, and excerpt integrity.

    Inputs must already conform to their domain schemas. These checks establish
    structural consistency, not that an excerpt legally supports a proposition.
    """
    errors: list[str] = []
    source = sources.get(passage["source_id"])
    if source is None:
        errors.append("unknown_source")
    expected_hash = "sha256:" + hashlib.sha256(passage["text"].encode("utf-8")).hexdigest()
    if passage["verification"]["excerpt_hash"] != expected_hash:
        errors.append("excerpt_hash_mismatch")
    if passage["verification"]["verified_on"] < passage["verification"]["retrieved_on"]:
        errors.append("verification_precedes_retrieval")

    dimensions = ("country", "state", "locality", "court", "agency")
    for workflow_id in passage["workflow_ids"]:
        workflow = workflows.get(workflow_id)
        if workflow is None:
            errors.append(f"unknown_workflow:{workflow_id}")
            continue
        if source is not None:
            if workflow_id not in source["workflow_fit"]["workflow_ids"]:
                errors.append(f"source_not_linked_to_workflow:{workflow_id}")
            for record in (source, workflow):
                if any(
                    passage["jurisdiction"].get(key) != record["jurisdiction"].get(key)
                    for key in dimensions
                ):
                    errors.append(f"jurisdiction_mismatch:{record['id']}")
        for field, records, fit_field in (
            ("legal_rule_ids", legal_rules, "source_support"),
            ("process_step_ids", process_steps, "sources"),
        ):
            for record_id in passage[field]:
                record = records.get(record_id)
                if record is None:
                    errors.append(f"unknown_{field}:{record_id}")
                    continue
                fits = (
                    record["workflow_fit"]["supported_workflow_ids"]
                    if field == "legal_rule_ids" else record["workflow_ids"]
                )
                if workflow_id not in fits:
                    errors.append(f"record_not_linked_to_workflow:{record_id}")
                if any(
                    passage["jurisdiction"].get(key) != record["jurisdiction"].get(key)
                    for key in dimensions
                ):
                    errors.append(f"jurisdiction_mismatch:{record_id}")
                support = record[fit_field]
                supported_sources = support["required_source_ids"] + support.get("optional_source_ids", [])
                if passage["source_id"] not in supported_sources:
                    errors.append(f"source_not_linked_to_record:{record_id}")
    return sorted(set(errors))
