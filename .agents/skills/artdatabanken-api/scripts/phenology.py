"""Pure-Python phenology helpers for the "what's in season" feature.

No dependencies, no Django, no network -- feed it dates (or SOS records) and it
gives you week-of-year histograms, the expected activity window, and an
in-season score. Wire the API calls and persistence in Tempus around this.

Vocabulary: a *phenogram* here is a dict {iso_week: value} for weeks 1..52
(week 53 is folded into 52). "Activity" means the Artportalen activity/lifeStage
term you filtered on -- e.g. ``imago`` for adult insects, ``flowering`` for
plants. See references/seasonality.md.
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, Iterable, List, Optional, Tuple

Phenogram = Dict[int, float]
WEEKS = list(range(1, 53))


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def to_date(value) -> _dt.date:
    """Accept date, datetime, or ISO string ('2024-06-14' or full timestamp)."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value)[:10])


def iso_week(value) -> int:
    w = to_date(value).isocalendar()[1]
    return 52 if w == 53 else w


def sos_record_dates(records: Iterable[dict], key: str = "event.startDate") -> List[_dt.date]:
    """Pull the observation date out of SOS Search records (dotted key path)."""
    parts = key.split(".")
    out: List[_dt.date] = []
    for rec in records:
        node = rec
        for p in parts:
            node = (node or {}).get(p) if isinstance(node, dict) else None
        if node:
            try:
                out.append(to_date(node))
            except ValueError:
                pass
    return out


# --------------------------------------------------------------------------- #
# Building the phenogram
# --------------------------------------------------------------------------- #
def phenogram(dates: Iterable, weights: Optional[Iterable[float]] = None) -> Phenogram:
    """Week-of-year totals, weeks 1..52 always present (0 where empty).

    ``weights`` (parallel iterable) sums individuals/quantity instead of records
    -- use only for a "good year vs bad year" abundance hint, and only over one
    ``organismQuantityType``. For phenology, leave it None and prefer counting
    *occupied grid cells* or ``decluster()``ed records (see references/
    seasonality.md) -- raw report counts are dominated by twitchers piling onto
    a single staked rarity.
    """
    hist: Phenogram = {w: 0.0 for w in WEEKS}
    if weights is None:
        for d in dates:
            hist[iso_week(d)] += 1.0
    else:
        for d, wt in zip(dates, weights):
            hist[iso_week(d)] += float(wt or 0.0)
    return hist


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def decluster(
    records: Iterable[dict],
    *,
    taxon_key: str = "taxon.id",
    lat_key: str = "location.decimalLatitude",
    lon_key: str = "location.decimalLongitude",
    date_key: str = "event.startDate",
    radius_m: float = 1000.0,
    gap_days: int = 21,
) -> Iterator[_dt.date]:
    """Collapse reports of the same staked individual/population.

    300 people twitching one rarity at one spot over two weeks should count once
    per week, not 300 times. Greedy spatial-temporal clustering per taxon; yields
    one date per (cluster, ISO week) so a long-staying individual keeps its
    duration while a same-week pile-on does not. Feed the result to
    ``phenogram()``. Records with no date are dropped; records with no coords
    can't be declustered and pass through individually.
    """
    def get(rec: dict, path: str):
        node = rec
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return node

    rows = []
    for rec in records:
        raw = get(rec, date_key)
        d = None
        if raw:
            try:
                d = to_date(raw)
            except ValueError:
                d = None
        rows.append((d, get(rec, taxon_key), get(rec, lat_key), get(rec, lon_key)))
    rows.sort(key=lambda r: r[0] or _dt.date.min)

    clusters: List[dict] = []
    emitted: set = set()
    for d, tx, lat, lon in rows:
        if d is None:
            continue
        if lat is None or lon is None:
            yield d
            continue
        idx = None
        for i, c in enumerate(clusters):
            if (c["taxon"] == tx and (d - c["last"]).days <= gap_days
                    and _haversine_m(lat, lon, c["lat"], c["lon"]) <= radius_m):
                idx, c["last"] = i, d
                break
        if idx is None:
            clusters.append({"taxon": tx, "lat": lat, "lon": lon, "last": d})
            idx = len(clusters) - 1
        key = (idx, iso_week(d))
        if key not in emitted:
            emitted.add(key)
            yield d


