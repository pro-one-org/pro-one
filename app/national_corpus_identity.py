"""Explain cross-source identity without coalescing provider representations."""

from app.national_corpus_federal import USReportsProvider


BROWN_DERIVATIVE_HASH = "959b1191a895c3995b76e1fb53f3bc07e265e6f8e7aa425aa7aa00de1a021cbf"


def compare_identity(left, right, left_source, right_source):
    if any(left[field] != right[field] for field in ("jurisdiction", "authority_type")):
        return "conflicting_identity", "incompatible_jurisdiction_or_authority_type"
    if left["authority_id"] == right["authority_id"]:
        if left["edition"] == right["edition"] and left["normalized_hash"] == right["normalized_hash"]:
            return "same_authority_same_version", "same_checked_identity_edition_and_text"
        return "same_authority_different_version", "same_checked_identity_with_different_edition_or_text"

    observations = {left_source["provider"]: (left, left_source), right_source["provider"]: (right, right_source)}
    if set(observations) == {"us_reports", "courtlistener"}:
        official, official_source = observations["us_reports"]
        reproduction, reproduction_source = observations["courtlistener"]
        if (official_source["native_id"] == "USREPORTS-347-483"
                and official_source["hash"] == USReportsProvider.raw_hash
                and reproduction_source["native_id"] == "opinions/105221/"
                and reproduction["normalized_hash"] == BROWN_DERIVATIVE_HASH
                and all(official[field] == reproduction[field] for field in ("court", "citation", "published_on"))
                and official["citation"] == "347 U.S. 483"):
            return "derivative_representation", "checked_us_reports_granule_and_courtlistener_cluster"

    citations = lambda record: {" ".join(value.casefold().split()) for value in (
        record["citation"], *record.get("alternate_citations", ()),
    )}
    if citations(left).isdisjoint(citations(right)):
        return "unresolved_identity", "no_shared_reported_citation"
    if any(left.get(key) and right.get(key) and left[key] != right[key] for key in ("court", "published_on")):
        return "conflicting_identity", "shared_citation_with_inconsistent_issuer_or_date"
    if left["title"].casefold() == right["title"].casefold():
        return "probable_match", "shared_citation_and_title_need_independent_evidence"
    return "unresolved_identity", "shared_citation_without_enough_identity_evidence"
