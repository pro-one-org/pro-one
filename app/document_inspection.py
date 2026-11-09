"""Explain document cues without treating uploaded content as legal evidence."""

import re


# These are heading cues. The upload cannot establish who issued or signed it.
DOCUMENT_HEADINGS = (
    (r"(?:proposed|draft) (?:final )?order", "Possible draft order",
     "The heading suggests a draft or proposed order. Its signature and entry status are unverified."),
    (r"(?:final )?order(?: granting| denying| of| to)?", "Possible order",
     "The heading suggests an order. Its authenticity, signature, entry and applicability are unverified."),
    (r"(?:amended )?complaint", "Possible complaint",
     "A complaint states a party's allegations and requests. The upload does not establish findings."),
    (r"motion(?: for| to)?", "Possible motion",
     "A motion asks the court to act. The upload does not establish how the court ruled."),
    (r"(?:opening |reply )?brief|memorandum in (?:support|opposition)", "Possible brief",
     "A brief presents a party's arguments. Its statements remain advocacy and its citations require verification."),
    (r"(?:civil )?summons", "Possible summons",
     "A summons may contain instructions or dates. The excerpt does not verify service or calculate a deadline."),
    (r"(?:lease |purchase |employment |settlement )?agreement|contract", "Possible agreement",
     "The text may describe proposed or signed terms. Its execution, enforceability and applicability are unverified."),
    (r"demand(?: letter)?", "Possible demand",
     "A demand states the sender's position or request. The upload does not establish an obligation."),
)


def inspect_document_question(message, document):
    if not document or not re.search(r"\b(?:explain|summari[sz]e|what)\b", message, re.I):
        return None
    if not re.search(r"\b(?:this|it|upload|document|order|complaint|motion|brief|summons|agreement|contract|demand)\b",
                     message, re.I):
        return None
    if re.search(r"\bdc[- ]?402\b|\bmaryland\b.{0,80}\bsummons\b|\bscc\b", document, re.I):
        return None  # Keep supported procedural intake available.

    lines = [line.strip() for line in document.splitlines() if line.strip()]
    for index, line in enumerate(lines[:12]):
        for pattern, heading, limitation in DOCUMENT_HEADINGS:
            if not re.match(r"^(?:" + pattern + r")(?:\b|$)", line, re.I):
                continue
            sections = [{"heading": heading, "text": limitation, "citation_numbers": [], "user_provided": False}]
            excerpt = next((item for item in lines[index + 1:] if len(item) >= 20), "")
            if heading == "Possible order":
                excerpt = next((item for item in lines[index + 1:] if re.search(r"\bordered\b", item, re.I)), excerpt)
            if excerpt:
                sections.append({"heading": "Excerpt from your upload" + (" (truncated)" if len(excerpt) > 600 else ""),
                                 "text": excerpt[:600] + ("…" if len(excerpt) > 600 else ""),
                                 "citation_numbers": [], "user_provided": True})
            return {"sections": sections, "sources": [], "notices": [], "warnings": [],
                    "limitations": [limitation], "publicly_approved": False, "status_label": "Document inspection"}
    return None
