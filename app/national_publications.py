"""Normalize pinned legislative excerpts using the existing national corpus contract."""
from datetime import date
from urllib.parse import urlsplit

from app.jurisdictions import registry
from app.national_certifications import certified_basis
from app.national_corpus import AuthorityVersion, CorpusError, Observation, Source, fingerprint
from app.national_coverage import manifest


class LegislativeExcerpts:
    """Replays a retained excerpt, independently identifying its original publisher capture.

    A changed publisher page requires a new observation and a new checked selector.
    It cannot update the legal status or modify an older snapshot.
    """
    def __init__(self, jurisdiction, authority_type="statute"):
        self.jurisdiction = jurisdiction
        record = manifest(jurisdiction)
        hosts = sorted({urlsplit(record["sources"][p["source_id"]]["url"]).hostname
                        for p in record.get("passages", {}).values() if p["authority_type"] == authority_type})
        prefix = "legislative_excerpts_" if authority_type == "statute" else "court_rule_excerpts_"
        self.source = Source(
            name=prefix + jurisdiction.lower().replace("-", "_"),
            host=", ".join(hosts), authority_type=authority_type, jurisdictions=(jurisdiction,),
            official_publisher=True, rendition="Retained excerpt of an official publication",
            endpoint="catalogued publisher URL", format="UTF-8 text excerpt",
            update="add reviewed selectors", rights="Bounded official text excerpts only.",
            attribution="Publisher identified in the scoped manifest",
            currentness_method="Capture dates identify observations. Operative status requires independent evidence.",
            parser_revision="1", max_bytes=32000, refresh_supported=False,
            refresh_limitation="Check the original publisher snapshot and later amendments before relying on this excerpt.",
        )

    def publication(self, selector):
        record = manifest(self.jurisdiction)
        try:
            row = record.get("passages", {})[selector]
            source = record["sources"][row["source_id"]]
        except KeyError:
            raise CorpusError("unsupported_authority") from None
        if (not source["url"].startswith("https://") or row["authority_type"] != self.source.authority_type
                or row["currentness"] not in {"unresolved", "historical", "current_as_of"}):
            raise CorpusError("invalid_legislative_publication")
        return row, source

    def source_url(self, selector):
        return self.publication(selector)[1]["url"]

    def fetch(self, selector):
        raise CorpusError("retained_snapshot_required")

    def normalize(self, selector, raw):
        row, source = self.publication(selector)
        if raw != row["text"].encode("utf-8") or fingerprint(raw) != row["text_sha256"]:
            raise CorpusError("retained_excerpt_hash_mismatch")
        citation = row["citation"]
        owner = registry()[self.jurisdiction]
        retrieved = date.fromisoformat(row["retrieved_at"][:10])
        publisher = urlsplit(source["url"]).hostname
        day, basis = (certified_basis(owner.id, source["url"], row["publisher_sha256"], row["publisher_path"], citation, row["text"])
                      if row["currentness"] == "current_as_of" else (None, None))
        version = AuthorityVersion(
            jurisdiction=owner.id, sovereign=owner.kind, authority_type=self.source.authority_type,
            identity_namespace="legislative_publication" if self.source.authority_type == "statute" else "judicial_publication",
            identity_key=citation,
            title=citation, citation=citation,
            edition=row.get("edition", f"publisher capture {retrieved.isoformat()}"),
            effective_from=date.fromisoformat(row["effective_from"]) if row.get("effective_from") else None,
            text=row["text"], legislature=publisher if self.source.authority_type == "statute" else None,
            court=row.get("court"), currentness=row["currentness"],
            current_as_of=day, currentness_basis=basis,
            limitations=("Bounded excerpt. Classification, exceptions, later amendments and application require review.",),
        )
        member = row.get("publisher_member")
        location = f"{citation}; archive member {member}" if member else citation
        hash_scope = "publisher member" if row.get("publisher_archive_etag") else "original publisher"
        yield Observation(version, selector, f"{location}; {hash_scope} SHA-256 {row['publisher_sha256']}",
                          citation)


def providers():
    return tuple(LegislativeExcerpts(scope, kind) for scope in registry()
                 for kind in sorted({p["authority_type"] for p in manifest(scope).get("passages", {}).values()}))
