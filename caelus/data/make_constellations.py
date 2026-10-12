"""Merge d3-celestial's constellation lines and names into one compact JSON file.

Usage: python -I make_constellations.py <data dir> <constellations.json>
"""

import json
import sys
from pathlib import Path

source, target = Path(sys.argv[1]), sys.argv[2]
lines = json.loads((source / "d3-celestial-constellations.lines.json").read_text(encoding="utf-8"))
names = json.loads((source / "d3-celestial-constellations.json").read_text(encoding="utf-8"))

by_id = {feature["id"]: feature for feature in names["features"]}
constellations = []
for feature in lines["features"]:
    info = by_id[feature["id"]]
    constellations.append(
        {
            "id": feature["id"],
            "name": info["properties"]["la"],
            "genitive": info["properties"]["gen"],
            "greek": info["properties"]["el"],
            "rank": int(info["properties"]["rank"]),
            "at": info["geometry"]["coordinates"],
            "lines": feature["geometry"]["coordinates"],
        }
    )

payload = {
    "source": "d3-celestial, Olaf Frohn, BSD-3-Clause",
    "epoch": "J2000",
    "constellations": constellations,
}
with open(target, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
print(len(constellations), constellations[0]["name"], constellations[0]["at"], len(by_id))
