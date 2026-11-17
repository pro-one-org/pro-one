"""Canonical matter commands. Models supply proposals; commands control trust."""
from hashlib import sha256
import re
from uuid import uuid4

from pydantic import Field

from app.documents import isolated_extract
from app.matter_ingest import INSTRUCTIONS, grounded_rows, propose
from app.matter_models import (
    Assertion, Correction, Dispute, DocumentSource, Evidence, Event, ExternalRecord,
    ExternalSource, Gap, IdentityCandidate, InferenceSource, Matter, Message, Party,
    Record, Target, Text, UserSource,
)
from app.matter_state import (
    BASE_GAPS, EVENT_FIELDS, IDENTITY_FIELDS, OPTIONAL_EVENT_FIELDS, PARTY_FIELDS, MatterError, equivalent,
    norm, page_at, projection, source_status,
)
from app.matter_store import RevisionConflict, now


class ImportedRecord(Record):
    """A trusted operator's reviewed registry extract, independent of API clients."""
    source: ExternalRecord
    excerpt: str = Field(min_length=1, max_length=16000)
    kind: str = Field(pattern=r"^(corporate_record|government_record)$")
    limitations: tuple[Text, ...] = Field(default=(), max_length=8)


def records_by_id(config):
    return {(record.source.provider, record.source.record_id): record for record in config}


