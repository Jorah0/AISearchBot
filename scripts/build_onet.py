"""Build lodestar/data/onet.json.gz from the O*NET database text download (pass 23, blueprint section 5).

    python -I scripts/build_onet.py db_31_0_text.zip --version 31.0

The zip is the "Text" download of https://www.onetcenter.org/database.html (CC BY 4.0). Per occupation the output keeps
code, title, a short description, the Job Zone, alternate/job titles, related occupations (by Related Index), up to 5
Core tasks and up to 25 technology examples (Hot Technology first). Run it again for a new O*NET release: the version
is recorded in meta and every career suggestion names it."""
import argparse
import csv
import gzip
import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

CODE = "O*NET-SOC Code"
CREDIT = ("Source: O*NET {v} Database by the U.S. Department of Labor, Employment and Training Administration. "
          "Used under the CC BY 4.0 license.")
# logical file -> (accepted file names, {logical column: accepted header names}); 31.0 renamed a few, older names kept
FILES = {
    "occ": (("Occupation Data.txt",), {"title": ("Title",), "desc": ("Description",)}),
    "zones": (("Job Zones.txt",), {"zone": ("Job Zone",)}),
    "titles": (("Job Titles.txt", "Alternate Titles.txt"), {"title": ("Job Title", "Alternate Title")}),
    "related": (("Related Occupations.txt",), {"code": ("Related O*NET-SOC Code",), "index": ("Index", "Related Index")}),
    "tasks": (("Task Statements.txt",), {"task": ("Task",), "type": ("Task Type",)}),
    "tech": (("Software Skills.txt", "Technology Skills.txt"), {"example": ("Workplace Example", "Example"),
                                                                 "hot": ("Hot Technology",)}),
}


def _rows(z: zipfile.ZipFile, names: tuple, cols: dict) -> list[dict]:
    """Rows of the first file present, with columns renamed to their logical names (plus 'soc')."""
    by_base = {n.rsplit("/", 1)[-1].casefold(): n for n in z.namelist()}
    member = next((by_base[n.casefold()] for n in names if n.casefold() in by_base), None)
    if member is None:
        raise SystemExit(f"none of {names} is in the zip")
    r = csv.DictReader(io.StringIO(z.read(member).decode("utf-8-sig", errors="replace")), delimiter="	")
    head = r.fieldnames or []
    pick = {"soc": next((h for h in head if h == CODE), None)}
    pick |= {k: next((h for h in alts if h in head), None) for k, alts in cols.items()}
    if missing := [k for k, h in pick.items() if h is None]:
        raise SystemExit(f"{member}: no column for {missing}; found {head}")
    return [{k: (row.get(h) or "").strip() for k, h in pick.items()} for row in r]


def build(zip_path: Path, out: Path, version: str) -> dict:
    with zipfile.ZipFile(zip_path) as z:
        d = {k: _rows(z, names, cols) for k, (names, cols) in FILES.items()}
    occ = {r["soc"]: {"code": r["soc"], "title": r["title"], "desc": r["desc"][:300], "zone": None, "titles": [],
                      "related": [], "tasks": [], "tech": []} for r in d["occ"]}
    for r in d["zones"]:
        if r["soc"] in occ and r["zone"].isdigit():
            occ[r["soc"]]["zone"] = int(r["zone"])
    for r in d["titles"]:
        o = occ.get(r["soc"])
        if o and r["title"] and r["title"].casefold() not in {x.casefold() for x in o["titles"]}:
            o["titles"].append(r["title"])
    rel: dict[str, list] = {}
    for r in d["related"]:
        rel.setdefault(r["soc"], []).append((int(r["index"]) if r["index"].isdigit() else 999, r["code"]))
    for code, pairs in rel.items():
        if code in occ:
            occ[code]["related"] = [c for _, c in sorted(pairs)]
    for r in d["tasks"]:
        o = occ.get(r["soc"])
        if o and r["type"] == "Core" and len(o["tasks"]) < 5:
            o["tasks"].append(r["task"])
    tech: dict[str, list] = {}
    for r in d["tech"]:
        tech.setdefault(r["soc"], []).append((r["hot"] != "Y", r["example"]))
    for code, pairs in tech.items():
        if code in occ:
            seen, keep = set(), []
            for _, ex in sorted(pairs, key=lambda p: p[0]):  # stable: file order within hot / not hot
                if ex and ex.casefold() not in seen:
                    seen.add(ex.casefold())
                    keep.append(ex)
            occ[code]["tech"] = keep[:25]
    meta = {"version": version, "source": f"O*NET {version} Database", "url": "https://www.onetcenter.org/database.html",
            "license": "CC BY 4.0", "credit": CREDIT.format(v=version), "built": date.today().isoformat()}
    Path(out).write_bytes(gzip.compress(json.dumps({"meta": meta, "occ": occ}, separators=(",", ":")).encode("utf-8")))
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("zip")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "lodestar" / "data" / "onet.json.gz"))
    ap.add_argument("--version", required=True)
    a = ap.parse_args(argv)
    meta = build(Path(a.zip), Path(a.out), a.version)
    n = len(json.loads(gzip.decompress(Path(a.out).read_bytes()))["occ"])
    print(f"{a.out}: {n} occupations, O*NET {meta['version']}, {Path(a.out).stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
