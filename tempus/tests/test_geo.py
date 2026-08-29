from django.test import SimpleTestCase

from tempus.services import geo

# Stockholm C -> Uppsala C, roughly 63 km apart.
STOCKHOLM = (18.0649, 59.3293)
UPPSALA = (17.6389, 59.8586)
LINE = [STOCKHOLM, UPPSALA]


class HaversineTests(SimpleTestCase):
    def test_known_distance(self):
        d = geo.haversine_m(STOCKHOLM[1], STOCKHOLM[0], UPPSALA[1], UPPSALA[0])
        self.assertAlmostEqual(d, 63_000, delta=3_000)

    def test_zero_distance(self):
        self.assertEqual(geo.haversine_m(59.0, 18.0, 59.0, 18.0), 0.0)


class DensifyTests(SimpleTestCase):
    def test_endpoints_preserved(self):
        pts = geo.densify(LINE, 10_000)
        self.assertEqual(pts[0], STOCKHOLM)
        self.assertAlmostEqual(pts[-1][0], UPPSALA[0], places=6)
        self.assertAlmostEqual(pts[-1][1], UPPSALA[1], places=6)

    def test_spacing_within_tolerance(self):
        spacing = 5_000
        pts = geo.densify(LINE, spacing)
        gaps = [
            geo.haversine_m(a[1], a[0], b[1], b[0])
            for a, b in zip(pts, pts[1:])
        ]
        for gap in gaps:
            self.assertLessEqual(gap, spacing * 1.05)
        self.assertGreaterEqual(len(pts), 13)

    def test_rejects_non_positive_spacing(self):
        with self.assertRaises(ValueError):
            geo.densify(LINE, 0)


class SnapTests(SimpleTestCase):
    def test_point_on_line_has_zero_offset(self):
        mid = geo.point_at_distance(LINE, geo.line_length_m(LINE) / 2)
        _snapped, distance = geo.nearest_point_on_line(LINE, mid)
        self.assertLess(distance, 1.0)

    def test_snap_towards_pulls_far_point_in(self):
        # ~1 degree east of the mid-route point is far off the corridor.
        mid = geo.point_at_distance(LINE, geo.line_length_m(LINE) / 2)
        far = (mid[0] + 1.0, mid[1])
        snapped = geo.snap_towards(far, LINE, max_offset_m=2_000)
        self.assertLess(abs(snapped[0] - mid[0]), abs(far[0] - mid[0]))

    def test_snap_towards_keeps_near_point(self):
        mid = geo.point_at_distance(LINE, geo.line_length_m(LINE) / 2)
        near = (mid[0] + 0.0001, mid[1])
        self.assertEqual(geo.snap_towards(near, LINE, max_offset_m=2_000), near)


class BboxTests(SimpleTestCase):
    def test_centroid(self):
        self.assertEqual(geo.bbox_centroid([10.0, 50.0, 20.0, 60.0]), (15.0, 55.0))
