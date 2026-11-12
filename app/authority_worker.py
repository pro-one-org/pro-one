"""Isolated, bounded official-source network and PDF parser worker."""

import json
import sys
from dataclasses import asdict


def main():
    if sys.platform != "win32":
        import resource
        rule_source = len(sys.argv) > 1 and sys.argv[1] == "va-rule-3-20"
        memory = (512 if rule_source else 256) * 1024 * 1024
        cpu = 10 if rule_source else 5
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
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
