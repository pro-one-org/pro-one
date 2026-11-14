"""Bounded HTTPS and safe XML parsing for official publisher adapters."""

from http.client import HTTPException
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from xml.etree import ElementTree as ET

from app.authority import normalized_source
from app.models.http_transport import NoRedirect
from app.national_corpus import CorpusError, FetchedSource


class SafeTree(ET.TreeBuilder):
    def doctype(self, name, public_id, system_id):
        raise CorpusError("source_xml_doctype_forbidden")


def xml_root(raw):
    try:
        return ET.fromstring(raw, parser=ET.XMLParser(target=SafeTree()))
    except ET.ParseError as exc:
        raise CorpusError("source_xml_invalid") from exc


def text_of(element):
    return normalized_source("".join(element.itertext())) if element is not None else ""


class PublicProvider:
    def fetch(self, selector):
        url = self.source_url(selector)
        deadline = monotonic() + 30
        opener = build_opener(ProxyHandler({}), NoRedirect())
        request = Request(url, headers={"User-Agent": "Pro-One legal corpus ingestion/1.0", "Accept-Encoding": "identity"})
        raw = bytearray()
        try:
            with opener.open(request, timeout=10) as response:
                if (response.geturl() != url or response.status != 200
                        or response.headers.get("Content-Encoding", "identity") != "identity"):
                    raise CorpusError("source_response_invalid")
                while True:
                    chunk = response.read1(min(65536, self.source.max_bytes + 1 - len(raw)))
                    raw.extend(chunk)
                    if len(raw) > self.source.max_bytes:
                        raise CorpusError("source_size_out_of_bounds")
                    if monotonic() > deadline:
                        raise CorpusError("source_download_deadline")
                    if not chunk:
                        return FetchedSource(bytes(raw), requests=1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise CorpusError(f"source_http_{status}") from None
        except (URLError, OSError, HTTPException):
            raise CorpusError("source_transport_error") from None
