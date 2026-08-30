"""Score a location by how *varied and interesting* its species records are -
not by how many reports it has.

The design problem (see the ``artdatabanken-api`` skill, "Counting method"):
raw observation counts measure observer interest, not biological interest. One
staked rarity gets mobbed by a hundred reporters; a hundred hooded-crow records
mean nothing. So the score here is built from:

* **richness**       - how many distinct taxa, effort-corrected;
* **evenness**       - inverse Simpson index, so "100 crows + 3 others" scores
                       far below an even spread of the same richness;
* **rarity**         - taxa whose *report* carries weight: seldom-reported or
                       red-listed species, read from a precomputed per-taxon
                       ``significance`` (0..1) rather than recomputed live;
* **recency**        - a notable taxon reported in the last few days (the "one
                       very interesting bird was just seen" case).

Pure functions, no Django and no network. Each ``TaxonRow`` carries its own
``significance`` - the caller looks it up (``Phenogram.significance`` /
``Species.significance``, both filled during phenogram builds) and attaches it.
``significance_from_cells`` is the shared formula used to fill those fields.
"""

import math
from dataclasses import dataclass, field

# Relative weights of the four terms in the final score. Tune here.
W_RICHNESS = 1.0
W_EVENNESS = 1.0
W_RARITY = 2.0
W_RECENCY = 3.0

# A taxon counts toward the rarity and recency terms when its significance is at
# least this, or it carries any red-list category.
NOTABLE_SIGNIFICANCE = 0.5
# Significance used for a taxon we have no precomputed value for (not locally
# registered, or no phenogram in the area yet). Below NOTABLE_SIGNIFICANCE, so an
# unknown taxon still counts toward richness/evenness but does not pile into the
# rarity term.
DEFAULT_SIGNIFICANCE = 0.3

# significance_from_cells: an occupied-cell share of 10**-SIGNIFICANCE_LOG_SPAN
# maps to 1.0; a share of 1.0 maps to 0.0.
SIGNIFICANCE_LOG_SPAN = 4.0
# In Sweden many still-common species are red-listed (declining populations), so
# red-list status *adds* to significance rather than replacing it - a widespread
# NT bird stays un-notable, a genuinely scarce one is pushed over the line, and
# the threatened categories clear the bar on their own (DEFAULT_SIGNIFICANCE +
# the VU/EN/CR bump > NOTABLE_SIGNIFICANCE).
RED_LIST_BUMP = {"NT": 0.10, "DD": 0.15, "VU": 0.25, "EN": 0.40, "CR": 0.55, "RE": 0.55}

# Recency bonus decays to zero over this many days.
RECENCY_HALFLIFE_DAYS = 10.0
RED_LIST_CATEGORIES = set(RED_LIST_BUMP)


@dataclass
class TaxonRow:
    """One taxon's presence at a candidate location."""

    taxon_id: int
    count: int
    scientific_name: str = ""
    vernacular_name: str = ""
    red_list_category: str = ""
    last_seen_days: float | None = None  # age in days of the most recent record
    significance: float | None = None    # 0..1, precomputed; None -> default

    @property
    def red_listed(self) -> bool:
        return self.red_list_category.upper() in RED_LIST_CATEGORIES

    @property
    def effective_significance(self) -> float:
        base = DEFAULT_SIGNIFICANCE if self.significance is None else self.significance
        base += RED_LIST_BUMP.get(self.red_list_category.upper(), 0.0)
        return max(0.0, min(1.0, base))


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


def significance_from_cells(species_cells: int, area_cells: int) -> float | None:
    """Rarity of a *report* of a taxon in an area, on a 0..1 scale.

    ``species_cells`` / ``area_cells`` are occupied-grid-cell counts from
    ``GeoGridAggregation`` (the taxon's footprint vs. all reporting effort in
    the area) - both effort-robust, so a twitched rarity mobbed at one spot
    fills one cell, not hundreds. Returns ``None`` when there is no effort
    baseline to divide by. Red-list status is folded in later, at scoring time
    (:attr:`TaxonRow.effective_significance`).
    """
    if area_cells <= 0:
        return None
    share = max(species_cells, 1) / area_cells
    raw = -math.log10(min(share, 1.0)) / SIGNIFICANCE_LOG_SPAN
    return round(max(0.0, min(1.0, raw)), 3)


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


def _is_notable(row: TaxonRow) -> bool:
    # effective_significance already folds in the red-list bump, so a widespread
    # NT species is not notable while a threatened or genuinely scarce one is.
    return row.effective_significance >= NOTABLE_SIGNIFICANCE


def _rarity_weight(row: TaxonRow) -> float:
    """The taxon's contribution to the rarity term: just its significance."""
    return row.effective_significance


def _recency_weight(row: TaxonRow) -> float:
    if row.last_seen_days is None:
        return 0.0
    return math.exp(-max(0.0, row.last_seen_days) / RECENCY_HALFLIFE_DAYS)


def _reason(row: TaxonRow, recency_w: float) -> str:
    parts: list[str] = []
    if row.red_listed:
        parts.append(f"red-listed ({row.red_list_category.upper()})")
    if row.effective_significance >= NOTABLE_SIGNIFICANCE and not row.red_listed:
        parts.append("rarely reported")
    if recency_w > 0.35 and row.last_seen_days is not None:
        d = int(round(row.last_seen_days))
        parts.append("seen today" if d <= 0 else f"seen {d} day{'s' if d != 1 else ''} ago")
    return "; ".join(parts) or "adds to the species mix"


def rarity_score(rows: list[TaxonRow]) -> float:
    return sum(_rarity_weight(r) for r in rows if r.count > 0 and _is_notable(r))


def recency_bonus(rows: list[TaxonRow]) -> float:
    """Sum of recency weights, but only for taxa that are actually notable -
    a fresh crow record must not light this up.
    """
    return sum(_recency_weight(r) for r in rows if r.count > 0 and _is_notable(r))


def score(
    rows: list[TaxonRow],
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
    rar = rarity_score(live)
    rec = recency_bonus(live)

    richness_term = W_RICHNESS * (corrected_richness - reference_richness)
    evenness_term = W_EVENNESS * math.log(inv_simpson) if inv_simpson > 1 else 0.0
    rarity_term = W_RARITY * rar
    recency_term = W_RECENCY * rec
    total_score = richness_term + evenness_term + rarity_term + recency_term

    contributions: list[Contribution] = []
    for r in live:
        if not _is_notable(r):
            continue
        rw = _rarity_weight(r)
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
            reason=_reason(r, cw),
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
