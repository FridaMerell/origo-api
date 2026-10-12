"""Turn the Hevelius sky culture's constellation art into the meshes the sky chart warps it with.

Each drawing comes with three stars pointed out on it (constellationsart.fab).
Those fix an affine map from the drawing to a tangent plane around the three
stars, and a grid over the whole drawing is carried through that map to right
ascension and declination. The chart draws the drawing as the triangles of that
grid, so it follows the chart's own projection.

Usage: python -I make_figures.py <hevelius dir> <hygdata_v41.csv> <figures.json>
"""

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

COLUMNS = ROWS = 6
# Hevelius's own abbreviations, where they differ from the IAU ones the chart uses.
# Serpentarius is Ophiuchus holding the serpent; Argo Navis is filed under its keel.
RENAMED = {"Cvn": "CVn", "Srt": "Oph", "TAs": "TrA", "TMa": "Tri", "Nav": "Car"}
# Figures with no counterpart among the 88: Mons Maenalus, Robur Carolinum, Triangulum Minus.
SKIPPED = {"MBo", "Rob", "TMi"}

source, hyg_path, target = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

art = {}
# The index is not UTF-8 (a stray Latin-1 byte in a comment); only its ASCII rows matter.
for line in (source / "constellationsart.fab").read_text(encoding="latin-1").splitlines():
    parts = line.split()
    if len(parts) != 11 or line.startswith("#") or parts[0] in SKIPPED:
        continue
    numbers = [int(value) for value in parts[2:]]
    art[RENAMED.get(parts[0], parts[0])] = (
        parts[1],
        [((numbers[i], numbers[i + 1]), numbers[i + 2]) for i in (0, 3, 6)],
    )

wanted = {hip for _, anchors in art.values() for _, hip in anchors}
positions = {}
with open(hyg_path, newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        if row["hip"] and int(row["hip"]) in wanted:
            positions[int(row["hip"])] = (float(row["ra"]) * 15, float(row["dec"]))


def image_size(path):
    """Width and height from a PNG header."""
    header = path.read_bytes()[:24]
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


figures = {}
for figure, (file, anchors) in sorted(art.items()):
    missing = [hip for _, hip in anchors if hip not in positions]
    if missing:
        print(f"skipped {figure}: HIP {missing} not in HYG")
        continue
    width, height = image_size(source / file)
    stars = np.radians([positions[hip] for _, hip in anchors])
    # Centre of the tangent plane: the mean direction of the three stars.
    vectors = np.array([[math.cos(d) * math.cos(r), math.cos(d) * math.sin(r), math.sin(d)] for r, d in stars])
    centre = vectors.mean(axis=0)
    centre /= np.linalg.norm(centre)
    centre_ra, centre_dec = math.atan2(centre[1], centre[0]), math.asin(centre[2])

    def to_plane(ra, dec):
        cosine = math.sin(centre_dec) * math.sin(dec) + math.cos(centre_dec) * math.cos(dec) * math.cos(ra - centre_ra)
        return (
            math.cos(dec) * math.sin(ra - centre_ra) / cosine,
            (math.cos(centre_dec) * math.sin(dec) - math.sin(centre_dec) * math.cos(dec) * math.cos(ra - centre_ra)) / cosine,
        )

    def from_plane(x, y):
        rho = math.hypot(x, y)
        if rho == 0:
            return math.degrees(centre_ra) % 360, math.degrees(centre_dec)
        angle = math.atan(rho)
        dec = math.asin(math.cos(angle) * math.sin(centre_dec) + y * math.sin(angle) * math.cos(centre_dec) / rho)
        ra = centre_ra + math.atan2(
            x * math.sin(angle),
            rho * math.cos(centre_dec) * math.cos(angle) - y * math.sin(centre_dec) * math.sin(angle),
        )
        return math.degrees(ra) % 360, math.degrees(dec)

    design = np.array([[1, x / width, y / height] for (x, y), _ in anchors])
    plane = np.array([to_plane(ra, dec) for ra, dec in stars])
    coefficients = np.linalg.solve(design, plane)

    nodes = []
    for row in range(ROWS + 1):
        for column in range(COLUMNS + 1):
            x, y = np.array([1, column / COLUMNS, row / ROWS]) @ coefficients
            ra, dec = from_plane(x, y)
            nodes.append([round(ra, 2), round(dec, 2)])
    figures[figure] = {
        "image": f"/data/figures/{Path(file).stem}.webp",
        "columns": COLUMNS,
        "rows": ROWS,
        # Row by row from the drawing's top left corner: [right ascension, declination], J2000.
        "nodes": nodes,
    }

with open(target, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "source": "Johannes Hevelius, Firmamentum Sobiescianum (1690). Sky culture for Stellarium by Mark Crossley, wilmslowastro.com; scans: US Naval Observatory, STScI, Polish National Digital Library",
            "figures": figures,
        },
        handle,
        separators=(",", ":"),
    )
print(len(figures), "figures:", " ".join(figures))
