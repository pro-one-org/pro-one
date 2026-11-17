"""Explicitly enabled local matter API with per-matter access and release gates."""
from datetime import date
import hmac
import os
from pathlib import Path
import re
import sqlite3
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field, TypeAdapter
from starlette.concurrency import run_in_threadpool

from app.capabilities import ResearchMatter
from app.claim_models import AnalyzeClaim
from app.claim_service import ClaimService
from app.claim_store import ClaimStore
from app.legal_research import GeneralLegalResearchService
from app.matter_models import Choice, EvidenceKind, EventKind, FieldName, Message, PartyRole, Record, Target, Text, UserSource
from app.matter_service import ImportedRecord, MatterService, records_by_id
from app.matter_state import MatterError, procedural_facts, projection, snapshot
from app.matter_store import MatterNotFound, MatterStore, RevisionConflict, now
from app.procedural_models import Key, Scope
from app.procedural_research import ProceduralRequest, ProceduralResearchService, US_STATE_NAMES


class CreateMatter(Record):
    text: str = Field(min_length=1, max_length=2000)
    model_assistance: bool = False


class Statement(CreateMatter):
    revision: int = Field(ge=0)
    message_id: UUID | None = None
    party: UUID | None = None
    event: UUID | None = None
    event_kind: EventKind | None = None
    participants: tuple[UUID, ...] = Field(default=(), max_length=12)
    related_evidence: tuple[UUID, ...] = Field(default=(), max_length=12)
    new_party_role: PartyRole | None = None
    corrects: tuple[UUID, ...] = Field(default=(), max_length=12)
    disputes: UUID | None = None


class Inventory(Record):
    revision: int = Field(ge=0)
    kind: EvidenceKind
    label: Text | None = None
    custody: Text | None = None


class RegistryLookup(Record):
    revision: int = Field(ge=0)
    provider: Key
    record_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,119}$")
    party: UUID


class Procedure(Record):
    revision: int = Field(ge=0)
    message: str = Field(min_length=1, max_length=2000)
    as_of: date | None = None
    selected_path: Key | None = None
    choice_token: str = Field(default="", max_length=2000)
    stage: Key | None = None


class Research(Record):
    area: Key
    topics: tuple[Key, ...] = Field(min_length=1, max_length=8)
    context_fields: tuple[FieldName, ...] = Field(default=(), max_length=12)


def matter_token(secret, matter_id):
    return hmac.digest(secret.encode("ascii"), b"pro-one/matter-access/v1\x00" + matter_id.bytes, "sha256").hex()


