"""Replay the bounded, reviewed amendment pairing for 8 CFR 100.4(a)."""

from datetime import date

from app.national_corpus import CorpusError, fingerprint
from app.national_corpus_providers import PROVIDERS


EFFECTIVE = date(2026, 3, 2)
BASIS = ("FR Doc. 2026-01868 adds the Detroit Gordie Howe International Bridge entry to "
         "8 CFR 100.4(a), effective 2026-03-02. The entry is absent from the 2025 annual edition "
         "and appears in the retained eCFR rendition. Subsequent section currentness remains unresolved.")
ARTIFACTS = (
    ("govinfo_cfr", "2025/8/1/100.4", "a26419cdb13efc6a533ee1c0e373ead60f27f462c6d62237823962a3ad858ff3", "8 CFR 100.4"),
    ("govinfo_ecfr", "8", "0b36bdcddc16ecfbbbbaae69a5b2fff81ef64f7b4c08d1af19a668f4ea3a92aa", "8 CFR 100.4"),
    ("govinfo_register", "2026-01-30", "c45bbcf00e1e314b5be86c45431da58244e4dcc95d973d0fc4dab3a4271cad07", "FR Doc. 2026-01868"),
)


def reviewed_supersession(store):
    observations = []
    proof = {}
    for role, (name, selector, content_hash, citation) in zip(("earlier", "later", "rule"), ARTIFACTS):
        provider = PROVIDERS[name]
        raw = store.snapshot_bytes(content_hash)
        if raw is None or fingerprint(raw) != content_hash:
            raise CorpusError("supersession_artifact_unavailable")
        matches = [obs for obs in provider.normalize(selector, raw) if obs.version.citation == citation]
        if len(matches) != 1:
            raise CorpusError("supersession_identity_unverified")
        obs = matches[0]
        sources = [source for source in store.provenance(obs.version.version_id)
                   if source["provider"] == name and source["hash"] == content_hash
                   and source["selector"] == selector and source["native_id"] == obs.native_id
                   and source["parser_revision"] == provider.source.parser_revision
                   and source["url"] == provider.source_url(selector)
                   and source["locator"] == obs.locator and source["original_citation"] == obs.original_citation]
        if len(sources) != 1:
            raise CorpusError("supersession_provenance_unverified")
        observations.append(obs)
        proof.update({f"{role}_snapshot": sources[0]["id"], f"{role}_native": obs.native_id,
                      f"{role}_version": obs.version.version_id})
    earlier, later, rule = observations
    entry = "Gordie Howe International Bridge"
    if (earlier.version.authority_id != later.version.authority_id
            or earlier.version.currentness != "historical" or later.version.currentness != "unresolved"
            or entry in earlier.version.text or entry not in later.version.text
            or rule.version.document_kind != "final_rule" or rule.version.effective_from != EFFECTIVE
            or not any(edge.kind == "amends_cfr" and edge.target_native_id == earlier.version.citation
                       for edge in rule.relationships)):
        raise CorpusError("supersession_evidence_unverified")
    return {**proof, "effective_on": EFFECTIVE.isoformat(), "basis": BASIS}


def record_reviewed_supersession(store):
    proof = reviewed_supersession(store)
    fields = ("earlier_snapshot", "earlier_native", "later_snapshot", "later_native",
              "rule_snapshot", "rule_native", "effective_on", "basis")
    db = store.connection
    with db:
        db.execute("INSERT OR IGNORE INTO corpus_supersessions VALUES(?,?,?,?,?,?,?,?)",
                   tuple(proof[field] for field in fields))
        if store.supersession(proof["earlier_version"], EFFECTIVE) != proof:
            raise CorpusError("supersession_conflict")
    return proof
