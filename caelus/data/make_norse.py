"""Resolve Stellarium's Norse sky culture from HIP numbers to coordinates.

Usage: python -I make_norse.py <norse/index.json> <hygdata_v41.csv> <norse.json>
"""

import csv
import json
import sys

culture_path, hyg_path, target = sys.argv[1], sys.argv[2], sys.argv[3]
with open(culture_path, encoding="utf-8") as handle:
    culture = json.load(handle)

wanted = {hip for item in culture["constellations"] for line in item["lines"] for hip in line}
wanted |= {int(key.split()[1]) for key in culture["common_names"]}
positions = {}
with open(hyg_path, newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        if row["hip"] and int(row["hip"]) in wanted:
            positions[int(row["hip"])] = [round(float(row["ra"]) * 15, 3), round(float(row["dec"]), 3)]
missing = wanted - positions.keys()
if missing:
    raise SystemExit(f"HIP numbers not in HYG: {sorted(missing)}")

constellations = []
for item in culture["constellations"]:
    lines = [[positions[hip] for hip in line] for line in item["lines"]]
    points = [point for line in lines for point in line]
    constellations.append(
        {
            "id": item["id"].split()[-1],
            "name": item["common_name"]["english"],
            "rank": 1,
            # All six figures lie far from RA 0h, so a plain mean is a safe label position.
            "at": [
                round(sum(point[0] for point in points) / len(points), 2),
                round(sum(point[1] for point in points) / len(points), 2),
            ],
            "lines": lines,
        }
    )

payload = {
    "source": "Stellarium sky culture 'Norse', Jonas Persson, CC BY-SA",
    "epoch": "J2000",
    "constellations": constellations,
    "stars": [
        {"at": positions[int(key.split()[1])], "name": names[0]["english"]}
        for key, names in culture["common_names"].items()
    ],
}
with open(target, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
print(json.dumps(payload)[:600])
