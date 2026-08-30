from django.test import SimpleTestCase

from tempus.services import diversity
from tempus.services.diversity import TaxonRow

CROW = 103095       # Corvus cornix, hooded crow - abundant, always reported
WARBLER = 205835    # a scarce, red-listed warbler - the "interesting bird"
MALLARD = 202803
TIT = 199324

# Precomputed rarity (0..1) as the caller would attach it.
COMMON = 0.05
SCARCE = 0.85


class SignificanceFromCellsTests(SimpleTestCase):
    def test_widespread_species_scores_low(self):
        # occupies most cells that have any reports at all
        value = diversity.significance_from_cells(900, 1_000)
        self.assertLess(value, 0.1)

    def test_localised_species_scores_high(self):
        value = diversity.significance_from_cells(1, 10_000)
        self.assertGreater(value, 0.9)

    def test_no_effort_baseline_is_none(self):
        self.assertIsNone(diversity.significance_from_cells(5, 0))


class RedListBumpTests(SimpleTestCase):
    def test_widespread_nt_bird_stays_un_notable(self):
        row = TaxonRow(1, 5, red_list_category="NT", significance=0.05)
        self.assertLess(row.effective_significance, diversity.NOTABLE_SIGNIFICANCE)

    def test_scarce_nt_bird_is_pushed_over_the_line(self):
        row = TaxonRow(1, 5, red_list_category="NT", significance=0.45)
        self.assertGreaterEqual(row.effective_significance, diversity.NOTABLE_SIGNIFICANCE)

    def test_threatened_category_is_notable_without_data(self):
        row = TaxonRow(1, 5, red_list_category="EN")  # significance=None
        self.assertGreaterEqual(row.effective_significance, diversity.NOTABLE_SIGNIFICANCE)


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
    def test_one_rare_recent_bird_beats_a_hundred_crows(self):
        crow_spot = [TaxonRow(CROW, 100, scientific_name="Corvus cornix",
                              significance=COMMON)]
        warbler_spot = [TaxonRow(
            WARBLER, 1, scientific_name="Acrocephalus paludicola",
            vernacular_name="vattensångare",
            red_list_category="EN", last_seen_days=2, significance=SCARCE,
        )]
        self.assertGreater(
            diversity.score(warbler_spot).score, diversity.score(crow_spot).score
        )

    def test_scarce_species_beats_common_even_without_red_list(self):
        common_spot = [TaxonRow(CROW, 80, significance=COMMON)]
        scarce_spot = [TaxonRow(TIT, 3, significance=SCARCE)]
        self.assertGreater(
            diversity.score(scarce_spot).score, diversity.score(common_spot).score
        )

    def test_contributions_name_the_interesting_taxon(self):
        rows = [
            TaxonRow(CROW, 40, scientific_name="Corvus cornix", significance=COMMON),
            TaxonRow(WARBLER, 1, scientific_name="Acrocephalus paludicola",
                     red_list_category="EN", last_seen_days=1, significance=SCARCE),
        ]
        result = diversity.score(rows)
        self.assertTrue(result.contributions)
        top = result.contributions[0]
        self.assertEqual(top.taxon_id, WARBLER)
        self.assertIn("red-listed", top.reason)
        self.assertIn("day", top.reason)
        self.assertNotIn(CROW, [c.taxon_id for c in result.contributions])

    def test_unknown_significance_falls_back_to_default(self):
        row = TaxonRow(TIT, 5)  # significance=None
        self.assertEqual(row.effective_significance, diversity.DEFAULT_SIGNIFICANCE)

    def test_fresh_common_bird_does_not_trigger_recency(self):
        rows = [TaxonRow(CROW, 3, last_seen_days=0, significance=COMMON)]
        self.assertEqual(diversity.score(rows).recency, 0.0)

    def test_effort_correction_damps_high_volume_spots(self):
        self.assertGreater(diversity.effort_correction(10_000),
                           diversity.effort_correction(100))
        quiet = [TaxonRow(CROW, 1, significance=COMMON),
                 TaxonRow(MALLARD, 1, significance=COMMON),
                 TaxonRow(TIT, 1, significance=COMMON)]
        busy = [TaxonRow(CROW, 100, significance=COMMON),
                TaxonRow(MALLARD, 100, significance=COMMON),
                TaxonRow(TIT, 100, significance=COMMON)]
        self.assertGreater(
            diversity.score(quiet).breakdown["corrected_richness"],
            diversity.score(busy).breakdown["corrected_richness"],
        )
