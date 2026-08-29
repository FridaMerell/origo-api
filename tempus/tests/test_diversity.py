from django.test import SimpleTestCase

from tempus.services import diversity
from tempus.services.diversity import TaxonRow

CROW = 103095       # Corvus cornix, hooded crow - abundant, always reported
WARBLER = 205835    # a scarce, red-listed warbler - the "interesting bird"
MALLARD = 202803
TIT = 199324


class InverseSimpsonTests(SimpleTestCase):
    def test_single_dominant_taxon_collapses_to_one(self):
        rows = [TaxonRow(CROW, 100), TaxonRow(MALLARD, 1), TaxonRow(TIT, 1)]
        self.assertLess(diversity.inverse_simpson(rows), 1.2)

    def test_even_spread_approaches_richness(self):
        rows = [TaxonRow(CROW, 10), TaxonRow(MALLARD, 10),
                TaxonRow(TIT, 10), TaxonRow(WARBLER, 10)]
        self.assertAlmostEqual(diversity.inverse_simpson(rows), 4.0, places=6)

    def test_empty(self):
        self.assertEqual(diversity.inverse_simpson([]), 0.0)


class RichnessTests(SimpleTestCase):
    def test_counts_distinct_present_taxa(self):
        rows = [TaxonRow(CROW, 5), TaxonRow(MALLARD, 0), TaxonRow(TIT, 2)]
        self.assertEqual(diversity.richness(rows), 2)


class ScoreTests(SimpleTestCase):
    def setUp(self):
        # Corridor-wide: crows and mallards everywhere, the warbler almost never.
        self.corridor_freq = diversity.corridor_frequencies({
            CROW: 5_000, MALLARD: 3_000, TIT: 1_500, WARBLER: 3,
        })

    def test_one_rare_recent_bird_beats_a_hundred_crows(self):
        crow_spot = [TaxonRow(CROW, 100, scientific_name="Corvus cornix")]
        warbler_spot = [TaxonRow(
            WARBLER, 1, scientific_name="Acrocephalus paludicola",
            vernacular_name="vattensångare",
            red_list_category="EN", last_seen_days=2,
        )]
        crow = diversity.score(crow_spot, self.corridor_freq)
        warbler = diversity.score(warbler_spot, self.corridor_freq)
        self.assertGreater(warbler.score, crow.score)

    def test_contributions_name_the_interesting_taxon(self):
        rows = [
            TaxonRow(CROW, 40, scientific_name="Corvus cornix"),
            TaxonRow(WARBLER, 1, scientific_name="Acrocephalus paludicola",
                     red_list_category="EN", last_seen_days=1),
        ]
        result = diversity.score(rows, self.corridor_freq)
        self.assertTrue(result.contributions)
        top = result.contributions[0]
        self.assertEqual(top.taxon_id, WARBLER)
        self.assertIn("red-listed", top.reason)
        self.assertIn("day", top.reason)
        # A plain crow record must not become a contribution.
        self.assertNotIn(CROW, [c.taxon_id for c in result.contributions])

    def test_fresh_common_bird_does_not_trigger_recency(self):
        rows = [TaxonRow(CROW, 3, scientific_name="Corvus cornix", last_seen_days=0)]
        result = diversity.score(rows, self.corridor_freq)
        self.assertEqual(result.recency, 0.0)

    def test_effort_correction_damps_high_volume_spots(self):
        # Same richness, 100x the reports -> the busy spot's richness term is
        # divided by a larger factor.
        self.assertGreater(diversity.effort_correction(10_000),
                           diversity.effort_correction(100))
        quiet = [TaxonRow(CROW, 1), TaxonRow(MALLARD, 1), TaxonRow(TIT, 1)]
        busy = [TaxonRow(CROW, 100), TaxonRow(MALLARD, 100), TaxonRow(TIT, 100)]
        self.assertGreater(
            diversity.score(quiet, self.corridor_freq).breakdown["corrected_richness"],
            diversity.score(busy, self.corridor_freq).breakdown["corrected_richness"],
        )
