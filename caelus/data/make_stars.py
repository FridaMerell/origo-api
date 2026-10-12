"""Reduce the HYG catalogue to the naked-eye stars as two compact JSON files.

stars.json is what the sky chart draws. star-details.json holds what is only
shown for one star at a time, row for row in the same order, so it can be
fetched when a star is first opened.

Usage: python -I make_stars.py <hygdata_v41.csv> <stars.json> <star-details.json>
"""

import csv
import json
import sys

LIMIT = 6.5
LIGHT_YEARS_PER_PARSEC = 3.26156
# HYG's placeholder for a missing or dubious parallax.
UNKNOWN_DISTANCE = 100000

source, target, details_target = sys.argv[1], sys.argv[2], sys.argv[3]
rows = []
with open(source, newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        if row["id"] == "0":  # the Sun
            continue
        magnitude = float(row["mag"])
        if magnitude > LIMIT:
            continue
        distance = float(row["dist"])
        rows.append(
            (
                [
                    round(float(row["ra"]) * 15, 3),
                    round(float(row["dec"]), 3),
                    round(magnitude, 2),
                    round(float(row["ci"]), 2) if row["ci"] else None,
                    row["bayer"],
                    row["con"],
                    row["proper"],
                ],
                [
                    int(row["hip"]) if row["hip"] else None,
                    int(row["hd"]) if row["hd"] else None,
                    round(distance * LIGHT_YEARS_PER_PARSEC, 1) if distance < UNKNOWN_DISTANCE else None,
                    row["spect"],
                    float(f"{float(row['lum']):.3g}") if row["lum"] else None,
                    row["flam"],
                    row["var"],
                ],
            )
        )
rows.sort(key=lambda pair: pair[0][2])
stars = [star for star, _ in rows]
details = [detail for _, detail in rows]

SOURCE = "HYG Database v4.1, astronexus, CC BY-SA 4.0"
with open(target, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "source": SOURCE,
            "epoch": "J2000",
            "fields": ["ra", "dec", "mag", "ci", "bayer", "con", "name"],
            "stars": stars,
        },
        handle,
        ensure_ascii=False,
        separators=(",", ":"),
    )
with open(details_target, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "source": SOURCE,
            "fields": ["hip", "hd", "light_years", "spectrum", "luminosity", "flamsteed", "variable"],
            "stars": details,
        },
        handle,
        ensure_ascii=False,
        separators=(",", ":"),
    )
print(len(stars), stars[0], details[0])
print(stars[-1], details[-1])
