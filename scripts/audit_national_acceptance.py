"""Print the jurisdiction evidence inventory for open national acceptance criteria."""
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.jurisdictions import registry
from app.national_coverage import OFFICIAL_FORM_REQUIREMENTS, manifest


STATUS = {"current_as_of": "D", "unresolved": "U", "historical": "H"}


def status(categories, *names):
    marks = {STATUS[row["currentness"]] for name in names for row in categories[name]}
    return "/".join(mark for mark in STATUS.values() if mark in marks) or "—"


def inventory(scope):
    record = manifest(scope)
    categories = defaultdict(list)
    for row in record["passages"].values():
        categories[record["sources"][row["source_id"]]["category"]].append(row)

    formation = categories["contract_formation"]
    # This flag lists ordinary-formation candidates. Opinion scope still needs review.
    ordinary = any(row["authority_type"] in {"opinion", "court_instruction"} for row in formation)
    ordinary = ordinary or scope in {"US-CA", "US-LA"}

    fault = record.get("fault_allocation")
    bound_fault = STATUS[fault["currentness"]] if fault else "—"
    accrual = status(categories, "accrual")
    if scope == "US-WA" and accrual != "—":
        accrual += " (property)"
    forms = ", ".join(sorted(
        form["publisher_identifier"] for form in record.get("forms", {}).values()
        if form["mandatory"] in OFFICIAL_FORM_REQUIREMENTS
    )) or "—"
    return (
        scope[3:],
        status(categories, "negligence_elements"),
        status(categories, "premises"),
        bound_fault,
        status(categories, "pi_limitations"),
        accrual,
        status(categories, "tolling"),
        "candidate" if ordinary else "sales",
        status(categories, "contract_breach"),
        status(categories, "general_contract_damages"),
        status(categories, "written_contract_limitations", "oral_contract_limitations",
               "general_contract_limitations"),
        status(categories, "contract_accrual"),
        forms,
    )


def main():
    headers = (
        "Scope", "14 elements", "14 premises", "15 regime", "16 period", "16 accrual",
        "16 tolling", "17 formation", "17 breach", "17 ordinary damages",
        "18 period", "18 accrual", "39 scoped forms",
    )
    for row in (headers, ("---",) * len(headers)):
        print("| " + " | ".join(row) + " |")
    for scope, jurisdiction in sorted(registry().items()):
        if jurisdiction.kind in {"state", "district"}:
            print("| " + " | ".join(inventory(scope)) + " |")


if __name__ == "__main__":
    main()
