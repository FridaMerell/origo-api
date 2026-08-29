"""Score a location by how *varied and interesting* its species records are -
not by how many reports it has.

The design problem (see the ``artdatabanken-api`` skill, "Counting method"):
raw observation counts measure observer interest, not biological interest. One
staked rarity gets mobbed by a hundred reporters; a hundred hooded-crow records
mean nothing. So the score here is built from:

* **richness**       - how many distinct taxa, effort-corrected;
* **evenness**       - inverse Simpson index, so "100 crows + 3 others" scores
                       far below an even spread of the same richness;
* **rarity**         - taxa that are seldom reported *along this whole route*
                       but turn up here, red-listed taxa weighted extra;
* **recency**        - a rare or red-listed taxon reported in the last few days
                       (the "one very interesting bird was just seen" case).

Pure functions, no Django and no network. Feed it rows built from a SOS
``TaxonAggregation`` plus a corridor-wide frequency table; the API glue lives in
:mod:`tempus.services.route_planner`.
"""

import math
from dataclasses import dataclass, field

# Relative weights of the four terms in the final score. Tune here.
W_RICHNESS = 1.0
W_EVENNESS = 1.0
W_RARITY = 2.0
W_RECENCY = 3.0

# A taxon counts as "notable" when its corridor frequency is below this share
# of all corridor observations, or it carries any red-list category.
RARE_FREQUENCY = 0.01
# Recency bonus decays to zero over this many days.
RECENCY_HALFLIFE_DAYS = 10.0
RED_LIST_CATEGORIES = {"NT", "VU", "EN", "CR", "RE", "DD"}


@dataclass
class TaxonRow:
    """One taxon's presence at a candidate location."""

    taxon_id: int
    count: int
    scientific_name: str = ""
    vernacular_name: str = ""
    red_list_category: str = ""
    last_seen_days: float | None = None  # age in days of the most recent record

    @property
    def red_listed(self) -> bool:
        return self.red_list_category.upper() in RED_LIST_CATEGORIES


@dataclass
class Contribution:
    """Why one taxon matters to the score - shown to the user as the 'why'."""

    taxon_id: int
    scientific_name: str
    vernacular_name: str
    count: int
    red_list_category: str
    last_seen_days: float | None
    rarity_weight: float
    recency_weight: float
    reason: str

    @property
    def weight(self) -> float:
        return self.rarity_weight + self.recency_weight


@dataclass
class LocationScore:
    score: float
    richness: int
    inverse_simpson: float
    rarity: float
    recency: float
    total_count: int
    breakdown: dict = field(default_factory=dict)
    contributions: list[Contribution] = field(default_factory=list)


def richness(rows: list[TaxonRow]) -> int:
    return len({r.taxon_id for r in rows if r.count > 0})


def inverse_simpson(rows: list[TaxonRow]) -> float:
    """``1 / Σ pᵢ²``. Ranges from 1 (one taxon dominates) up to the richness
    (every taxon equally represented). This is the "variance in species" term.
    """
    total = sum(r.count for r in rows if r.count > 0)
    if total <= 0:
        return 0.0
    sum_sq = sum((r.count / total) ** 2 for r in rows if r.count > 0)
    return 1.0 / sum_sq if sum_sq else 0.0


def effort_correction(total_count: int) -> float:
    """Divisor that damps the richness term for heavily-watched spots, so a
    place near a city does not win on observer volume alone. ``sqrt`` keeps
    some credit for genuine extra diversity.
    """
    return math.sqrt(total_count) if total_count > 0 else 1.0


def _rarity_weight(row: TaxonRow, corridor_freq: dict[int, float]) -> float:
    """``-log(fᵢ)`` capped, times a red-list multiplier. ``fᵢ`` is the taxon's
    share of all corridor observations; an unseen-elsewhere taxon is treated as
    just below the rarest observed frequency.
    """
    freq = corridor_freq.get(row.taxon_id)
    if not freq or freq <= 0:
        freq = min([f for f in corridor_freq.values() if f > 0], default=RARE_FREQUENCY) / 2
    weight = -math.log(min(freq, 1.0))
    if row.red_listed:
        weight *= 2.0
    return max(0.0, weight)


