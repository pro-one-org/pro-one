"""Canonical political jurisdictions. Court location alone does not determine governing law."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1] / "data" / "national-coverage"


@dataclass(frozen=True)
class Jurisdiction:
    id: str
    name: str
    kind: str
    manifest: str


@lru_cache(maxsize=1)
def registry():
    rows = [Jurisdiction(**item) for item in json.loads((ROOT / "registry.json").read_bytes())]
    mapping = {row.id: row for row in rows}
    if len(mapping) != len(rows) or any(
        not re.fullmatch(r"US(?:-[A-Z]{2})?", row.id) or row.manifest != row.id + ".json"
        or row.kind not in {"federal", "state", "district", "territory"} for row in rows
    ):
        raise ValueError("invalid_national_registry")
    return MappingProxyType(mapping)


def jurisdiction_id(value):
    key = value.strip().upper()
    if key == registry()["US"].name.upper():
        return "US"
    candidate = key if key.startswith("US-") or key == "US" else "US-" + key
    return candidate if candidate in registry() else NAME_SCOPES.get(value.strip().casefold())


SUBNATIONAL_NAMES = {row.id[3:]: row.name for row in registry().values() if row.id != "US"}
STATE_NAMES = {row.id[3:]: row.name for row in registry().values() if row.kind in {"state", "district"}}
NAME_SCOPES = {name.casefold(): "US-" + code for code, name in SUBNATIONAL_NAMES.items()}
NAME_SCOPES.update({"d.c.": "US-DC", "washington, d.c.": "US-DC", "washington dc": "US-DC",
                    "washington, dc": "US-DC", "district of columbia": "US-DC"})
NAME_PATTERN = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, sorted(NAME_SCOPES, key=len, reverse=True))) + r")(?!\w)", re.I)


CONNECTION_FIELDS = frozenset({
    "residence_jurisdiction", "incident_jurisdiction", "work_jurisdiction", "employer_jurisdiction",
    "property_jurisdiction", "contract_formation_jurisdiction", "contract_performance_jurisdiction",
    "defendant_jurisdiction", "filing_jurisdiction", "agency_jurisdiction",
})


def possible_tribal_scope(message):
    return any(row["name"].casefold() in message.casefold() for row in tribal_registry().values()) or bool(
        re.search(r"\b(?:tribal (?:court|land|law|nation|jurisdiction)|Indian (?:country|reservation)|on (?:a|the) reservation)\b", message, re.I))


@lru_cache(maxsize=1)
def tribal_registry():
    rows = json.loads((ROOT / "tribal-jurisdictions.json").read_bytes())
    return MappingProxyType({row["id"]: row for row in rows})
