"""Rebuild lodestar/data/places.json.gz (pass 53, the Board's map) from the U.S. Census Bureau's Gazetteer files
(public domain): https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/
usage: python scripts/build_places.py 2024_Gaz_place_national.txt 2024_Gaz_zcta_national.txt"""
import gzip
import json
import re
import sys
from pathlib import Path

SUFFIX = re.compile(r"\s+(city and borough|consolidated government|unified government|metropolitan government|"
                    r"municipality|city|town|township|village|borough|CDP|comunidad|zona urbana|plantation|corporation)"
                    r"(\s*\(.*\))?$", re.I)


def rows(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        head = [h.strip() for h in f.readline().split("\t")]
        for line in f:
            yield dict(zip(head, (v.strip() for v in line.split("\t"))))


def main(place, zcta):
    p, z = {}, {}
    for r in rows(place):
        name = SUFFIX.sub("", r["NAME"]).strip().lower()
        p.setdefault(f"{name}|{r['USPS'].lower()}", [round(float(r["INTPTLAT"]), 3), round(float(r["INTPTLONG"]), 3)])
    for r in rows(zcta):
        z[r["GEOID"]] = [round(float(r["INTPTLAT"]), 3), round(float(r["INTPTLONG"]), 3)]
    out = Path(__file__).resolve().parent.parent / "lodestar" / "data" / "places.json.gz"
    data = {"source": "U.S. Census Bureau, 2024 Gazetteer Files (public domain)", "p": p, "z": z}
    out.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))
    print(f"{len(p)} places, {len(z)} ZIPs -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
