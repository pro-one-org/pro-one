"""Official Federal Register and United States Reports adapters."""

from datetime import date, datetime
from io import BytesIO
import re

from app.authority import normalized_source
from app.national_corpus import AuthorityVersion, CorpusError, Observation, Source, SourceRelationship, fingerprint
from app.national_corpus_transport import PublicProvider, text_of, xml_root


class FederalRegisterProvider(PublicProvider):
    source = Source(
        name="govinfo_register", host="www.govinfo.gov", authority_type="register_document", jurisdictions=("US",),
        official_publisher=True, rendition="Office of the Federal Register daily issue XML via GovInfo",
        endpoint="/bulkdata/FR/{year}/{month}/FR-{date}.xml",
        format="bounded XML issue, indexed preambles", update="explicit daily issue",
        rights="Federal Register government text. Exact XML remains in local audit storage.",
        attribution="Office of the Federal Register and U.S. Government Publishing Office",
        currentness_method="Uses issue date, XML classification and explicit effective-date wording where recognized.",
        parser_revision="3",
    )
    kinds = {"RULE": "other", "PRORULE": "proposed_rule", "NOTICE": "notice", "PRESDOC": "other"}

    def _selection(self, selector):
        try:
            if re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", selector):
                return date.fromisoformat(selector)
        except ValueError:
            pass
        raise CorpusError("invalid_register_issue_selector")

    def source_url(self, selector):
        issue = self._selection(selector)
        path = self.source.endpoint.format(year=issue.year, month=f"{issue.month:02d}", date=selector)
        return f"https://{self.source.host}{path}"

    def normalize(self, selector, raw):
        issue = self._selection(selector)
        root = xml_root(raw)
        dates = {text_of(node).partition(", ")[2] for node in root.findall("DATE")}
        expected = f"{issue:%B} {issue.day}, {issue.year}"
        volumes = {text_of(node) for node in root.findall("VOL")}
        if root.tag != "FEDREG" or dates != {expected} or len(volumes) != 1:
            raise CorpusError("source_edition_identity_mismatch")
        volume = next(iter(volumes))
        if not re.fullmatch(r"[1-9][0-9]{0,3}", volume):
            raise CorpusError("source_edition_identity_mismatch")
        index = {}
        for entry in root.findall("./CNTNTS//DOCENT"):
            native = text_of(entry.find("FRDOCBP"))
            page = re.match(r"([1-9][0-9]*)\b", text_of(entry.find("PGS")))
            if native and page:
                index.setdefault(native, set()).add(page[1])
        for node in root.iter():
            if node.tag in self.kinds:
                yield self._document(node, issue, volume, index)

    def _document(self, node, issue, volume, index):
        native_match = re.match(r"\[FR Doc\. (\d{4}-\d{5})\b", text_of(node.find("FRDOC")))
        preamble = node.find("PREAMB")
        if not native_match or preamble is None:
            raise CorpusError("source_register_document_identity_mismatch")
        native = native_match[1]
        title = text_of(preamble.find("SUBJECT"))
        if not title:
            raise CorpusError("source_register_title_missing")
        action = text_of(preamble.find("ACT")).removeprefix("ACTION:").strip().casefold()
        kind = self.kinds[node.tag]
        if node.tag == "RULE" and action.rstrip(".") in {"final rule", "direct final rule", "interim final rule"}:
            kind = "final_rule"
        effective = None
        date_text = text_of(preamble.find("EFFDATE")).removeprefix("DATES:").strip()
        match = re.fullmatch(
            r"(?:This (?:final )?rule is effective|Effective) ([A-Z][a-z]+ \d{1,2}, \d{4})\.", date_text,
        )
        if kind == "final_rule" and match:
            effective = datetime.strptime(match[1], "%B %d, %Y").date()
        agency = text_of(preamble.find("SUBAGY")) or text_of(preamble.find("AGENCY"))
        citation = f"FR Doc. {native}"
        pages = index.get(native, set())
        alternate = (f"{volume} FR {next(iter(pages))}",) if len(pages) == 1 else ()
        version = AuthorityVersion(
            jurisdiction="US", sovereign="federal", authority_type="register_document",
            identity_namespace="federal_register", identity_key=native, citation=citation,
            alternate_citations=alternate, title=title, edition=issue.isoformat(),
            text="\n".join(filter(None, (text_of(element) for element in preamble))),
            hierarchy=(f"Federal Register vol. {volume}", issue.isoformat()),
            currentness="proposed" if kind == "proposed_rule" else "unresolved",
            document_kind=kind, published_on=issue, effective_from=effective, agency=agency or None,
            limitations=("Indexed preamble. Full published document is retained in the source XML.",
                         "CFR references identify the parts listed in the preamble. Subsequent changes remain unresolved."),
        )
        targets = dict.fromkeys(
            f"{match[1]} CFR part {match[2]}" for ref in preamble.findall("CFR")
            if (match := re.fullmatch(r"([1-9][0-9]?) CFR Part ([0-9]+[a-zA-Z]?)", text_of(ref)))
        )
        edges = tuple(SourceRelationship("references_cfr", target) for target in targets)
        if kind == "final_rule":
            edges += self._amendments(node, targets)
        return Observation(version, native, f"{node.tag} / FRDOC {native} / PREAMB", text_of(node.find("FRDOC")), edges)

    def _amendments(self, node, parts):
        if len(parts) != 1:
            return ()
        edges = []
        for part in parts:
            title, _, _, part_number = part.split()
            for instruction in node.findall(".//REGTEXT/AMDPAR"):
                text = text_of(instruction)
                match = re.search(r"§\s*([0-9]+[a-zA-Z]?\.[0-9]+[a-zA-Z0-9-]*)\b", text)
                if (match and match[1].split(".")[0] == part_number
                        and re.search(r"\b(add|revise|remove|amend|redesignate|correct)\b", text, re.I)):
                    edges.append(SourceRelationship("amends_cfr", f"{title} CFR {match[1]}"))
        return tuple(dict.fromkeys(edges))


