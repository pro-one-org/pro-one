from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
VALIDATOR_PATH = ROOT / "scripts" / "validate_repository.py"

STANDALONE_SUPPORTED_SCHEMA_CASES = {
    "source": (
        "source.schema.json",
        "sample-sources.json",
        ("schema", "source_authority", "source_freshness", "jurisdiction"),
    ),
    "workflow": (
        "workflow.schema.json",
        "sample-workflows.json",
        (
            "schema",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "evaluation",
            "privacy",
        ),
    ),
    "process_step": (
        "process-step.schema.json",
        "sample-process-steps.json",
        ("schema", "jurisdiction", "legal_information_boundary", "safety", "evaluation"),
    ),
    "legal_document": (
        "legal-document.schema.json",
        "sample-legal-documents.json",
        (
            "schema",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "privacy",
            "evaluation",
        ),
    ),
    "intake": (
        "intake.schema.json",
        "sample-intakes.json",
        (
            "schema",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "privacy",
            "evaluation",
        ),
    ),
    "response": (
        "response.schema.json",
        "sample-responses.json",
        (
            "schema",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "privacy",
            "evaluation",
        ),
    ),
    "legal_rule": (
        "legal-rule.schema.json",
        "sample-legal-rules.json",
        (
            "schema",
            "source_authority",
            "jurisdiction",
            "legal_information_boundary",
            "safety",
            "evaluation",
        ),
    ),
    "risk": (
        "risk.schema.json",
        "sample-risks.json",
        ("schema", "safety", "evaluation"),
    ),
    "evaluation_fixture": (
        "evaluation-fixture.schema.json",
        "sample-evaluation-fixtures.json",
        ("schema", "evaluation"),
    ),
}

spec = importlib.util.spec_from_file_location("repository_validator", VALIDATOR_PATH)
assert spec and spec.loader
repository_validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = repository_validator
spec.loader.exec_module(repository_validator)


def approved_review(kind: str, record: dict | None = None) -> dict:
    record = record or {}
    return {
        "status": "approved",
        "review_scope": sorted(
            repository_validator.required_supported_review_scopes(kind, record)
        ),
    }