class MatterService:
    def __init__(self, store, *, registry=None, provider="", model="", records=None):
        self.store = store
        self.registry = registry
        self.provider = provider
        self.model = model
        self.records = records or {}

    @staticmethod
    def revise(base, on, **append):
        changes = {key: getattr(base, key) + tuple(values) for key, values in append.items()}
        clean = base.model_dump()
        return Matter.model_validate(clean | changes | {"revision": base.revision + 1, "updated_at": on})

    def read(self, matter_id, revision):
        base = self.store.get(matter_id)
        if base.revision != revision:
            raise RevisionConflict("revision_conflict")
        return base

    def candidates(self, text, origin, enabled):
        if enabled and self.registry and not INSTRUCTIONS.search(text):
            return propose(self.registry, self.provider, self.model, text, origin)
        return None

    def create(self, text, *, model_assistance=False):
        on = now()
        matter = Matter(id=uuid4(), revision=0, created_at=on, updated_at=on,
                        gaps=tuple(Gap(target=Target(field=field), question=prompt,
                                       status="unresolved" if field in PARTY_FIELDS else "unknown")
                                   for field, prompt in BASE_GAPS.items()))
        result, review = self.statement_update(matter, text, on, model_assistance=model_assistance)
        payload = result.model_dump() | {"revision": 0}
        return self.store.create(Matter.model_validate(payload)), review

    def statement(self, base, text, **options):
        result, review = self.statement_update(base, text, now(), **options)
        return self.store.update(base, result), review

    def statement_update(self, base, text, on, *, message_id=None, party=None, event=None, event_kind=None,
                         participants=(), related_evidence=(), new_party_role=None,
                         corrects=(), disputes=None, model_assistance=False):
        message = Message(id=message_id or uuid4(), text=text, received_at=on)
        prior_message = next((row for row in base.messages if row.id == message.id), None)
        if prior_message:
            raise MatterError("message_id_already_recorded")
        source = UserSource(message_id=message.id)
        review = self.candidates(text, source.kind, model_assistance)
        rows = tuple(grounded_rows(text, source.kind))
        patch = self.add_rows(base, rows, on, source, party=party, event=event, event_kind=event_kind,
                              participants=participants, related_evidence=related_evidence,
                              new_party_role=new_party_role, force=bool(corrects))
        added = tuple(patch["assertions"])
        if review and review.possible_issue and issue_supported(text, review.possible_issue):
            patch["assertions"].append(Assertion(
                id=uuid4(), target=Target(field="possible_legal_issue"), value=review.possible_issue,
                source=InferenceSource(message_id=message.id, provider=self.provider, model=self.model),
                received_at=on, status="inferred"))
        active = {row.id: row for row in base.assertions}
        retired = {row.previous for row in base.corrections}
        if len(set(corrects)) != len(corrects):
            raise MatterError("duplicate_correction")
        corrections = []
        for previous in corrects:
            old = active.get(previous)
            replacements = [a for a in added if old and a.target == old.target]
            if not old or previous in retired or old.status in {"inferred", "alleged"} or len(replacements) != 1:
                raise MatterError("correction_requires_single_supported_replacement")
            corrections.append(Correction(previous=previous, replacement=replacements[0].id,
                                          message=source, received_at=on))
        # A dedicated goal statement represents a new objective and retains the earlier goal.
        if not corrects and len(rows) == 1 and rows[0][0] == "goal" and added:
            corrections.extend(Correction(previous=row.id, replacement=added[0].id, message=source, received_at=on)
                               for row in base.assertions if row.target.field == "goal" and row.id not in retired)
        if disputes:
            if disputes not in active or disputes in retired:
                raise MatterError("invalid_dispute")
            patch["disputes"] = [Dispute(assertion=disputes, message=source, received_at=on)]
        result = self.revise(base, on, messages=(message,), corrections=corrections, **patch)
        return result, review.suggestions if review else ()

    @staticmethod
    def add_rows(base, rows, on, source, *, evidence=None, party=None, event=None, event_kind=None,
                 participants=(), related_evidence=(), new_party_role=None, force=False):
        """Apply source-specific proposals to a single explicit or default subject."""
        patch = {"assertions": [], "parties": [], "events": [], "identities": []}
        if (party and not any(row.id == party for row in base.parties)
                or event and not any(row.id == event for row in base.events)
                or party and new_party_role or event and event_kind):
            raise MatterError("invalid_subject_reference")
        if not event_kind and (participants or related_evidence):
            raise MatterError("event_required_for_relationships")
        explicit_event = event is not None or event_kind is not None
        if not explicit_event and sum(row.kind == "incident" for row in base.events) > 1 and any(
            row[0] in EVENT_FIELDS | OPTIONAL_EVENT_FIELDS for row in rows
        ):
            raise MatterError("incident_requires_explicit_scope")
        initial_party = next((row for row in rows if row[0] in {"brand", "legal_name"}), None)
        if not party and (new_party_role or (initial_party and not base.parties)):
            if not initial_party:
                raise MatterError("party_requires_attributed_name")
            party = uuid4()
        elif not party and len(base.parties) == 1:
            party = base.parties[0].id
        new_party = party is not None and all(row.id != party for row in base.parties)
        # Primary incident is canonical for unscoped incident updates.
        if not event and not event_kind:
            event = next((row.id for row in base.events if row.kind == "incident"), None)
            if not event and any(field in EVENT_FIELDS or field == "matter_type" for field, *_ in rows):
                event_kind = "incident"
        if event_kind:
            event = uuid4()
            origin = evidence.id if evidence else source.message_id
            patch["events"].append(Event(id=event, kind=event_kind, origin=origin,
                                         participants=participants or ((party,) if party and event_kind == "incident" else ()),
                                         evidence=related_evidence or ((evidence.id,) if evidence else ())))
        superseded = {row.previous for row in base.corrections}
        prior_sources = {row.id: row.text for row in base.messages}
        for field, value, quote, offset in rows:
            event_scoped = field in EVENT_FIELDS or (explicit_event and field in OPTIONAL_EVENT_FIELDS)
            subject = party if field in PARTY_FIELDS else event if event_scoped else None
            if field in PARTY_FIELDS | EVENT_FIELDS and subject is None:
                continue
            # A differently named business requires an explicit scope; never merge by a name.
            if field == "brand" and not new_party and not force and any(
                a.target == Target(field="brand", subject=party) and not equivalent(a.value, value)
                for a in base.assertions if a.id not in superseded
            ):
                raise MatterError("distinct_party_requires_explicit_creation_or_correction")
            target = Target(field=field, subject=subject)
            attribution = source or (
                ExternalSource(evidence_id=evidence.id, excerpt=quote, offset=offset)
                if evidence.external else DocumentSource(evidence_id=evidence.id, excerpt=quote, offset=offset,
                                                         page=page_at(evidence, offset))
            )
            status = source_status(attribution, evidence)
            if any(a.target == target and equivalent(a.value, value) for a in patch["assertions"]):
                continue
            if not force and source and any(
                a.target == target and equivalent(a.value, value) and a.locator == quote
                and a.source.kind == source.kind and a.source.message_id in prior_sources
                for a in base.assertions if a.id not in superseded
            ):
                continue
            row = Assertion(id=uuid4(), target=target, value=value, source=attribution, status=status,
                            received_at=on, locator=quote if source else None)
            patch["assertions"].append(row)
            if new_party and initial_party and field == initial_party[0] and not patch["parties"]:
                patch["parties"].append(Party(id=party, origin=row.id, role=new_party_role or "business_involved"))
            if field in IDENTITY_FIELDS:
                anchor = registry_anchor(base, party, evidence.external) if evidence and evidence.external else None
                patch["identities"].append(IdentityCandidate(
                    party=party, assertion=row.id, relationship={"legal_name": "legal_name", "operator": "operator",
                    "property_owner": "owner"}[field], corroborates=anchor))
        return patch

    def upload(self, base, raw, content_type, kind, *, party=None, event=None, model_assistance=False):
        digest = sha256(raw).hexdigest()
        if any(row.content_hash == digest for row in base.evidence):
            return base, ()
        try:
            parsed = isolated_extract(raw, content_type, include_locators=True)
        except Exception:
            raise MatterError("document_extraction_failed") from None
        on = now()
        text = parsed["text"]
        kind = "court_filing" if kind != "legal_authority" and pleading(text) else kind
        item = Evidence(id=uuid4(), kind=kind, origin="user_upload", extracted_text=text,
                        content_hash=digest, extraction="extracted", received_at=on,
                        limitations=tuple(parsed["warnings"]), page_offsets=tuple(parsed.get("page_offsets", ())),
                        custody="supplied_by_user")
        review = self.candidates(text, "document", model_assistance)
        rows = tuple(grounded_rows(text, "document", kind))
        patch = self.add_rows(base, rows, on, None, evidence=item, party=party, event=event)
        receipt = Event(id=uuid4(), kind="document_received", origin=item.id, evidence=(item.id,))
        patch["events"].append(receipt)
        return self.store.update(base, self.revise(base, on, evidence=(item,), **patch)), review.suggestions if review else ()

    def inventory(self, base, kind, label, custody):
        on = now()
        item = Evidence(id=uuid4(), kind=kind, origin="user_inventory", label=label, custody=custody,
                        extraction="metadata_only", received_at=on)
        return self.store.update(base, self.revise(base, on, evidence=(item,)))

    def external(self, base, provider, record_id, *, party=None):
        record = self.records.get((provider, record_id))
        if not record:
            raise MatterError("external_record_not_configured")
        text = record.excerpt
        digest = sha256(record.model_dump_json().encode()).hexdigest()
        existing = {item.id for item in base.evidence if item.content_hash == digest}
        prior = {row.id for row in base.assertions if isinstance(row.source, ExternalSource)
                 and row.source.evidence_id in existing and row.target.subject == party}
        if prior and (any(row.assertion in prior and row.corroborates for row in base.identities)
                      or not registry_anchor(base, party, record.source)):
            return base
        on = now()
        item = Evidence(id=uuid4(), kind=record.kind, origin="external_record", content_hash=digest,
                        extracted_text=text, received_at=on, extraction="extracted", external=record.source,
                        limitations=record.limitations)
        # Registry records support bounded identity observations, never incident facts or legal conclusions.
        rows = tuple(row for row in grounded_rows(text, "external_record") if row[0] in IDENTITY_FIELDS)
        if not rows or not party:
            raise MatterError("external_record_requires_party_and_identity_evidence")
        patch = self.add_rows(base, rows, on, None, evidence=item, party=party)
        return self.store.update(base, self.revise(base, on, evidence=(item,), **patch))