class USReportsProvider(PublicProvider):
    """Pinned granule whose title, case date and edition were checked against GovInfo."""

    source = Source(
        name="us_reports", host="www.govinfo.gov", authority_type="opinion", jurisdictions=("US",),
        official_publisher=True, rendition="Supreme Court United States Reports via GovInfo",
        endpoint="/content/pkg/USREPORTS-347/pdf/USREPORTS-347-483.pdf", format="checked granule PDF",
        update="review and pin a specific granule", rights="Judicial publication, including editorial reporter material.",
        attribution="Supreme Court of the United States and U.S. Government Publishing Office",
        currentness_method="Pinned official report identifies the case and edition. Treatment remains unresolved.",
        parser_revision="1", max_bytes=2 * 1024 * 1024,
    )
    raw_hash = "a638465fcfd46d5e3e968bf1e887a2a374f8fc9bf0d8cffc881d4fab7cd04eec"

    def source_url(self, selector):
        if selector != "347-483":
            raise CorpusError("invalid_us_reports_selector")
        return f"https://{self.source.host}{self.source.endpoint}"

    def normalize(self, selector, raw):
        self.source_url(selector)
        if fingerprint(raw) != self.raw_hash:
            raise CorpusError("us_reports_snapshot_unreviewed")
        from pypdf import PdfReader
        pages = PdfReader(BytesIO(raw)).pages
        if len(pages) != 14:
            raise CorpusError("us_reports_page_count_mismatch")
        text = "\n".join(normalized_source(page.extract_text()) for page in pages)
        if not text.startswith("BROWN v. BOARD OF EDUCATION. 483"):
            raise CorpusError("us_reports_case_identity_mismatch")
        version = AuthorityVersion(
            jurisdiction="US", sovereign="federal", authority_type="opinion",
            identity_namespace="us_reports_granule", identity_key=selector,
            title="Brown v. Board of Education", citation="347 U.S. 483", edition="U.S. Reports volume 347",
            text=text, hierarchy=("U.S. Reports volume 347",), court="Supreme Court of the United States",
            opinion_role="mixed", published_on=date(1954, 5, 17),
            limitations=("Reporter granule includes syllabus, counsel and judicial text. Extraction may contain OCR defects.",
                         "Role and subsequent treatment require independent review."),
        )
        yield Observation(version, "USREPORTS-347-483", "PDF pages 1–14", "347 U.S. 483 (1954)")
