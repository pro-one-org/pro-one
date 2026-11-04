"""Isolated, bounded official-source network and PDF parser worker."""

import json
import sys
from dataclasses import asdict


def main():
    if sys.platform != "win32":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    from app.authority import VirginiaOfficialProvider, BoundedAuthorityTransport
    from app.repository import RecordRepository
    try:
        document = VirginiaOfficialProvider(RecordRepository(), BoundedAuthorityTransport()).fetch(sys.argv[1])
        output = json.dumps(asdict(document)).encode("utf-8")
        if len(output) > 512000:
            return 1
        sys.stdout.buffer.write(output)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