def smooth(hist: Phenogram, window: int = 1) -> Phenogram:
    """Circular moving average +/- ``window`` weeks (the year wraps)."""
    out: Phenogram = {}
    for w in WEEKS:
        acc = 0.0
        for off in range(-window, window + 1):
            wk = (w - 1 + off) % 52 + 1
            acc += hist.get(wk, 0.0)
        out[w] = acc / (2 * window + 1)
    return out


def normalize(hist: Phenogram) -> Phenogram:
    """Scale so the year sums to 1.0 -> 'fraction of annual records in week w'."""
    total = sum(hist.values()) or 1.0
    return {w: hist.get(w, 0.0) / total for w in WEEKS}


def divide(hist: Phenogram, effort: Phenogram) -> Phenogram:
    """Correct for observer effort: taxon counts / all-taxa counts, per week.

    Pass ``effort`` = phenogram of *all* observations in the same area/years.
    Removes the "everything peaks when birders are out in May" artefact.
    """
    return {w: (hist.get(w, 0.0) / effort[w]) if effort.get(w) else 0.0 for w in WEEKS}


# --------------------------------------------------------------------------- #
# Reading the curve
# --------------------------------------------------------------------------- #
def peak_week(hist: Phenogram) -> int:
    return max(WEEKS, key=lambda w: hist.get(w, 0.0))


def activity_window(hist: Phenogram, lo: float = 0.10, hi: float = 0.90) -> Tuple[int, int]:
    """ISO-week span holding the central lo..hi mass of records.

    e.g. (20, 34) == "normally reported between week 20 and week 34".
    Handles seasons that straddle new year by rotating to the emptiest week.
    """
    start = min(WEEKS, key=lambda w: hist.get(w, 0.0))
    order = [(start - 1 + i) % 52 + 1 for i in range(52)]
    total = sum(hist.values()) or 1.0
    cum, lo_wk, hi_wk = 0.0, order[0], order[-1]
    for w in order:
        cum += hist.get(w, 0.0) / total
        if cum <= lo:
            lo_wk = w
        if cum <= hi:
            hi_wk = w
    return lo_wk, hi_wk


def limb(hist: Phenogram, week: int) -> str:
    """'ascending' | 'descending' | 'off' for a given week vs the seasonal peak."""
    pk = peak_week(hist)
    val = smooth(hist, 1)[week]
    if val < 0.05 * hist.get(pk, 1.0):
        return "off"
    # distance forward to peak vs backward from peak, on the circular year
    fwd = (pk - week) % 52
    return "ascending" if 0 < fwd <= 26 else "descending"


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def in_season_score(
    baseline: Phenogram,
    current_week: int,
    *,
    first_week_this_year: Optional[int] = None,
    reported_this_year: bool = False,
    weeks_of_data: int = 0,
) -> float:
    """0..~1. High = normally active now, on the way up, and (if seen this year)
    only just started. Multiplicative so any hard-zero factor kills the score.
    """
    base = normalize(smooth(baseline, 1))
    weight = base[current_week]
    if weight == 0:
        return 0.0

    rising = 1.0 if limb(baseline, current_week) == "ascending" else 0.25
    confidence = min(1.0, weeks_of_data / 5.0) if weeks_of_data else 0.5

    if reported_this_year and first_week_this_year is not None:
        age = (current_week - first_week_this_year) % 52
        recency = max(0.0, 1.0 - age / 6.0)      # fades over ~6 weeks
    elif reported_this_year:
        recency = 0.3
    else:
        recency = 1.0                            # not seen yet = maximal "look now"

    return weight * rising * recency * confidence


def season_status(
    window: Tuple[int, int],
    current_week: int,
    *,
    reported_this_year: bool,
    first_week_this_year: Optional[int] = None,
) -> str:
    """State machine for a watchlist entry's current-year progress."""
    lo, hi = window
    span = [(lo - 1 + i) % 52 + 1 for i in range((hi - lo) % 52 + 1)]
    in_window = current_week in span
    before = not in_window and ((lo - current_week) % 52) < ((current_week - hi) % 52)

    if reported_this_year:
        if first_week_this_year is not None and (current_week - first_week_this_year) % 52 <= 2:
            return "just_started"
        return "seen"
    if before:
        return "not_yet_due"
    if in_window:
        return "due_now_unseen"
    return "overdue" if ((current_week - hi) % 52) <= 6 else "season_over"


__all__ = [
    "Phenogram", "to_date", "iso_week", "sos_record_dates", "phenogram",
    "decluster", "smooth", "normalize", "divide", "peak_week", "activity_window",
    "limb", "in_season_score", "season_status",
]
