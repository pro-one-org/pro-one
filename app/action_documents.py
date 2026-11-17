"""Deterministic preparation copies, with an exact display digest and field manifests."""
from fastapi.encoders import jsonable_encoder

from app.claim_catalog import fingerprint


def assemble(catalog, matter, readiness, deadline_records):
    definition = catalog.actions[readiness["action"]["id"]]
    template = catalog.templates[definition.template]
    support = readiness["resolved_fields"]
    procedure = catalog.procedure
    forum = procedure.forums.get(definition.forum)
    theories = readiness["theory_refs"]
    sections, manifest, missing = [], [], []
    lines = [template.title, "Development reference copy. External execution is disabled."]
    for section in template.sections:
        lines.extend(("", section.title))
        fields = []
        for number, field in enumerate(section.fields, 1):
            provenance = None
            value = None
            if field.source == "forum" and forum and readiness["choice"]:
                value = forum.name
                provenance = {"kind": "forum", "id": definition.forum, "court_id": forum.court_id,
                              "authority": tuple(catalog.authority(ref.authority) for ref in forum.evidence)}
            elif field.source == "theory" and theories:
                value = [row["label"] for row in theories]
                provenance = {"kind": "claim_report", "id": readiness["claim_analysis_id"],
                              "theories": [{"id": row["id"], "version": row["version"],
                                            "authority": row["authority"]} for row in theories]}
            elif field.source in support:
                record = support[field.source]
                value, provenance = record["value"], record["selected"]
            placeholder = None
            if value is None and field.required:
                missing.append(field.id)
                placeholder = f"[{field.title.upper()} UNRESOLVED]"
            fields.append({"id": field.id, "label": field.title, "value": value, "placeholder": placeholder,
                           "required": field.required, "paragraph": number if section.number_paragraphs else None})
            manifest.append({"field_id": field.id, "source": field.source, "provenance": provenance})
            if value is not None or placeholder:
                prefix = f"{number}. " if section.number_paragraphs else ""
                display = ("; ".join(value) if isinstance(value, list) else "Yes" if value is True else
                           "No" if value is False else str(value)) if value is not None else placeholder
                lines.append(f"{prefix}{field.title}: {display}")
        sections.append({"title": section.title, "fields": fields})
    status = ("incomplete" if missing else "blocked" if readiness["status"] == "blocked"
              else "draft" if readiness["status"] != "ready_for_document_preparation" else "ready_for_user_review")
    signature = None
    if template.unsigned_signature_block:
        signature = {"state": "unsigned", "name": support.get("plaintiff_name", {}).get("value"),
                     "contact_state": "requires_review"}
        lines.extend(("", "Signature block", "Unsigned preparation copy. Review applicable signing and contact requirements."))

    def procedure_rows(which):
        return [{"id": key, "conditions": item.conditions, which: getattr(item, which),
                 "authority": tuple(catalog.procedure_evidence((key,)).values())}
                for key in definition.procedure_refs
                if (item := procedure.requirements[key]) and getattr(item, which)]

    used_evidence = {row["provenance"].get("evidence_id") for row in manifest if row["provenance"]}
    exhibit_inventory = [
        {"evidence_id": item.id, "content_hash": item.content_hash, "kind": item.kind,
         "status": "source_record_for_review"}
        for item in matter.evidence if str(item.id) in used_evidence and item.kind in template.attachment_kinds
    ]
    adverse = sorted({identity for row in theories for identity in row["adverse_or_conflicting_assertions"]})
    payload = {
        "action_id": definition.id, "readiness_id": readiness["artifact_id"], "status": status,
        "document": {"type": template.document_type, "title": template.title, "sections": sections,
                     "caption": sections[0]["fields"] if template.include_caption else None,
                     "signature": signature, "plain_text": "\n".join(lines) + "\n"},
        "filing": procedure_rows("filing"), "fees": procedure_rows("fee"), "service": procedure_rows("service"),
        "service_contact": support.get("registered_agent"),
        "parties": {"filing_party": readiness["user_party_id"], "selected_counterparty": readiness["party_id"]},
        "destination": {"forum_id": definition.forum, "court_id": forum.court_id if forum else None,
                        "court_name": forum.name if forum else None, "scope": "proposed_destination_for_review"},
        "exhibit_inventory": exhibit_inventory, "deadline_context": [
            {"id": row["artifact_id"], "status": row["status"], "calculated_date": row["calculated_date"],
             "reason": row["reason"], "explanation": row["explanation"]} for row in deadline_records
        ],
        "readiness_context": {key: readiness[key] for key in ("status", "dimensions", "blockers", "warnings")},
        "manifest": {"template_id": template.id, "template_version": template.version,
                     "matter_revision": matter.revision, "claim_analysis_id": readiness["claim_analysis_id"],
                     "readiness_id": readiness["artifact_id"], "procedural_snapshot": readiness["dependencies"]["procedure"],
                     "field_mappings": manifest, "unresolved_fields": missing, "adverse_or_conflicting_assertions": adverse},
        "review_status": "unreviewed", "external_execution": "disabled",
    }
    payload = jsonable_encoder(payload)
    return payload | {"displayed_digest": fingerprint(payload).split(":", 1)[1]}
