#!/usr/bin/env python3
"""Validate Pro-One schemas, sample records, references, and repository invariants."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
# Keep direct script execution portable, including outside the repository cwd.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.corpus import passage_relationship_errors

SCHEMA_DIR = ROOT / "schemas"
DATA_DIR = ROOT / "data"
PROJECT_OWNED_DIRECTORIES = (
    ROOT / ".github",
    ROOT / "data",
    ROOT / "docs",
    ROOT / "schemas",
    ROOT / "scripts",
    ROOT / "tests",
)
EXCLUDED_DIRECTORY_NAMES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "site-packages",
    "vendor",
    "venv",
}

DATA_SCHEMAS = {
    "source-passages.json": ("source_passage", "source-passage.schema.json"),
    "sample-evaluation-fixtures.json": ("evaluation_fixture", "evaluation-fixture.schema.json"),
    "sample-intakes.json": ("intake", "intake.schema.json"),
    "sample-legal-documents.json": ("legal_document", "legal-document.schema.json"),
    "sample-legal-rules.json": ("legal_rule", "legal-rule.schema.json"),
    "sample-process-steps.json": ("process_step", "process-step.schema.json"),
    "sample-responses.json": ("response", "response.schema.json"),
    "sample-risks.json": ("risk", "risk.schema.json"),
    "sample-sources.json": ("source", "source.schema.json"),
    "sample-workflows.json": ("workflow", "workflow.schema.json"),
}

ReferenceRole = Literal["supporting", "association", "test_or_negative"]


@dataclass(frozen=True)
class ReferenceSpec:
    target_kind: str
    role: ReferenceRole = "supporting"


@dataclass(frozen=True)
class DependencyEligibility:
    maturity_statuses: frozenset[str]
    review_statuses: frozenset[str]
    description: str


REFERENCE_FIELDS = {
    "source_id": ReferenceSpec("source"),
    "allowed_source_ids": ReferenceSpec("source"),
    "deadline_source_ids": ReferenceSpec("source"),
    "depends_on": ReferenceSpec("process_step"),
    "document_ids": ReferenceSpec("legal_document"),
    "evaluation_fixture_ids": ReferenceSpec("evaluation_fixture"),
    "excluded_document_ids": ReferenceSpec("legal_document", "test_or_negative"),
    "excluded_process_step_ids": ReferenceSpec("process_step", "test_or_negative"),
    "excluded_workflow_ids": ReferenceSpec("workflow", "test_or_negative"),
    "expected_risk_ids": ReferenceSpec("risk"),
    "intake_ids": ReferenceSpec("intake"),
    "legal_document_ids": ReferenceSpec("legal_document"),
    "legal_rule_ids": ReferenceSpec("legal_rule"),
    "next_step_ids": ReferenceSpec("process_step"),
    "optional_rule_ids": ReferenceSpec("legal_rule"),
    "optional_source_ids": ReferenceSpec("source"),
    "process_step_ids": ReferenceSpec("process_step"),
    "prohibited_source_ids": ReferenceSpec("source", "test_or_negative"),
    "required_evaluation_fixture_ids": ReferenceSpec("evaluation_fixture"),
    "required_rule_ids": ReferenceSpec("legal_rule"),
    "required_source_ids": ReferenceSpec("source"),
    "response_ids": ReferenceSpec("response"),
    "risk_ids": ReferenceSpec("risk"),
    "source_ids": ReferenceSpec("source"),
    "superseded_by_source_id": ReferenceSpec("source", "test_or_negative"),
    "supported_document_ids": ReferenceSpec("legal_document"),
    "supported_process_step_ids": ReferenceSpec("process_step"),
    "supported_workflow_ids": ReferenceSpec("workflow"),
    "workflow_ids": ReferenceSpec("workflow"),
}

# Reference roles are resolved by record domain and full object path. Backlinks,
# applicability, and test-target relationships must resolve, but they do not
# make the referenced record a prerequisite for lifecycle promotion.
REFERENCE_PATH_ROLES: dict[
    tuple[str, tuple[str, ...]], ReferenceRole
] = {
    ("source_passage", ("workflow_ids",)): "association",
    ("source_passage", ("legal_rule_ids",)): "association",
    ("source_passage", ("process_step_ids",)): "association",
    ("source", ("workflow_fit", "workflow_ids")): "association",
    ("process_step", ("workflow_ids",)): "association",
    ("process_step", ("sequence", "next_step_ids")): "association",
    ("legal_document", ("workflow_ids",)): "association",
    ("legal_document", ("process_step_ids",)): "association",
    ("intake", ("workflow_ids",)): "association",
    ("intake", ("process_step_ids",)): "association",
    ("intake", ("document_ids",)): "association",
    ("legal_rule", ("workflow_fit", "supported_workflow_ids")): "association",
    ("legal_rule", ("process_step_fit", "supported_process_step_ids")): "association",
    ("legal_rule", ("document_fit", "supported_document_ids")): "association",
    **{
        ("risk", ("related_records", field_name)): "association"
        for field_name in (
            "source_ids",
            "workflow_ids",
            "process_step_ids",
            "legal_document_ids",
            "intake_ids",
            "legal_rule_ids",
        )
    },
    **{
        ("response", ("related_records", field_name)): "association"
        for field_name in (
            "workflow_ids",
            "process_step_ids",
            "legal_document_ids",
            "intake_ids",
            "risk_ids",
            "evaluation_fixture_ids",
        )
    },
    **{
        ("evaluation_fixture", ("related_records", field_name)): "test_or_negative"
        for field_name in (
            "source_ids",
            "workflow_ids",
            "process_step_ids",
            "legal_document_ids",
            "intake_ids",
            "legal_rule_ids",
            "risk_ids",
            "response_ids",
        )
    },
    ("evaluation_fixture", ("source_context", "allowed_source_ids")): "test_or_negative",
    ("evaluation_fixture", ("risk", "expected_risk_ids")): "test_or_negative",
}

SUPPORTED_DEPENDENCY_ELIGIBILITY = {
    "source_passage": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "supported and approved source passage"
    ),
    "source": DependencyEligibility(
        frozenset({"supported"}),
        frozenset({"approved"}),
        "supported and approved source satisfying source-schema eligibility",
    ),
    "workflow": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "publicly supported workflow"
    ),
    "process_step": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "publicly supported process step"
    ),
    "legal_document": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "publicly supported legal document"
    ),
    "intake": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "publicly supported intake"
    ),
    "legal_rule": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "publicly supported legal rule"
    ),
    "risk": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "publicly supported risk control"
    ),
    "response": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "publicly supported response pattern"
    ),
    "evaluation_fixture": DependencyEligibility(
        frozenset({"supported"}), frozenset({"approved"}), "supported evaluation fixture"
    ),
}

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
MOJIBAKE_MARKERS = ("\ufffd", "\u00e2\u20ac", "\u00c3", "\u00c2")


class ValidationReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.counts: defaultdict[str, int] = defaultdict(int)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def checked(self, category: str, amount: int = 1) -> None:
        self.counts[category] += amount


def load_json(path: Path, report: ValidationReport) -> Any | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.error(f"{path.relative_to(ROOT)}: invalid JSON/UTF-8: {exc}")
        return None
    report.checked("JSON files")
    return value


def json_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def is_project_owned(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return not any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts)


def iter_project_files(suffixes: set[str]) -> Iterator[Path]:
    """Yield only repository-owned files, independent of local environments."""
    for path in sorted(ROOT.iterdir()):
        if path.is_file() and path.suffix.lower() in suffixes:
            yield path
    for directory in PROJECT_OWNED_DIRECTORIES:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in suffixes and is_project_owned(path):
                yield path


def discover_schema_reference_fields(value: Any) -> set[str]:
    fields: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            fields.update(
                key
                for key in properties
                if key.endswith(("_id", "_ids")) or key == "depends_on"
            )
        for child in value.values():
            fields.update(discover_schema_reference_fields(child))
    elif isinstance(value, list):
        for child in value:
            fields.update(discover_schema_reference_fields(child))
    return fields


def reference_spec_for(
    record_kind: str, field_path: tuple[Any, ...], field_name: str
) -> ReferenceSpec | None:
    spec = REFERENCE_FIELDS.get(field_name)
    if spec is None:
        return None
    string_path = tuple(str(part) for part in field_path)
    role = REFERENCE_PATH_ROLES.get((record_kind, string_path), spec.role)
    return ReferenceSpec(spec.target_kind, role)


def walk_references(
    value: Any, record_kind: str, path: tuple[Any, ...] = ()
):
    if isinstance(value, dict):
        for key, child in value.items():
            current = path + (key,)
            spec = reference_spec_for(record_kind, current, key)
            if spec:
                if isinstance(child, list):
                    for index, record_id in enumerate(child):
                        if isinstance(record_id, str):
                            yield spec, record_id, current + (index,)
                elif isinstance(child, str):
                    yield spec, child, current
            yield from walk_references(child, record_kind, current)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_references(child, record_kind, path + (index,))


def supporting_dependency_edges(
    records_by_kind: dict[str, dict[str, dict[str, Any]]],
) -> set[tuple[tuple[str, str], tuple[str, str]]]:
    """Return existing support-gating edges for graph regression checks."""
    edges: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for kind, records in records_by_kind.items():
        for record_id, record in records.items():
            for spec, target_id, _path in walk_references(record, kind):
                if (
                    spec.role == "supporting"
                    and target_id in records_by_kind.get(spec.target_kind, {})
                ):
                    edges.add(((kind, record_id), (spec.target_kind, target_id)))
    return edges


def validate_markdown(report: ValidationReport) -> None:
    link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    fence_pattern = re.compile(r"^\s*(`{3,}|~{3,})")

    for path in iter_project_files({".md"}):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            report.error(f"{path.relative_to(ROOT)}: invalid UTF-8 Markdown: {exc}")
            continue

        report.checked("Markdown files")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                report.error(f"{path.relative_to(ROOT)}: possible encoding corruption marker {marker!r}")

        open_fence: tuple[str, int] | None = None
        for number, line in enumerate(text.splitlines(), start=1):
            match = fence_pattern.match(line)
            if not match:
                continue
            marker = match.group(1)[0]
            if open_fence is None:
                open_fence = (marker, number)
            elif open_fence[0] == marker:
                open_fence = None
        if open_fence:
            report.error(
                f"{path.relative_to(ROOT)}:{open_fence[1]}: unclosed {open_fence[0] * 3} fence"
            )

        for match in link_pattern.finditer(text):
            destination = match.group(1).strip().strip("<>")
            destination = destination.split(maxsplit=1)[0]
            if not destination or destination.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local_path = destination.split("#", 1)[0]
            if local_path and not (path.parent / local_path).resolve().exists():
                line = text.count("\n", 0, match.start()) + 1
                report.error(
                    f"{path.relative_to(ROOT)}:{line}: broken relative link {destination!r}"
                )


def review_status(record: dict[str, Any]) -> str | None:
    review = record.get("review")
    return review.get("status") if isinstance(review, dict) else None


def maturity_status(record: dict[str, Any]) -> str | None:
    return record.get("status")


def is_supported(record: dict[str, Any]) -> bool:
    return maturity_status(record) == "supported"


def required_supported_review_scopes(
    kind: str, record: dict[str, Any]
) -> frozenset[str]:
    """Return the domain-specific review gate for public supported use."""
    required = set(SUPPORTED_REVIEW_SCOPES[kind])
    if kind == "workflow" and record.get("intake", {}).get("collects_sensitive_data"):
        required.add("privacy")
    return frozenset(required)


def validate_supported_review_scopes(
    kind: str,
    record: dict[str, Any],
    location: str,
    report: ValidationReport,
) -> None:
    if not is_supported(record):
        return
    review = record.get("review", {})
    actual = set(review.get("review_scope", [])) if isinstance(review, dict) else set()
    missing = required_supported_review_scopes(kind, record) - actual
    if missing:
        report.error(
            f"{location}: supported {kind} is missing required review scopes: "
            + ", ".join(sorted(missing))
        )


def validate_review_provenance(
    filename: str, record: dict[str, Any], report: ValidationReport
) -> None:
    review = record.get("review")
    if not isinstance(review, dict):
        return
    if review.get("status") in {"reviewed", "approved"}:
        required = (
            "reviewed_by",
            "reviewer_role",
            "review_scope",
            "reviewed_on",
            "reviewed_record_version",
        )
        missing = [field for field in required if not review.get(field)]
        if missing:
            report.error(
                f"{filename}:{record.get('id')}: reviewed/approved record lacks review provenance: "
                + ", ".join(missing)
            )
        if review.get("reviewed_record_version") != record.get("record_version"):
            report.error(
                f"{filename}:{record.get('id')}: review version does not match record_version"
            )


def validate_cross_record_references(
    records_by_kind: dict[str, dict[str, dict[str, Any]]],
    record_locations: dict[tuple[str, str], str],
    report: ValidationReport,
) -> None:
    for kind, records in records_by_kind.items():
        for record_id, record in records.items():
            location = record_locations[(kind, record_id)]
            for spec, target_id, path in walk_references(record, kind):
                target_kind = spec.target_kind
                target = records_by_kind.get(target_kind, {}).get(target_id)
                if target is None:
                    report.error(
                        f"{location}:{json_path(path)}: unknown {target_kind} id {target_id!r}"
                    )
                    continue
                report.checked("Cross-record references")

                if is_supported(record) and spec.role == "supporting":
                    eligibility = SUPPORTED_DEPENDENCY_ELIGIBILITY[target_kind]
                    target_maturity = maturity_status(target)
                    target_review = review_status(target)
                    if (
                        target_maturity not in eligibility.maturity_statuses
                        or target_review not in eligibility.review_statuses
                    ):
                        report.error(
                            f"{location}: supported record has ineligible supporting "
                            f"{target_kind} {target_id!r}; expected {eligibility.description}, "
                            f"got maturity={target_maturity!r}, review={target_review!r}"
                        )

            if is_supported(record) and review_status(record) != "approved":
                report.error(f"{location}: supported record must have approved review status")
            validate_supported_review_scopes(kind, record, location, report)

            if kind == "legal_rule" and is_supported(record):
                statement = record.get("rule_statement", {})
                support = record.get("source_support", {})
                user_support = record.get("user_support", {})
                if statement.get("user_facing_allowed"):
                    if not support.get("required_source_ids"):
                        report.error(f"{location}: supported user-facing rule requires a source")
                    if not user_support.get("requires_citation"):
                        report.error(f"{location}: supported user-facing rule must require citation")

            if kind == "response" and is_supported(record):
                source_use = record.get("source_use", {})
                if source_use.get("source_required"):
                    allowed = set(source_use.get("allowed_source_review_statuses", []))
                    if allowed - {"reviewed", "approved"}:
                        report.error(
                            f"{location}: supported source-backed response allows non-reviewed source states"
                        )
                    high_risk = {"high", "extreme"}.intersection(
                        record.get("risk", {}).get("risk_levels_supported", [])
                    )
                    if high_risk and allowed != {"approved"}:
                        report.error(
                            f"{location}: high-risk supported response must allow only approved sources"
                        )


def main() -> int:
    report = ValidationReport()

    parsed_json: dict[Path, Any] = {}
    for path in iter_project_files({".json"}):
        value = load_json(path, report)
        if value is not None:
            parsed_json[path] = value

    schemas: dict[str, dict[str, Any]] = {}
    registry = Registry()
    discovered_reference_fields: set[str] = set()
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        schema = parsed_json.get(path)
        if not isinstance(schema, dict):
            continue
        try:
            Draft202012Validator.check_schema(schema)
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        except Exception as exc:  # check_schema raises several detailed exception types
            report.error(f"{path.relative_to(ROOT)}: invalid Draft 2020-12 schema: {exc}")
            continue
        schemas[path.name] = schema
        discovered_reference_fields.update(discover_schema_reference_fields(schema))
        report.checked("JSON Schemas")

    missing_reference_specs = discovered_reference_fields - REFERENCE_FIELDS.keys()
    unused_reference_specs = REFERENCE_FIELDS.keys() - discovered_reference_fields
    if missing_reference_specs:
        report.error(
            "Typed reference fields missing validator definitions: "
            + ", ".join(sorted(missing_reference_specs))
        )
    if unused_reference_specs:
        report.error(
            "Validator reference definitions not present in schemas: "
            + ", ".join(sorted(unused_reference_specs))
        )
    report.checked("Typed reference fields", len(discovered_reference_fields))

    record_kinds = {kind for kind, _ in DATA_SCHEMAS.values()}
    if set(SUPPORTED_DEPENDENCY_ELIGIBILITY) != record_kinds:
        report.error("Supported dependency eligibility is not defined for every record kind")
    if set(SUPPORTED_REVIEW_SCOPES) != record_kinds:
        report.error("Supported review scopes are not defined for every record kind")

    records_by_kind: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    record_locations: dict[tuple[str, str], str] = {}

    for filename, (kind, schema_name) in DATA_SCHEMAS.items():
        path = DATA_DIR / filename
        records = parsed_json.get(path)
        schema = schemas.get(schema_name)
        if not isinstance(records, list):
            report.error(f"data/{filename}: expected a JSON array")
            continue
        if schema is None:
            report.error(f"data/{filename}: schema {schema_name} was not available")
            continue

        validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                report.error(f"data/{filename}[{index}]: expected an object")
                continue
            record_id = record.get("id")
            if not isinstance(record_id, str):
                report.error(f"data/{filename}[{index}]: missing string id")
                continue
            if record_id in records_by_kind[kind]:
                report.error(f"data/{filename}: duplicate {kind} id {record_id!r}")
            records_by_kind[kind][record_id] = record
            record_locations[(kind, record_id)] = f"data/{filename}:{record_id}"

            errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
            for error in errors:
                report.error(
                    f"data/{filename}:{record_id}:{json_path(error.path)}: {error.message}"
                )
            report.checked("Sample records")
            validate_review_provenance(filename, record, report)

    validate_cross_record_references(records_by_kind, record_locations, report)

    # Share corpus semantics with runtime startup, after schema/reference checks.
    if not report.errors:
        for passage in records_by_kind["source_passage"].values():
            for error in passage_relationship_errors(
                passage,
                sources=records_by_kind["source"],
                workflows=records_by_kind["workflow"],
                legal_rules=records_by_kind["legal_rule"],
                process_steps=records_by_kind["process_step"],
            ):
                report.error(f"source passage {passage['id']}: {error}")

    validate_markdown(report)

    stale_patterns = {
        "old repository identity": re.compile("zeit" + "cow" + re.escape("/pro-one"), re.IGNORECASE),
        "PR-history wording": re.compile(r"\bThis PR " + "introduces" + r"\b", re.IGNORECASE),
    }
    for path in iter_project_files({".md", ".json", ".yml", ".yaml", ".py"}):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            report.error(f"{path.relative_to(ROOT)}: invalid UTF-8 text: {exc}")
            continue
        for label, pattern in stale_patterns.items():
            if pattern.search(text):
                report.error(f"{path.relative_to(ROOT)}: contains stale {label}")

    if report.errors:
        print(f"Repository validation failed with {len(report.errors)} error(s):", file=sys.stderr)
        for error in report.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    summary = ", ".join(f"{name}: {count}" for name, count in sorted(report.counts.items()))
    print(f"Repository validation passed ({summary}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
