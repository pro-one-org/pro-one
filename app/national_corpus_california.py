"""Replayable California Civil Code sample from pinned official ZIP ranges."""

from base64 import b64decode, b64encode
from datetime import date
import json
import re
import struct
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
import zlib

from app.corpus_store import encode
from app.models.http_transport import NoRedirect
from app.national_corpus import AuthorityVersion, CorpusError, FetchedSource, Observation, Source, SourceRelationship, fingerprint
from app.national_corpus_transport import xml_root


ARCHIVE = "https://downloads.leginfo.legislature.ca.gov/pubinfo_2025.zip"
ETAG = '"4d06247b-65fd132c77540"'
LAST_MODIFIED = "Mon, 09 Nov 2026 05:26:05 GMT"
ARCHIVE_SIZE = 1_292_248_187
# Reviewed central-directory values for this archive. The local member headers
# and CRCs must agree before the compressed ranges become a source artifact.
MEMBERS = {
    "LAW_SECTION_TBL.dat": (10_838_907, 6_058_749, 43_307_757, 1211681546),
    "LAW_SECTION_TBL_24509.lob": (350_068_925, 2033, 6295, 4154510936),
    "LAW_SECTION_TBL_33783.lob": (130_317_069, 772, 1695, 2544740953),
}
SECTIONS = {"1941.1.": "LAW_SECTION_TBL_24509.lob", "1942.": "LAW_SECTION_TBL_33783.lob"}
RANGE_ENDS = (16_898_655, 350_071_469, 130_318_352)
MEMBER_HASHES = {
    "LAW_SECTION_TBL.dat": "d266e37c095bcc4f4d67e944edac7ac0fae6bf2e90a6d057351fa707a066b4df",
    "LAW_SECTION_TBL_24509.lob": "8b86cf55f3950670b6c41a2bac55e8cfa1655763399805d454c0c3371b2e8a70",
    "LAW_SECTION_TBL_33783.lob": "6f6e64c028aeaa9533dc7838aa12f1a21140afea8095dd0961482b02873cfa7e",
}
LOCAL_HEADER = struct.Struct("<4s5H3L2H")


def compressed_member(raw, name):
    _, compressed, size, crc = MEMBERS[name]
    if len(raw) < LOCAL_HEADER.size:
        raise CorpusError("california_zip_header_invalid")
    signature, _, flags, method, _, _, stored_crc, stored_compressed, stored_size, namesize, extra = LOCAL_HEADER.unpack_from(raw)
    start = LOCAL_HEADER.size + namesize + extra
    if (signature != b"PK\x03\x04" or flags != 0 or method != 8
            or (stored_crc, stored_compressed, stored_size) != (crc, compressed, size)
            or raw[LOCAL_HEADER.size:LOCAL_HEADER.size + namesize] != name.encode("ascii")
            or start + compressed > len(raw)):
        raise CorpusError("california_zip_header_invalid")
    return raw[start:start + compressed]


def inflate_member(data, name):
    _, compressed, expected_size, expected_crc = MEMBERS[name]
    if len(data) != compressed or fingerprint(data) != MEMBER_HASHES[name]:
        raise CorpusError("california_zip_member_identity_invalid")
    inflater = zlib.decompressobj(-15)
    total = crc = 0
    try:
        for offset in range(0, len(data), 65536):
            pending = data[offset:offset + 65536]
            while pending:
                chunk = inflater.decompress(pending, 65536)
                pending = inflater.unconsumed_tail
                total += len(chunk)
                crc = zlib.crc32(chunk, crc)
                if total > expected_size:
                    raise CorpusError("california_zip_size_invalid")
                yield chunk
    except zlib.error:
        raise CorpusError("california_zip_stream_invalid") from None
    if not inflater.eof or inflater.unused_data or (total, crc) != (expected_size, expected_crc):
        raise CorpusError("california_zip_integrity_invalid")


def section_rows(data):
    rows = {}
    incomplete = b""
    for chunk in inflate_member(data, "LAW_SECTION_TBL.dat"):
        lines = (incomplete + chunk).split(b"\n")
        incomplete = lines.pop()
        if len(incomplete) > 16384:
            raise CorpusError("california_zip_row_limit")
        for raw in lines:
            fields = raw.rstrip(b"\r").split(b"\t")
            if len(fields) != 18 or fields[1] != b"`CIV`":
                continue
            section = fields[2].decode("ascii", "replace").strip("`")
            if section not in SECTIONS or fields[14].decode("ascii", "replace") != SECTIONS[section]:
                continue
            if section in rows:
                raise CorpusError("california_zip_duplicate_section")
            rows[section] = [field.decode("utf-8").strip("`") for field in fields]
    if incomplete or set(rows) != set(SECTIONS):
        raise CorpusError("california_zip_missing_section")
    return rows


