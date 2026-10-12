"""Fit a scanned Uranometria plate to the sky and write the mesh the chart warps it with.

Stars pointed out on the plate (as fractions of its width and height) are matched
to the catalogue. A least-squares fit maps plate positions to a tangent plane
around the plate's centre, and a grid over the whole plate is carried through
that fit to right ascension and declination. The chart draws the plate as the
triangles of that grid, so it follows the chart's own projection.

Usage: python -I make_plate.py <stars.json> <plate.json>
"""

import json
import math
import sys

import numpy as np

# Orion, from Wikimedia Commons "ORION Uranometria orion.jpg" (USNO Library, public domain).
IMAGE = "/plate-orion.webp"
FIGURE = "Ori"
ASPECT = 2445 / 3329
# (Bayer letter, constellation) -> the star's position on the scan, in its own pixels,
# read off a copy with a labelled grid laid over it.
MEASURED_SIZE = (2445, 3329)
CONTROL_POINTS = {
    ("Alp", "Ori"): (764, 1344),
    ("Gam", "Ori"): (1320, 1414),
    ("Del", "Ori"): (1230, 1960),
    ("Eps", "Ori"): (1166, 2044),
    ("Zet", "Ori"): (1086, 2100),
    ("Bet", "Ori"): (1580, 2566),
    ("Kap", "Ori"): (984, 2730),
    ("Lam", "Ori"): (1116, 1150),
    ("Eta", "Ori"): (1366, 2120),
    ("Iot", "Ori"): (1186, 2424),
    ("Tau", "Ori"): (1520, 2466),
    ("Mu", "Ori"): (624, 1246),
    ("Alp", "Tau"): (2160, 510),
    # Stars out towards the plate's corners keep the fit from drifting there.
    ("Chi-1", "Ori"): (694, 306),
    ("Chi-2", "Ori"): (524, 330),
    ("Nu", "Ori"): (480, 756),
    ("Xi", "Ori"): (410, 800),
    ("Omi-1", "Ori"): (1872, 720),
    ("Omi-2", "Ori"): (1796, 784),
}
COLUMNS, ROWS = 8, 10
MODEL = sys.argv[3] if len(sys.argv) > 3 else "bilinear"

stars_path, target = sys.argv[1], sys.argv[2]
with open(stars_path, encoding="utf-8") as handle:
    catalogue = json.load(handle)["stars"]
# The catalogue is sorted brightest first, so the first match is the star meant.
positions = {}
for ra, dec, _, _, bayer, constellation, _ in catalogue:
    positions.setdefault((bayer, constellation), (ra, dec))

centre_ra = math.radians(np.mean([positions[key][0] for key in CONTROL_POINTS]))
centre_dec = math.radians(np.mean([positions[key][1] for key in CONTROL_POINTS]))


def to_plane(ra, dec):
    """Gnomonic projection around the plate's centre, in radians."""
    ra, dec = math.radians(ra), math.radians(dec)
    cosine = math.sin(centre_dec) * math.sin(dec) + math.cos(centre_dec) * math.cos(dec) * math.cos(ra - centre_ra)
    return (
        math.cos(dec) * math.sin(ra - centre_ra) / cosine,
        (math.cos(centre_dec) * math.sin(dec) - math.sin(centre_dec) * math.cos(dec) * math.cos(ra - centre_ra)) / cosine,
    )


def from_plane(x, y):
    rho = math.hypot(x, y)
    if rho == 0:
        return math.degrees(centre_ra), math.degrees(centre_dec)
    angle = math.atan(rho)
    dec = math.asin(math.cos(angle) * math.sin(centre_dec) + y * math.sin(angle) * math.cos(centre_dec) / rho)
    ra = centre_ra + math.atan2(
        x * math.sin(angle),
        rho * math.cos(centre_dec) * math.cos(angle) - y * math.sin(centre_dec) * math.sin(angle),
    )
    return math.degrees(ra) % 360, math.degrees(dec)


def terms(u, v):
    # Second order: Bayer's trapezoidal projection is not a plain affine image of the sky.
    if MODEL == "affine":
        return [1, u, v]
    if MODEL == "bilinear":
        return [1, u, v, u * v]
    return [1, u, v, u * u, u * v, v * v]


measured = np.array([[x / MEASURED_SIZE[0], y / MEASURED_SIZE[1]] for x, y in CONTROL_POINTS.values()])
plane = np.array([to_plane(*positions[key]) for key in CONTROL_POINTS])
design = np.array([terms(u, v) for u, v in measured])
coefficients, *_ = np.linalg.lstsq(design, plane, rcond=None)

residuals = np.degrees(np.hypot(*(design @ coefficients - plane).T))
for key, residual in zip(CONTROL_POINTS, residuals):
    print(f"{key[0]} {key[1]}: {residual:.2f} deg")
print(f"worst {residuals.max():.2f} deg, mean {residuals.mean():.2f} deg")

nodes = []
for row in range(ROWS + 1):
    for column in range(COLUMNS + 1):
        x, y = np.array(terms(column / COLUMNS, row / ROWS)) @ coefficients
        ra, dec = from_plane(x, y)
        nodes.append([round(ra, 3), round(dec, 3)])

with open(target, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "source": "Johann Bayer, Uranometria, Orion. Scan: US Naval Observatory Library via Wikimedia Commons, public domain",
            "figure": FIGURE,
            "image": IMAGE,
            "aspect": round(ASPECT, 5),
            "columns": COLUMNS,
            "rows": ROWS,
            # Row by row from the plate's top left corner: [right ascension, declination], J2000.
            "nodes": nodes,
        },
        handle,
        separators=(",", ":"),
    )
print(nodes[0], nodes[COLUMNS], nodes[-1])
