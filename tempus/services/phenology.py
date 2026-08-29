"""Phenology maths: turn observation dates into a seasonal activity curve.

Pure functions, no Django and no network, so they are cheap to test and reuse
from management commands, Celery tasks or the API layer. The API calls that feed
these live in :mod:`tempus.services.artdatabanken`; persistence targets the
``Phenogram`` / ``SpeciesFollow`` models.

Vocabulary
----------
phenogram
    ``dict`` mapping ISO week ``1..52`` to a value (record count, occupied-cell
    count, ...). Week 53 is folded into 52. Weeks are used internally because
    they smooth out day-level reporting noise; :func:`season_window_days`
    converts the result to the day-of-year fields ``Phenogram`` stores.
activity window
    the ``(lo, hi)`` span holding the central 10-90 % of records - "roughly
    when you can expect to see it".
declustering
    collapsing many reports of one staked individual (a twitched rarity) down
    to one per week, so interest does not masquerade as abundance.
"""

import datetime

from tempus.services.geo import haversine_m as _haversine_m

Phenogram = dict[int, float]
WEEKS = list(range(1, 53))


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def to_date(value) -> datetime.date:
    """Accept a ``date``, ``datetime`` or ISO string (date or full timestamp)."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def iso_week(value) -> int:
    week = to_date(value).isocalendar().week
    return 52 if week == 53 else week


def day_of_year(value) -> int:
    return to_date(value).timetuple().tm_yday


def observation_dates(records, key: str = "event.startDate") -> list[datetime.date]:
    """Pull the observation date from SOS observation records (dotted key path).

    Records with a missing or unparseable date are skipped.
    """
    path = key.split(".")
    out: list[datetime.date] = []
    for record in records:
        node = record
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if not node:
            continue
        try:
            out.append(to_date(node))
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------- #
# Building the phenogram
# --------------------------------------------------------------------------- #
def phenogram(dates, weights=None) -> Phenogram:
    """Week-of-year totals, weeks ``1..52`` always present.

    ``weights`` (a parallel iterable) sums a per-record quantity instead of
    counting records - only use it for a rough "strong year / weak year"
    abundance hint over a single quantity unit. For phenology leave it ``None``
    and prefer counting occupied grid cells or :func:`decluster`-ed records.
    """
    hist: Phenogram = {week: 0.0 for week in WEEKS}
    if weights is None:
        for date in dates:
            hist[iso_week(date)] += 1.0
    else:
        for date, weight in zip(dates, weights):
            hist[iso_week(date)] += float(weight or 0.0)
    return hist


def decluster(
    records,
    *,
    taxon_key: str = "taxon.id",
    lat_key: str = "location.decimalLatitude",
    lon_key: str = "location.decimalLongitude",
    date_key: str = "event.startDate",
    radius_m: float = 1000.0,
    gap_days: int = 21,
):
    """Yield one date per distinct individual/population per ISO week.

    Hundreds of people twitching one rare bird at one spot in one week should
    count once, not hundreds of times; a genuinely long-staying individual keeps
    one count per week it is present. Greedy spatial-temporal clustering per
    taxon. Records with no date are dropped; records with no coordinates cannot
    be clustered and pass through individually.
    """
    def get(record, path):
        node = record
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return node

    rows = []
    for record in records:
        raw = get(record, date_key)
        date = None
        if raw:
            try:
                date = to_date(raw)
            except ValueError:
                date = None
        rows.append((date, get(record, taxon_key), get(record, lat_key), get(record, lon_key)))
    rows.sort(key=lambda row: row[0] or datetime.date.min)

    clusters: list[dict] = []
    emitted: set[tuple[int, int]] = set()
    for date, taxon, lat, lon in rows:
        if date is None:
            continue
        if lat is None or lon is None:
            yield date
            continue
        index = None
        for i, cluster in enumerate(clusters):
            if (
                cluster["taxon"] == taxon
                and (date - cluster["last"]).days <= gap_days
                and _haversine_m(lat, lon, cluster["lat"], cluster["lon"]) <= radius_m
            ):
                index, cluster["last"] = i, date
                break
        if index is None:
            clusters.append({"taxon": taxon, "lat": lat, "lon": lon, "last": date})
            index = len(clusters) - 1
        key = (index, iso_week(date))
        if key not in emitted:
            emitted.add(key)
            yield date


# --------------------------------------------------------------------------- #
# Shaping the curve
# --------------------------------------------------------------------------- #
def smooth(hist: Phenogram, window: int = 1) -> Phenogram:
    """Circular moving average +/- ``window`` weeks (the year wraps)."""
    out: Phenogram = {}
    for week in WEEKS:
        total = sum(hist.get((week - 1 + offset) % 52 + 1, 0.0)
                    for offset in range(-window, window + 1))
        out[week] = total / (2 * window + 1)
    return out


def normalize(hist: Phenogram) -> Phenogram:
    """Scale so the year sums to 1.0 -> "fraction of annual records in week w"."""
    total = sum(hist.values()) or 1.0
    return {week: hist.get(week, 0.0) / total for week in WEEKS}


def divide(hist: Phenogram, effort: Phenogram) -> Phenogram:
    """Correct for observer effort: taxon counts / all-taxa counts, per week.

    ``effort`` is a phenogram of *all* observations in the same area and years.
    Weeks with no effort data yield 0.0 rather than dividing by zero.
    """
    return {week: (hist.get(week, 0.0) / effort[week]) if effort.get(week) else 0.0
            for week in WEEKS}


# --------------------------------------------------------------------------- #
# Reading the curve
# --------------------------------------------------------------------------- #
def peak_week(hist: Phenogram) -> int:
    return max(WEEKS, key=lambda week: hist.get(week, 0.0))


def activity_window(hist: Phenogram, lo: float = 0.10, hi: float = 0.90) -> tuple[int, int]:
    """ISO-week span holding the central ``lo``..``hi`` mass of records.

    Rotates the year to start at its emptiest week first, so a season that
    straddles new year (e.g. an overwintering species) is handled correctly.
    """
    start = min(WEEKS, key=lambda week: hist.get(week, 0.0))
    order = [(start - 1 + i) % 52 + 1 for i in range(52)]
    total = sum(hist.values()) or 1.0
    cumulative, lo_week, hi_week = 0.0, order[0], order[-1]
    for week in order:
        cumulative += hist.get(week, 0.0) / total
        if cumulative <= lo:
            lo_week = week
        if cumulative <= hi:
            hi_week = week
    return lo_week, hi_week


def limb(hist: Phenogram, week: int) -> str:
    """``"ascending"`` / ``"descending"`` / ``"off"`` for a week vs the peak."""
    peak = peak_week(hist)
    if smooth(hist, 1)[week] < 0.05 * hist.get(peak, 1.0):
        return "off"
    weeks_to_peak = (peak - week) % 52
    return "ascending" if 0 < weeks_to_peak <= 26 else "descending"


def _week_to_day(week: int) -> int:
    return min(366, max(1, (week - 1) * 7 + 1))


def season_window_days(hist: Phenogram, *, years_present: int = 0) -> dict:
    """Derive the day-of-year envelope a ``Phenogram`` row stores.

    Returns ``start_day_of_year`` / ``peak_start_day`` / ``peak_end_day`` /
    ``end_day_of_year`` (the 10-90 % window, and the >=50 %-of-peak run around
    the peak), plus a heuristic ``confidence`` in ``0..1`` that grows with the
    number of years of data. :func:`phenogram_status` reads this envelope back
    to place a given day in the year.
    """
    smoothed = smooth(hist, 1)
    lo_week, hi_week = activity_window(smoothed)
    peak = peak_week(smoothed)
    half = 0.5 * smoothed[peak]

    peak_lo = peak
    while peak_lo > 1 and smoothed[peak_lo - 1] >= half:
        peak_lo -= 1
    peak_hi = peak
    while peak_hi < 52 and smoothed[peak_hi + 1] >= half:
        peak_hi += 1

    confidence = round(min(1.0, years_present / 5.0), 2) if years_present else None
    return {
        "start_day_of_year": _week_to_day(lo_week),
        "peak_start_day": _week_to_day(peak_lo),
        "peak_end_day": min(366, _week_to_day(peak_hi) + 6),
        "end_day_of_year": min(366, _week_to_day(hi_week) + 6),
        "confidence": confidence,
    }


# --------------------------------------------------------------------------- #
# Placing "now" in the envelope
# --------------------------------------------------------------------------- #
DEFAULT_SOON_DAYS = 21
DEFAULT_LAST_CHANCE_DAYS = 14

SEASON_STATUSES = (
    "out_of_season",
    "coming_into_season",
    "in_season",
    "at_peak",
    "going_out_of_season",
)


def _doy_in_span(day: int, start: int, end: int) -> bool:
    """True if day-of-year ``day`` is inside ``[start, end]``, year-wrap allowed."""
    if start <= end:
        return start <= day <= end
    return day >= start or day <= end


def _days_forward(frm: int, to: int) -> int:
    """Whole days from day-of-year ``frm`` forward to ``to`` (0..365, wraps)."""
    return (to - frm) % 366


def phenogram_status(
    envelope: dict,
    day_of_year: int,
    *,
    soon_days: int = DEFAULT_SOON_DAYS,
    last_chance_days: int = DEFAULT_LAST_CHANCE_DAYS,
) -> dict:
    """Where ``day_of_year`` sits in a phenogram's day-of-year envelope.

    ``envelope`` is any mapping carrying ``start_day_of_year`` /
    ``end_day_of_year`` and optional ``peak_start_day`` / ``peak_end_day`` -
    the shape :func:`season_window_days` returns and a ``Phenogram`` row
    stores. The window may cross new year. Returns:

    ``status``
        one of :data:`SEASON_STATUSES`.
    ``is_in_season``
        ``start <= now <= end`` (peak and last-chance both count as in season).
    ``is_coming_into_season``
        not in season yet, but ``start`` is within ``soon_days``.
    ``is_going_out_of_season``
        in season, and ``end`` is within ``last_chance_days``.
    ``at_peak``
        inside the peak sub-window, when the envelope carries one.
    ``days_until_start`` / ``days_until_end``
        whole days forward to each edge; ``days_until_start`` is 0 once in
        season, ``days_until_end`` is 0 once out of season.
    """
    start = envelope["start_day_of_year"]
    end = envelope["end_day_of_year"]
    peak_start = envelope.get("peak_start_day")
    peak_end = envelope.get("peak_end_day")

    in_season = _doy_in_span(day_of_year, start, end)
    at_peak = bool(
        peak_start and peak_end and _doy_in_span(day_of_year, peak_start, peak_end)
    )
    days_until_start = 0 if in_season else _days_forward(day_of_year, start)
    days_until_end = _days_forward(day_of_year, end) if in_season else 0
    coming = not in_season and days_until_start <= soon_days
    going = in_season and days_until_end <= last_chance_days

    if at_peak:
        status = "at_peak"
    elif going:
        status = "going_out_of_season"
    elif in_season:
        status = "in_season"
    elif coming:
        status = "coming_into_season"
    else:
        status = "out_of_season"

    return {
        "status": status,
        "is_in_season": in_season,
        "is_coming_into_season": coming,
        "is_going_out_of_season": going,
        "at_peak": at_peak,
        "days_until_start": days_until_start,
        "days_until_end": days_until_end,
    }


# --------------------------------------------------------------------------- #
# Scoring the current year
# --------------------------------------------------------------------------- #
def in_season_score(
    baseline: Phenogram,
    current_week: int,
    *,
    first_week_this_year: int | None = None,
    reported_this_year: bool = False,
    years_present: int = 0,
) -> float:
    """``0..~1``. High = normally active now, on the way up, and (if already
    seen this year) only just started. Multiplicative, so any hard-zero factor
    removes the taxon from the "coming into season" list entirely.
    """
    base = normalize(smooth(baseline, 1))
    weight = base[current_week]
    if weight == 0:
        return 0.0

    rising = 1.0 if limb(baseline, current_week) == "ascending" else 0.25
    confidence = min(1.0, years_present / 5.0) if years_present else 0.5

    if reported_this_year and first_week_this_year is not None:
        age = (current_week - first_week_this_year) % 52
        recency = max(0.0, 1.0 - age / 6.0)
    elif reported_this_year:
        recency = 0.3
    else:
        recency = 1.0

    return weight * rising * recency * confidence


def season_status(
    window: tuple[int, int],
    current_week: int,
    *,
    reported_this_year: bool,
    first_week_this_year: int | None = None,
) -> str:
    """Where a followed species is in its current-year cycle.

    One of ``not_yet_due`` / ``due_now_unseen`` / ``just_started`` / ``seen`` /
    ``overdue`` / ``season_over``.
    """
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
