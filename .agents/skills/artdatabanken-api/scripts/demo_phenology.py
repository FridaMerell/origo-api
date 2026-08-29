"""Runnable, no-network demo of scripts/phenology.py.

    python demo_phenology.py

Generates synthetic observation records for an imaginary spring butterfly in one
area, builds its phenogram, and prints the activity window, the seasonal limb at
a few weeks, an in-season score, and the per-year status machine -- exactly the
pieces Feature 1 / Feature 2 rely on. Also shows how `decluster()` neutralises a
mobbed rarity. See references/examples.md and references/seasonality.md.
"""

from __future__ import annotations

import datetime as dt
import random

import phenology as ph


def synthetic_history(years=range(2015, 2025), peak_week=20, spread=3.0, per_year=180):
    """Records for a univoltine spring flier, adults ~weeks 14-26."""
    rng = random.Random(42)
    recs = []
    for y in years:
        for _ in range(per_year):
            wk = round(rng.gauss(peak_week, spread))
            wk = max(1, min(52, wk))
            d = dt.date.fromisocalendar(y, wk, rng.randint(1, 7))
            recs.append({
                "taxon": {"id": 101664},
                "event": {"startDate": d.isoformat()},
                "location": {"decimalLatitude": 59.0 + rng.random(),
                             "decimalLongitude": 17.0 + rng.random()},
            })
    return recs


def sparkline(hist: ph.Phenogram) -> str:
    levels = " .:-=+oO#"          # ASCII, safe on any console
    hi = max(hist.values()) or 1.0
    return "".join(levels[min(8, int(round(hist[w] / hi * 8)))] for w in ph.WEEKS)


def main() -> None:
    recs = synthetic_history()
    print(f"synthetic history: {len(recs)} records, 2015-2024\n")

    curve = ph.smooth(ph.phenogram(ph.decluster(recs)), 1)
    lo, hi = ph.activity_window(curve)
    pk = ph.peak_week(curve)

    print("phenogram (ISO weeks 1..52):")
    print("  " + sparkline(curve))
    print(f"  {'^':>{lo+1}}{'-' * (hi - lo)}^   window weeks {lo}-{hi}, peak {pk}\n")

    for wk in (12, lo, pk, hi, 34):
        print(f"  week {wk:>2}: limb={ph.limb(curve, wk):<10} "
              f"score(unseen)={ph.in_season_score(curve, wk, weeks_of_data=10):.3f}")

    print("\nper-year status (window "
          f"{lo}-{hi}), pretend today is ISO week {pk - 2}:")
    today_wk = pk - 2
    cases = [
        ("not reported yet", False, None),
        ("first seen this week", True, today_wk),
        ("seen a month ago", True, today_wk - 4),
    ]
    for label, seen, first in cases:
        st = ph.season_status((lo, hi), today_wk,
                              reported_this_year=seen, first_week_this_year=first)
        print(f"  {label:<22} -> {st}")

    print("\ndecluster vs raw (300 twitchers on one bird, one spot, one day):")
    spot = {"taxon": {"id": 9}, "event": {"startDate": "2024-06-10"},
            "location": {"decimalLatitude": 59.1, "decimalLongitude": 17.2}}
    mob = [dict(spot) for _ in range(300)]
    print(f"  raw report count : {sum(ph.phenogram(ph.sos_record_dates(mob)).values()):.0f}")
    print(f"  declustered      : {sum(ph.phenogram(ph.decluster(mob)).values()):.0f}")


if __name__ == "__main__":
    main()
