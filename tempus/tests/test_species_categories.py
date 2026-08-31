from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from tempus.models import Species, SpeciesCategory, SpeciesCategoryMembership
from tempus.serializers import SpeciesCategorySerializer
from tempus.views import SpeciesCategoryViewSet

try:
    from django.contrib.auth import get_user_model
    User = get_user_model()
except Exception:  # pragma: no cover
    User = None


class SpeciesCategoryMembershipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="x")
        self.species = Species.objects.create(
            dyntaxa_taxon_id=1,
            scientific_name="Test species",
        )
        self.category_a = SpeciesCategory.objects.create(
            label="Category A",
            taxon_id=100,
        )
        self.category_b = SpeciesCategory.objects.create(
            label="Category B",
            taxon_id=101,
        )
        self.category_c = SpeciesCategory.objects.create(
            label="Category C",
            taxon_id=102,
            parent_category=self.category_a,
        )

    def test_species_can_belong_to_multiple_categories(self):
        SpeciesCategoryMembership.objects.create(
            category=self.category_a,
            species=self.species,
        )
        SpeciesCategoryMembership.objects.create(
            category=self.category_b,
            species=self.species,
        )

        self.assertEqual(self.species.categories.count(), 2)
        self.assertCountEqual(
            self.species.categories.values_list("label", flat=True),
            ["Category A", "Category B"],
        )
        self.assertFalse(self.category_a.is_primary)
        self.assertFalse(self.category_b.is_primary)

    def test_category_primary_is_serialized_and_editable(self):
        self.category_b.is_primary = True
        self.category_b.save(update_fields=["is_primary"])

        serializer = SpeciesCategorySerializer(instance=self.category_b)
        self.assertTrue(serializer.data["is_primary"])

    def test_parent_category_includes_child_species(self):
        SpeciesCategoryMembership.objects.create(
            category=self.category_c,
            species=self.species,
        )

        serializer = SpeciesCategorySerializer(instance=self.category_a)

        self.assertEqual(serializer.data["species"], [str(self.species.pk)])
        self.assertEqual(serializer.data["species_count"], 1)

    def test_parent_category_cannot_form_a_cycle(self):
        self.category_b.parent_category = self.category_a
        self.category_b.save(update_fields=["parent_category"])

        serializer = SpeciesCategorySerializer(
            instance=self.category_a,
            data={"parent_category": self.category_b.pk},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("parent_category", serializer.errors)

    def test_viewset_filters_and_orders_categories(self):
        factory = APIRequestFactory()
        request = factory.get(
            "/species-categories/",
            {"parent_category": str(self.category_a.pk), "ordering": "-label"},
        )
        force_authenticate(request, user=self.user)

        response = SpeciesCategoryViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["label"] for item in response.data], ["Category C"])