def router(settings, repository, generation):
    routes = APIRouter(prefix="/matters", tags=["development matters"])

    def access(request, matter_id=None):
        config = settings()
        if config.mode != "development":
            raise HTTPException(403, detail={"code": "matter_release_review_required"})
        secret = os.environ.get("PRO_ONE_MATTER_TOKEN", "")
        path = os.environ.get("PRO_ONE_MATTER_DB", "")
        if not path or not re.fullmatch(r"[0-9a-f]{64}", secret):
            raise HTTPException(403, detail={"code": "matter_development_disabled"})
        token = matter_token(secret, matter_id) if matter_id else secret
        auth = request.headers.get("authorization", "")
        if not auth.isascii() or not hmac.compare_digest(auth, f"Bearer {token}"):
            raise HTTPException(403, detail={"code": "matter_access_denied"})
        return config, path, secret

    def service(config, path, *, external=False):
        records = {}
        if external and (filename := os.environ.get("PRO_ONE_MATTER_RECORDS")):
            with Path(filename).open("rb") as file:
                payload = file.read(256001)
            if len(payload) > 256000:
                raise MatterError("matter_registry_limit")
            entries = TypeAdapter(list[ImportedRecord]).validate_json(payload)
            records = records_by_id(entries)
            if len(records) != len(entries):
                raise MatterError("duplicate_matter_registry_record")
        return MatterService(MatterStore(path), registry=generation.registry, provider=config.provider,
                             model=config.model, records=records)

    def execute(action):
        try:
            return action()
        except MatterNotFound as exc:
            raise HTTPException(404, detail={"code": str(exc)}) from None
        except RevisionConflict as exc:
            raise HTTPException(409, detail={"code": str(exc)}) from None
        except MatterError as exc:
            raise HTTPException(422, detail={"code": str(exc)}) from None
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(503, detail={"code": "matter_storage_or_record_unavailable"}) from None

    @routes.post("", status_code=201)
    def create(request: Request, body: CreateMatter):
        config, path, secret = access(request)

        def apply():
            matter, review = service(config, path).create(body.text, model_assistance=body.model_assistance)
            return {"matter": snapshot(matter), "review": review, "access_token": matter_token(secret, matter.id)}

        return execute(apply)

    @routes.get("/{matter_id}")
    def get(request: Request, matter_id: UUID, revision: int | None = Query(default=None, ge=0, le=199)):
        config, path, _ = access(request, matter_id)
        return execute(lambda: snapshot(service(config, path).store.get(matter_id, revision)))

    @routes.get("/{matter_id}/procedural-facts")
    def read_facts(request: Request, matter_id: UUID):
        config, path, _ = access(request, matter_id)

        def read():
            matter = service(config, path).store.get(matter_id)
            _, facts = procedural_facts(projection(matter), matter.parties)
            return {"revision": matter.revision, "facts": facts}

        return execute(read)

    @routes.post("/{matter_id}/statements")
    def statement(request: Request, matter_id: UUID, body: Statement):
        config, path, _ = access(request, matter_id)

        def apply():
            ledger = service(config, path)
            matter, review = ledger.statement(ledger.read(matter_id, body.revision),
                                             **body.model_dump(exclude={"revision"}))
            return {"matter": snapshot(matter), "review": review}

        return execute(apply)

    @routes.post("/{matter_id}/documents")
    async def document(request: Request, matter_id: UUID, revision: int = Query(ge=0), *,
                       kind: EvidenceKind = "document", party: UUID | None = None, event: UUID | None = None,
                       model_assistance: bool = False):
        config, path, _ = access(request, matter_id)
        raw = await request.body()
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()

        def apply():
            ledger = service(config, path)
            matter, review = ledger.upload(ledger.read(matter_id, revision), raw, content_type, kind,
                                           party=party, event=event, model_assistance=model_assistance)
            return {"matter": snapshot(matter), "review": review}

        return await run_in_threadpool(execute, apply)

    @routes.post("/{matter_id}/evidence")
    def inventory(request: Request, matter_id: UUID, body: Inventory):
        config, path, _ = access(request, matter_id)

        def apply():
            ledger = service(config, path)
            return snapshot(ledger.inventory(ledger.read(matter_id, body.revision), body.kind, body.label, body.custody))

        return execute(apply)

    @routes.post("/{matter_id}/external-records")
    def external(request: Request, matter_id: UUID, body: RegistryLookup):
        config, path, _ = access(request, matter_id)

        def apply():
            ledger = service(config, path, external=True)
            return snapshot(ledger.external(ledger.read(matter_id, body.revision), body.provider, body.record_id,
                                            party=body.party))

        return execute(apply)

    @routes.post("/{matter_id}/procedure")
    def procedure(request: Request, matter_id: UUID, body: Procedure):
        config, path, _ = access(request, matter_id)

        def apply():
            ledger = service(config, path)
            matter = ledger.read(matter_id, body.revision)
            facts, reports = procedural_facts(projection(matter), matter.parties)
            if reports["jurisdiction"]["state"] != "known" or reports["forum"]["state"] in {"conflicting", "unsupported"}:
                return {"revision": matter.revision, "status": "matter_scope_requires_confirmation",
                        "facts": {"jurisdiction": reports["jurisdiction"], "forum": reports["forum"]}}
            procedure_service = ProceduralResearchService(repository, config, generation)
            request_data = body.model_dump(exclude={"revision"}) | {
                "jurisdiction": reports["jurisdiction"]["value"], "forum": reports["forum"]["value"], "facts": facts,
            }
            result = procedure_service.respond(ProceduralRequest.model_validate(request_data),
                                               matter_scope=f"{matter.id}:{matter.revision}")
            if result.get("selection_origin") == "user" and result["status"] in {
                "option_explained", "reference_only", "prerequisite_missing", "procedure_explained",
            }:
                on = now()
                message = Message(id=uuid4(), text=body.message, received_at=on)
                choice = Choice(path=result["selected_path"], jurisdiction=result["jurisdiction"],
                                forum=reports["forum"]["value"], catalog_version=result["catalog_version"],
                                reference_date=result["reference_date"], based_on_revision=matter.revision,
                                procedural_status=result["status"], stage=result.get("stage"),
                                message=UserSource(message_id=message.id), received_at=on)
                matter = ledger.store.update(matter, ledger.revise(matter, on, messages=(message,), choices=(choice,)))
            return result | {"revision": matter.revision, "matter_facts": reports}

        return execute(apply)

    @routes.post("/{matter_id}/research")
    def research(request: Request, matter_id: UUID, body: Research):
        config, path, _ = access(request, matter_id)

        def assemble():
            ledger = service(config, path)
            matter = ledger.store.get(matter_id)
            fields = projection(matter)
            jurisdiction = fields.get(Target(field="jurisdiction"), {}).get("preferred")
            if jurisdiction is None:
                return {"status": "matter_scope_requires_confirmation", "revision": matter.revision}
            scope = jurisdiction.value
            scope = TypeAdapter(Scope).validate_python(scope)
            request_data = ResearchMatter(country="US", sovereign="federal" if scope == "US" else "state",
                                          state=US_STATE_NAMES.get(scope[3:]), legal_area=body.area, topics=list(body.topics))
            research_service = GeneralLegalResearchService(repository, config)
            try:
                result = research_service.assemble(request_data)
            finally:
                research_service.close()
            # Return bounded context alongside authority, without exporting facts to providers.
            keys = set(body.context_fields) | {"jurisdiction", "matter_type", "goal"}
            context = [{"target": target, "status": fact["status"],
                        "value": fact["preferred"].value if fact["preferred"] else None,
                        "assertion_ids": fact["assertions"]} for target, fact in fields.items() if target.field in keys]
            return {"revision": matter.revision, "matter_context": context[:16],
                    "selected_path": matter.choices[-1].path if matter.choices and
                    matter.choices[-1].based_on_revision + 1 == matter.revision else None, "research": result}

        return execute(assemble)

    @routes.get("/{matter_id}/legal-theories")
    def legal_theories(request: Request, matter_id: UUID, revision: int = Query(ge=0, le=199)):
        config, path, _ = access(request, matter_id)

        def read():
            matter = service(config, path).read(matter_id, revision)
            report = ClaimService(repository, config).analyze(matter, AnalyzeClaim(revision=revision))
            return {key: report[key] for key in ("matter_revision", "jurisdiction", "status", "summary", "exact_authority")}

        return execute(read)

    @routes.post("/{matter_id}/claim-analysis", status_code=201)
    def analyze_claim(request: Request, matter_id: UUID, body: AnalyzeClaim):
        config, path, _ = access(request, matter_id)

        def apply():
            ledger = service(config, path)
            matter = ledger.read(matter_id, body.revision)
            verifier = (os.environ.get("PRO_ONE_CLAIM_VERIFIER_PROVIDER", ""),
                        os.environ.get("PRO_ONE_CLAIM_VERIFIER_MODEL", ""))
            engine = ClaimService(repository, config, generation.registry, verifier)
            return ClaimStore(ledger.store).save(matter, engine.analyze(matter, body))

        return execute(apply)

    @routes.get("/{matter_id}/claim-analysis/{analysis_id}")
    def read_claim(request: Request, matter_id: UUID, analysis_id: str):
        config, path, _ = access(request, matter_id)

        def read():
            if not re.fullmatch(r"[0-9a-f]{64}", analysis_id):
                raise MatterNotFound("claim_analysis_not_found")
            ledger = service(config, path)
            return ClaimStore(ledger.store).get(matter_id, analysis_id, ClaimService(repository, config))

        return execute(read)

    @routes.get("/{matter_id}/claim-analysis/{analysis_id}/questions")
    def claim_questions(request: Request, matter_id: UUID, analysis_id: str):
        analysis = read_claim(request, matter_id, analysis_id)
        return {key: analysis[key] for key in ("matter_revision", "latest_matter_revision", "freshness",
                                                "stale_reasons", "questions")}

    return routes