class CaliforniaCivilCode:
    source = Source(
        name="california_code", host="downloads.leginfo.legislature.ca.gov", authority_type="statute",
        jurisdictions=("US-CA",), official_publisher=True, rendition="California Legislative Counsel PUBINFO law tables",
        endpoint="/pubinfo_2025.zip", format="bounded compressed table and text members in a replay envelope",
        update="pin a reviewed archive edition and member inventory", attribution="California Legislative Counsel",
        rights="California statutory text from the Legislature's public distribution. Other archive members are excluded.",
        currentness_method="Uses the pinned archive publication date and the official active_flg field. Later changes unresolved.",
        parser_revision="2", max_bytes=9 * 1024 * 1024, max_requests=len(MEMBERS),
    )

    def source_url(self, selector):
        if selector != "2025/civil-habitability":
            raise CorpusError("invalid_california_archive_selector")
        return ARCHIVE

    def fetch(self, selector):
        url = self.source_url(selector)
        opener = build_opener(ProxyHandler({}), NoRedirect())
        artifacts = {}
        for (name, (start, _, _, _)), end in zip(MEMBERS.items(), RANGE_ENDS, strict=True):
            requested = f"bytes={start}-{end}"
            request = Request(url, headers={"Range": requested, "If-Match": ETAG, "Accept-Encoding": "identity",
                                            "User-Agent": "Pro-One legal corpus ingestion/1.0"})
            try:
                with opener.open(request, timeout=15) as response:
                    if (response.status != 206 or response.geturl() != url or response.headers.get("ETag") != ETAG
                            or response.headers.get("Last-Modified") != LAST_MODIFIED
                            or response.headers.get("Content-Range") != f"bytes {start}-{end}/{ARCHIVE_SIZE}"
                            or response.headers.get("Content-Encoding", "identity") != "identity"):
                        raise CorpusError("california_archive_range_mismatch")
                    limit = end - start + 1
                    raw = response.read(limit + 1)
            except HTTPError as exc:
                status = exc.code
                exc.close()
                raise CorpusError(f"california_archive_http_{status}") from None
            except (URLError, OSError):
                raise CorpusError("california_archive_unavailable") from None
            if len(raw) != limit:
                raise CorpusError("california_archive_range_size")
            artifacts[name] = b64encode(compressed_member(raw, name)).decode("ascii")
        return FetchedSource(encode({"etag": ETAG, "last_modified": LAST_MODIFIED, "members": artifacts}).encode(), len(artifacts))

    def normalize(self, selector, raw):
        self.source_url(selector)
        try:
            envelope = json.loads(raw)
            members = envelope["members"]
            if envelope["etag"] != ETAG or envelope["last_modified"] != LAST_MODIFIED or set(members) != set(MEMBERS):
                raise ValueError()
            blobs = {name: b64decode(value, validate=True) for name, value in members.items()}
            rows = section_rows(blobs["LAW_SECTION_TBL.dat"])
        except (KeyError, TypeError, UnicodeError, ValueError):
            raise CorpusError("california_archive_replay_invalid") from None
        for section, row in rows.items():
            native, _, _, session, chapter, _, effective, *_ = row
            hierarchy = ("Civil Code", "Division 3", "Part 4", "Title 5", "Chapter 2")
            tree = xml_root(b"".join(inflate_member(blobs[SECTIONS[section]], SECTIONS[section])))
            if tree.tag != "{http://lc.ca.gov/legalservices/schemas/caml.1#}Content" or any(p.tag != "p" for p in tree):
                raise CorpusError("california_archive_text_scope")
            body = []
            for paragraph in tree:
                # CAML's empty EnSpace span is a word boundary.
                text = (paragraph.text or "") + "".join(
                    (" " if node.get("class") == "EnSpace" else "".join(node.itertext())) + (node.tail or "")
                    for node in paragraph
                )
                body.append(" ".join(text.split()))
            number = section.removesuffix(".")
            citation = f"Cal. Civ. Code § {number}"
            history = row[13]
            if row[15] != "Y":
                raise CorpusError("california_archive_section_inactive")
            explicit = date.fromisoformat(effective[:10]) if re.fullmatch(r"\d{4}-\d{2}-\d{2} 00:00:00", effective) else None
            version = AuthorityVersion(
                jurisdiction="US-CA", sovereign="state", authority_type="statute",
                identity_namespace="cal_civil_code", identity_key=number, title=citation, citation=citation,
                edition=f"Stats. {session}, ch. {chapter}", text="\n".join(body), hierarchy=hierarchy,
                legislature="California Legislature", effective_from=explicit,
                currentness="current", current_as_of=date(2026, 11, 9),
                currentness_basis="California Legislative Counsel PUBINFO archive 2026-11-09, LAW_SECTION_TBL.active_flg=Y.",
                limitations=(history, "Pinned Legislature archive. Subsequent changes remain unresolved."),
            )
            yield Observation(version, native, f"LAW_SECTION_TBL.dat / {native} / {SECTIONS[section]}", citation,
                              (SourceRelationship("part_of", "Civil Code / Division 3 / Part 4 / Title 5 / Chapter 2"),))
