"""In-memory, bounded text extraction. No paths, macros, network or OCR."""
from io import BytesIO
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET

MAX_FILE = 2 * 1024 * 1024
MAX_TEXT = 16000


def isolated_extract(data, content_type):
    """A timed child process isolates parser failures from the ASGI worker."""
    import json
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-B", "-m", "app.documents", content_type],
                            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=8, check=False)
    if result.returncode or len(result.stdout) > 128000:
        raise ValueError("This document could not be read safely. Try a shorter redacted TXT copy.")
    response = json.loads(result.stdout)
    if "error" in response:
        raise ValueError(response["error"])
    return response


def extract_document(data: bytes, content_type: str):
    if not data or len(data) > MAX_FILE:
        raise ValueError("Use a nonempty document smaller than 2 MB.")
    pages = None
    if content_type == "text/plain":
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("This file is not readable text.")
    elif content_type == "application/pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("This file is not a PDF.")
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 20:
            raise ValueError("Use an unlocked PDF with at most 20 pages.")
        pages = len(reader.pages)
        text = ""
        for page in reader.pages:
            if len(text) > MAX_TEXT:
                break
            text += (page.extract_text() or "") + "\n"
    elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        with ZipFile(BytesIO(data)) as archive:
            items = archive.infolist()
            if len(items) > 200 or sum(i.file_size for i in items) > 8 * MAX_FILE:
                raise ValueError("This document is too complex. Export a shorter text copy.")
            if any("vbaproject" in i.filename.casefold() for i in items):
                raise ValueError("Macro documents are not supported.")
            raw = archive.read("word/document.xml")
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("This document contains unsupported XML.")
            root = ET.fromstring(raw)
            text = "\n".join(n.text or "" for n in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
    else:
        raise ValueError("Use a text-readable PDF, DOCX, or UTF-8 TXT file.")
    if not text.strip():
        raise ValueError("No readable text was found. Scanned or image-only documents need OCR, which is not supported yet.")
    if len(text) > MAX_TEXT:
        raise ValueError("This document is too long. Upload a shorter redacted excerpt (up to 16,000 characters).")
    if re.search(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b|\b\d{12,19}\b", text):
        raise ValueError("Remove Social Security and account numbers before uploading again.")
    return {"text": text, "pages": pages, "characters": len(text), "warnings": ["Check extracted text against your original. Layout and dates may be misread."], "persisted": False}


if __name__ == "__main__":
    import json
    import sys
    if sys.platform != "win32":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    try:
        response = extract_document(sys.stdin.buffer.read(MAX_FILE + 1), sys.argv[1])
    except Exception:
        response = {"error": "This document could not be read safely. Use a short, redacted, text-readable PDF, DOCX or TXT copy. Scanned documents are not supported."}
    sys.stdout.buffer.write(json.dumps(response).encode("utf-8"))