def _is_notable(row: TaxonRow, corridor_freq: dict[int, float]) -> bool:
    return row.red_listed or corridor_freq.get(row.taxon_id, 0.0) < RARE_FREQUENCY


def _recency_weight(row: TaxonRow) -> float:
    if row.last_seen_days is None:
        return 0.0
    return math.exp(-max(0.0, row.last_seen_days) / RECENCY_HALFLIFE_DAYS)


def _reason(row: TaxonRow, recency_w: float,
            corridor_freq: dict[int, float]) -> str:
    parts: list[str] = []
    if row.red_listed:
        parts.append(f"red-listed ({row.red_list_category.upper()})")
    if corridor_freq.get(row.taxon_id, 0.0) < RARE_FREQUENCY:
        parts.append("rarely reported along this route")
    if recency_w > 0.35 and row.last_seen_days is not None:
        d = int(round(row.last_seen_days))
        parts.append("seen today" if d <= 0 else f"seen {d} day{'s' if d != 1 else ''} ago")
    return "; ".join(parts) or "adds to the species mix"


def rarity_score(rows: list[TaxonRow], corridor_freq: dict[int, float]) -> float:
    return sum(_rarity_weight(r, corridor_freq) for r in rows
              if r.count > 0 and _is_notable(r, corridor_freq))


def recency_bonus(rows: list[TaxonRow], corridor_freq: dict[int, float]) -> float:
    """Sum of recency weights, but only for taxa that are actually notable -
    a fresh crow record must not light this up.
    """
    return sum(_recency_weight(r) for r in rows
              if r.count > 0 and _is_notable(r, corridor_freq))


def score(
    rows: list[TaxonRow],
    corridor_freq: dict[int, float],
    *,
    reference_richness: float = 0.0,
) -> LocationScore:
    """Combine the four terms into one comparable score.

    ``reference_richness`` is the mean effort-corrected richness across all
    candidate locations on the route; pass it so the richness term is centred
    (a simple z-score-like offset). Leave it 0 for a standalone score.
    """
    live = [r for r in rows if r.count > 0]
    total = sum(r.count for r in live)
    rich = richness(live)
    inv_simpson = inverse_simpson(live)
    corrected_richness = rich / effort_correction(total)
    rar = rarity_score(live, corridor_freq)
    rec = recency_bonus(live, corridor_freq)

    richness_term = W_RICHNESS * (corrected_richness - reference_richness)
    evenness_term = W_EVENNESS * math.log(inv_simpson) if inv_simpson > 1 else 0.0
    rarity_term = W_RARITY * rar
    recency_term = W_RECENCY * rec
    total_score = richness_term + evenness_term + rarity_term + recency_term

    contributions: list[Contribution] = []
    for r in live:
        if not _is_notable(r, corridor_freq):
            continue
        rw = _rarity_weight(r, corridor_freq)
        cw = _recency_weight(r)
        contributions.append(Contribution(
            taxon_id=r.taxon_id,
            scientific_name=r.scientific_name,
            vernacular_name=r.vernacular_name,
            count=r.count,
            red_list_category=r.red_list_category,
            last_seen_days=r.last_seen_days,
            rarity_weight=round(W_RARITY * rw, 3),
            recency_weight=round(W_RECENCY * cw, 3),
            reason=_reason(r, cw, corridor_freq),
        ))
    contributions.sort(key=lambda c: c.weight, reverse=True)

    return LocationScore(
        score=round(total_score, 4),
        richness=rich,
        inverse_simpson=round(inv_simpson, 3),
        rarity=round(rar, 3),
        recency=round(rec, 3),
        total_count=total,
        breakdown={
            "richness_term": round(richness_term, 3),
            "evenness_term": round(evenness_term, 3),
            "rarity_term": round(rarity_term, 3),
            "recency_term": round(recency_term, 3),
            "corrected_richness": round(corrected_richness, 3),
        },
        contributions=contributions,
    )


def corridor_frequencies(taxon_counts: dict[int, int]) -> dict[int, float]:
    """Turn a corridor-wide ``{taxon_id: count}`` table into shares that sum to 1."""
    total = sum(taxon_counts.values())
    if total <= 0:
        return {tid: 0.0 for tid in taxon_counts}
    return {tid: c / total for tid, c in taxon_counts.items()}