class StandaloneSchemaTests(unittest.TestCase):
    def validate_with_standard_cli(
        self, schema_name: str, instance: dict
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as instance_file:
            json.dump(instance, instance_file)
            instance_path = Path(instance_file.name)
        try:
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "jsonschema",
                    str(SCHEMA_DIR / schema_name),
                    "--base-uri",
                    SCHEMA_DIR.as_uri() + "/",
                    "--instance",
                    str(instance_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            instance_path.unlink(missing_ok=True)

    def test_domain_schema_resolves_common_schema_without_custom_registry(self) -> None:
        workflow = json.loads(
            (ROOT / "data" / "sample-workflows.json").read_text(encoding="utf-8")
        )[0]
        result = self.validate_with_standard_cli("workflow.schema.json", workflow)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_supported_evaluation_fixture_requires_review_and_a_related_record(self) -> None:
        fixture = json.loads(
            (ROOT / "data" / "sample-evaluation-fixtures.json").read_text(encoding="utf-8")
        )[0]
        fixture["status"] = "supported"
        fixture["review"] = {
            "status": "approved",
            "reviewed_by": "schema-test-reviewer",
            "reviewer_role": "technical_reviewer",
            "review_scope": ["schema", "evaluation"],
            "reviewed_on": "2026-08-20",
            "reviewed_record_version": fixture["record_version"],
            "review_notes": "Synthetic test provenance; not sample-data review.",
        }

        valid_result = self.validate_with_standard_cli(
            "evaluation-fixture.schema.json", fixture
        )
        self.assertEqual(0, valid_result.returncode, valid_result.stderr)

        disconnected_fixture = copy.deepcopy(fixture)
        for field_name in disconnected_fixture["related_records"]:
            disconnected_fixture["related_records"][field_name] = []
        invalid_result = self.validate_with_standard_cli(
            "evaluation-fixture.schema.json", disconnected_fixture
        )
        self.assertNotEqual(0, invalid_result.returncode)

    def supported_schema_instance(
        self, kind: str, data_filename: str, review_scopes: tuple[str, ...]
    ) -> dict:
        instance = copy.deepcopy(
            json.loads((ROOT / "data" / data_filename).read_text(encoding="utf-8"))[0]
        )
        instance["status"] = "supported"
        instance["review"] = {
            "status": "approved",
            "reviewed_by": "schema-test-reviewer",
            "reviewer_role": "technical_reviewer",
            "review_scope": list(review_scopes),
            "reviewed_on": "2026-08-20",
            "reviewed_record_version": instance["record_version"],
            "review_notes": "Synthetic test provenance; not sample-data review.",
        }
        if "evaluation" in instance:
            instance["evaluation"]["required_evaluation_fixture_ids"] = [
                "schema-test-fixture"
            ]

        if kind == "source":
            instance["dates"]["last_verified"] = "2026-08-20"
            instance["citation"]["retrieved_at"] = "2026-08-20"
        elif kind == "intake":
            instance["workflow_ids"] = ["schema-test-workflow"]
        elif kind == "legal_rule":
            instance["source_support"]["required_source_ids"] = ["schema-test-source"]
            instance["source_support"]["source_review_required"] = True
            instance["user_support"]["requires_citation"] = True
        elif kind == "legal_document":
            instance["sources"]["required_source_ids"] = ["schema-test-source"]
            instance["sources"]["source_review_required"] = True
            instance["legal_rules"]["required_rule_ids"] = ["schema-test-rule"]
            instance["legal_rules"]["rule_review_required"] = True
        elif kind == "process_step":
            instance["sources"]["required_source_ids"] = ["schema-test-source"]
            instance["sources"]["source_review_required"] = True
        elif kind == "response":
            instance["source_use"]["source_required"] = False

        return instance

    def test_all_supported_domain_schemas_require_complete_review_scopes(self) -> None:
        for kind, (
            schema_name,
            data_filename,
            required_scopes,
        ) in STANDALONE_SUPPORTED_SCHEMA_CASES.items():
            with self.subTest(kind=kind, state="complete"):
                instance = self.supported_schema_instance(
                    kind, data_filename, required_scopes
                )
                valid_result = self.validate_with_standard_cli(schema_name, instance)
                self.assertEqual(0, valid_result.returncode, valid_result.stderr)

            for missing_scope in required_scopes:
                with self.subTest(kind=kind, missing_scope=missing_scope):
                    instance["review"]["review_scope"] = [
                        scope for scope in required_scopes if scope != missing_scope
                    ]
                    invalid_result = self.validate_with_standard_cli(
                        schema_name, instance
                    )
                    self.assertNotEqual(0, invalid_result.returncode)

    def test_supported_workflow_requires_domain_review_scopes(self) -> None:
        workflow = json.loads(
            (ROOT / "data" / "sample-workflows.json").read_text(encoding="utf-8")
        )[0]
        workflow["status"] = "supported"
        workflow["evaluation"]["required_evaluation_fixture_ids"] = ["schema-test-fixture"]
        workflow["review"] = {
            "status": "approved",
            "reviewed_by": "schema-test-reviewer",
            "reviewer_role": "technical_reviewer",
            "review_scope": ["schema"],
            "reviewed_on": "2026-08-20",
            "reviewed_record_version": workflow["record_version"],
            "review_notes": "Synthetic test provenance; not sample-data review.",
        }

        invalid_result = self.validate_with_standard_cli("workflow.schema.json", workflow)
        self.assertNotEqual(0, invalid_result.returncode)

        workflow["review"]["review_scope"] = sorted(
            repository_validator.required_supported_review_scopes("workflow", workflow)
        )
        valid_result = self.validate_with_standard_cli("workflow.schema.json", workflow)
        self.assertEqual(0, valid_result.returncode, valid_result.stderr)


class CrossRecordReferenceTests(unittest.TestCase):
    def test_all_schema_reference_fields_have_explicit_specs(self) -> None:
        discovered: set[str] = set()
        for schema_path in SCHEMA_DIR.glob("*.json"):
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            discovered.update(
                repository_validator.discover_schema_reference_fields(schema)
            )
        self.assertEqual(discovered, set(repository_validator.REFERENCE_FIELDS))

    def test_supported_policies_cover_every_record_kind(self) -> None:
        record_kinds = {
            kind for kind, _schema_name in repository_validator.DATA_SCHEMAS.values()
        }
        self.assertEqual(
            record_kinds, set(repository_validator.SUPPORTED_DEPENDENCY_ELIGIBILITY)
        )
        self.assertEqual(record_kinds, set(repository_validator.SUPPORTED_REVIEW_SCOPES))

    def test_typed_dangling_references_are_reported(self) -> None:
        record = {
            "status": "proposed",
            "review": {"status": "proposed"},
            "intake_ids": ["missing-intake"],
            "depends_on": ["missing-step"],
            "excluded_workflow_ids": ["missing-workflow"],
            "excluded_process_step_ids": ["missing-excluded-step"],
            "excluded_document_ids": ["missing-document"],
        }
        records = {"risk": {"fixture": record}}
        locations = {("risk", "fixture"): "test:fixture"}
        report = repository_validator.ValidationReport()

        repository_validator.validate_cross_record_references(
            records, locations, report
        )

        self.assertEqual(5, len(report.errors))
        self.assertTrue(all("unknown" in error for error in report.errors))

    def test_negative_fixture_source_may_be_rejected(self) -> None:
        fixture = {
            "status": "supported",
            "related_records": {"source_ids": ["rejected-source"]},
            "source_context": {
                "prohibited_source_ids": ["rejected-source"],
            },
        }
        fixture["review"] = approved_review("evaluation_fixture", fixture)
        rejected_source = {
            "status": "rejected",
            "review": {"status": "rejected"},
        }
        records = {
            "evaluation_fixture": {"fixture": fixture},
            "source": {"rejected-source": rejected_source},
        }
        locations = {
            ("evaluation_fixture", "fixture"): "test:fixture",
            ("source", "rejected-source"): "test:rejected-source",
        }
        report = repository_validator.ValidationReport()

        repository_validator.validate_cross_record_references(
            records, locations, report
        )

        self.assertEqual([], report.errors)

    def test_rejected_source_cannot_be_a_supporting_dependency(self) -> None:
        response = {
            "status": "supported",
            "related_records": {"source_ids": ["rejected-source"]},
            "source_use": {"source_required": False},
        }
        response["review"] = approved_review("response", response)
        rejected_source = {
            "status": "rejected",
            "review": {"status": "rejected"},
        }
        records = {
            "response": {"response": response},
            "source": {"rejected-source": rejected_source},
        }
        locations = {
            ("response", "response"): "test:response",
            ("source", "rejected-source"): "test:rejected-source",
        }
        report = repository_validator.ValidationReport()

        repository_validator.validate_cross_record_references(
            records, locations, report
        )

        self.assertTrue(
            any("ineligible supporting source" in error for error in report.errors)
        )

    def test_supported_workflow_rejects_proposed_process_step(self) -> None:
        workflow = {
            "status": "supported",
            "process": {"process_step_ids": ["proposed-step"]},
        }
        workflow["review"] = approved_review("workflow", workflow)
        proposed_step = {"status": "proposed", "review": {"status": "proposed"}}
        records = {
            "workflow": {"workflow": workflow},
            "process_step": {"proposed-step": proposed_step},
        }
        locations = {
            ("workflow", "workflow"): "test:workflow",
            ("process_step", "proposed-step"): "test:proposed-step",
        }
        report = repository_validator.ValidationReport()

        repository_validator.validate_cross_record_references(records, locations, report)

        self.assertTrue(
            any("ineligible supporting process_step" in error for error in report.errors)
        )

    def test_supported_workflow_rejects_proposed_evaluation_fixture(self) -> None:
        workflow = {
            "status": "supported",
            "evaluation": {
                "required_evaluation_fixture_ids": ["proposed-fixture"]
            },
        }
        workflow["review"] = approved_review("workflow", workflow)
        proposed_fixture = {
            "status": "proposed",
            "review": {"status": "proposed"},
        }
        records = {
            "workflow": {"workflow": workflow},
            "evaluation_fixture": {"proposed-fixture": proposed_fixture},
        }
        locations = {
            ("workflow", "workflow"): "test:workflow",
            ("evaluation_fixture", "proposed-fixture"): "test:proposed-fixture",
        }
        report = repository_validator.ValidationReport()

        repository_validator.validate_cross_record_references(records, locations, report)

        self.assertTrue(
            any(
                "ineligible supporting evaluation_fixture" in error
                for error in report.errors
            )
        )

    def test_supported_workflow_accepts_eligible_dependencies(self) -> None:
        workflow = {
            "status": "supported",
            "process": {"process_step_ids": ["supported-step"]},
            "evaluation": {
                "required_evaluation_fixture_ids": ["supported-fixture"]
            },
        }
        workflow["review"] = approved_review("workflow", workflow)
        supported_step = {"status": "supported"}
        supported_step["review"] = approved_review("process_step", supported_step)
        supported_fixture = {"status": "supported"}
        supported_fixture["review"] = approved_review(
            "evaluation_fixture", supported_fixture
        )
        records = {
            "workflow": {"workflow": workflow},
            "process_step": {"supported-step": supported_step},
            "evaluation_fixture": {"supported-fixture": supported_fixture},
        }
        locations = {
            ("workflow", "workflow"): "test:workflow",
            ("process_step", "supported-step"): "test:supported-step",
            ("evaluation_fixture", "supported-fixture"): "test:supported-fixture",
        }
        report = repository_validator.ValidationReport()

        repository_validator.validate_cross_record_references(records, locations, report)

        self.assertEqual([], report.errors)

    def test_backlink_associations_do_not_gate_lifecycle_promotion(self) -> None:
        process_step = {
            "status": "supported",
            "workflow_ids": ["proposed-workflow"],
        }
        process_step["review"] = approved_review("process_step", process_step)
        legal_rule = {
            "status": "supported",
            "document_fit": {"supported_document_ids": ["proposed-document"]},
        }
        legal_rule["review"] = approved_review("legal_rule", legal_rule)
        records = {
            "process_step": {"supported-step": process_step},
            "workflow": {
                "proposed-workflow": {
                    "status": "proposed",
                    "review": {"status": "proposed"},
                }
            },
            "legal_rule": {"supported-rule": legal_rule},
            "legal_document": {
                "proposed-document": {
                    "status": "proposed",
                    "review": {"status": "proposed"},
                }
            },
        }
        locations = {
            (kind, record_id): f"test:{record_id}"
            for kind, kind_records in records.items()
            for record_id in kind_records
        }
        report = repository_validator.ValidationReport()

        repository_validator.validate_cross_record_references(records, locations, report)

        self.assertEqual([], report.errors)

    def test_reciprocal_backlink_does_not_create_support_gating_cycle(self) -> None:
        records = {
            "workflow": {
                "workflow": {
                    "process": {"process_step_ids": ["step"]},
                }
            },
            "process_step": {
                "step": {
                    "workflow_ids": ["workflow"],
                }
            },
        }

        edges = repository_validator.supporting_dependency_edges(records)
        adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for source, target in edges:
            adjacency.setdefault(source, set()).add(target)

        def has_cycle(node: tuple[str, str], visiting: set, visited: set) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(has_cycle(child, visiting, visited) for child in adjacency.get(node, set())):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        nodes = set(adjacency) | {target for targets in adjacency.values() for target in targets}
        self.assertFalse(any(has_cycle(node, set(), set()) for node in nodes))
        self.assertEqual(
            {
                (("workflow", "workflow"), ("process_step", "step")),
            },
            edges,
        )


class SampleSemanticRegressionTests(unittest.TestCase):
    def test_corrected_workflows_do_not_contain_known_template_leakage(self) -> None:
        workflows = {
            workflow["id"]: workflow
            for workflow in json.loads(
                (ROOT / "data" / "sample-workflows.json").read_text(encoding="utf-8")
            )
        }
        forbidden_phrases = {
            "civil_discovery_information": (
                "minor's name",
                "domestic violence",
                "immigration",
            ),
            "subpoena_information": (
                "minor's name",
                "domestic violence",
                "immigration",
            ),
            "small_business_dispute_information": (
                "renewal",
                "agency approval",
                "licensing",
                "tax requirements",
                "agency requirements",
            ),
        }

        for workflow_id, phrases in forbidden_phrases.items():
            serialized = json.dumps(workflows[workflow_id]).lower()
            with self.subTest(workflow_id=workflow_id):
                for phrase in phrases:
                    self.assertNotIn(phrase, serialized)
                self.assertEqual("proposed", workflows[workflow_id]["status"])

    def test_proposed_workflows_do_not_claim_reviewed_source_metadata(self) -> None:
        workflows = {
            workflow["id"]: workflow
            for workflow in json.loads(
                (ROOT / "data" / "sample-workflows.json").read_text(encoding="utf-8")
            )
        }
        for workflow_id in (
            "name_change_information",
            "small_business_license_information",
        ):
            with self.subTest(workflow_id=workflow_id):
                workflow = workflows[workflow_id]
                self.assertIn("placeholder source metadata", workflow["description"])
                self.assertNotIn("reviewed source metadata", workflow["description"])
                self.assertEqual("proposed", workflow["status"])
                self.assertEqual("proposed", workflow["review"]["status"])

    def test_virginia_response_choice_fixture_routes_to_proposed_strategy_risk(self) -> None:
        fixtures = json.loads(
            (ROOT / "data" / "sample-evaluation-fixtures.json").read_text(encoding="utf-8")
        )
        risks = json.loads((ROOT / "data" / "sample-risks.json").read_text(encoding="utf-8"))
        fixture = next(
            item for item in fixtures if item["id"] == "va-small-claims-response-choice-fixture"
        )
        risk = next(item for item in risks if item["id"] == "va-small-claims-response-choice-risk")

        self.assertTrue(fixture["risk"]["risk_expected"])
        self.assertEqual([risk["id"]], fixture["risk"]["expected_risk_ids"])
        self.assertEqual([risk["id"]], fixture["related_records"]["risk_ids"])
        self.assertEqual("avoid_final_decision", fixture["risk"]["risk_routing_expected"])
        self.assertEqual("unsafe_user_request", risk["risk_type"])
        self.assertEqual("proposed", risk["status"])
        self.assertEqual("proposed", risk["review"]["status"])
        self.assertEqual(
            [fixture["id"]], risk["evaluation"]["required_evaluation_fixture_ids"]
        )


class ProjectScanTests(unittest.TestCase):
    def test_generated_environment_directories_are_excluded(self) -> None:
        excluded_examples = (
            ROOT / ".venv" / "invalid.json",
            ROOT / "node_modules" / "invalid.md",
            ROOT / "vendor" / "invalid.yml",
            ROOT / "build" / "invalid.py",
        )
        self.assertTrue(
            all(not repository_validator.is_project_owned(path) for path in excluded_examples)
        )


if __name__ == "__main__":
    unittest.main()