def registry_anchor(base, party, record):
    fields = projection(base)
    known = fields.get(Target(field="registry_id", subject=party), {}).get("preferred")
    scope = next((row for row in base.parties if row.id == party), None)
    proof = next((item for item in base.evidence if known and isinstance(known.source, DocumentSource)
                  and item.id == known.source.evidence_id), None)
    origin = next((row for row in base.assertions if scope and row.id == scope.origin), None)
    if (known and proof and origin and proof.content_hash == record.link_evidence_hash
            and equivalent(origin.value, record.subject_label)
            and known.value == f"{record.provider}/{record.record_id}"
            and not any(row.previous == origin.id for row in base.corrections)
            and not any(row.assertion == origin.id for row in base.disputes)):
        return known.id
    return None


def issue_supported(text, issue):
    # Independent eligibility. A model cannot create an issue classification from an unrelated statement.
    terms = {"premises_liability": r"\b(?:slipped|fell|wet floor)\b",
             "civil_procedure": r"\b(?:summons|complaint|served)\b", "contract": r"\b(?:contract|agreement)\b"}
    return bool(re.search(terms[issue], text, re.I))


def pleading(text):
    return bool(re.search(r"\b(?:plaintiff|defendant)\b.{0,90}\b(?:alleges?|knowingly failed)\b|"
                          r"^\s*(?:civil )?(?:complaint|petition|amended complaint)\s*$", text, re.I | re.M))
