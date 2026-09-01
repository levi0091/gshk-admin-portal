"""What the profiles hold of NAR1 and NNC1, and what they do not.

    uv run python scripts/cr_form_disposition_report.py

Reads the generated contract and prints the reconciliation: how many CR fields
a profile column holds, how many are computed, how many belong to a filing
rather than a profile, and — the column that matters — how many CR wants that
nothing in the portal or Viewpoint can supply.

ASCII only on purpose: this console is cp1252 and a Chinese description or an
em-dash raises UnicodeEncodeError mid-report.
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.cr_forms import contract  # noqa: E402

ORDER = ("mapped", "derived", "form_instance", "unsourced")


def main() -> int:
    by_disposition = Counter(e[0] for e in contract.FIELDS.values())
    by_form = defaultdict(Counter)
    for (form, _), entry in contract.FIELDS.items():
        by_form[form][entry[0]] += 1

    total = sum(by_disposition.values())
    print(f"CR FORM CONTRACT - {total} fields\n")

    header = "  " + "".join(d.ljust(15) for d in ORDER)
    print(f"{'form':10}{header}")
    for form in sorted(by_form):
        row = "".join(str(by_form[form][d]).ljust(15) for d in ORDER)
        print(f"{form:10}  {row}")
    row = "".join(str(by_disposition[d]).ljust(15) for d in ORDER)
    print(f"{'ALL':10}  {row}\n")

    # Mandatory-and-unsourced is the sharp end: CR requires it and nobody has
    # it, so a filing needing that field cannot be assembled at all.
    blocking = sorted(
        f"{form} {path.rsplit('/', 1)[-1]:24} {entry[1]}"
        for (form, path), entry in contract.FIELDS.items()
        if entry[0] == "unsourced" and entry[2]
    )
    print(f"MANDATORY BUT UNSOURCED ({len(blocking)}) - cannot be filed at all:")
    for line in blocking or ["  (none)"]:
        print(f"  {line}")

    optional_gaps = sorted(
        {f"{path.rsplit('/', 1)[-1]:24} {entry[1]}"
         for (form, path), entry in contract.FIELDS.items()
         if entry[0] == "unsourced" and not entry[2]}
    )
    print(f"\nOPTIONAL AND UNSOURCED ({len(optional_gaps)} distinct):")
    for line in optional_gaps:
        print(f"  {line}")

    # Every profile column the two forms actually depend on.
    tables = Counter(
        entry[1].split(".")[0]
        for entry in contract.FIELDS.values() if entry[0] == "mapped"
    )
    print("\nPROFILE TABLES THE FORMS DEPEND ON:")
    for table, n in tables.most_common():
        print(f"  {table:32} {n} field(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
