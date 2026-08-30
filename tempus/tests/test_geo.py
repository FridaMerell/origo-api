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

    def test_distance_along_line(self):
        total = geo.line_length_m(LINE)
        self.assertAlmostEqual(geo.distance_along_line(LINE, STOCKHOLM), 0.0, delta=1.0)
        self.assertAlmostEqual(geo.distance_along_line(LINE, UPPSALA), total, delta=1.0)
        quarter = geo.point_at_distance(LINE, total / 4)
        # a point a little off the line still projects to ~the same arc position
        off = (quarter[0] + 0.02, quarter[1])
        self.assertAlmostEqual(geo.distance_along_line(LINE, off), total / 4, delta=total * 0.05)


class BboxTests(SimpleTestCase):
    def test_centroid(self):
        self.assertEqual(geo.bbox_centroid([10.0, 50.0, 20.0, 60.0]), (15.0, 55.0))


class PointInPolygonTests(SimpleTestCase):
    # A square around Uppsala, with a hole cut out of the middle.
    SQUARE = {
        "type": "Polygon",
        "coordinates": [
            [[17.0, 59.0], [18.5, 59.0], [18.5, 60.0], [17.0, 60.0], [17.0, 59.0]],
            [[17.6, 59.5], [17.7, 59.5], [17.7, 59.6], [17.6, 59.6], [17.6, 59.5]],
        ],
    }
    MULTI = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}

    def test_inside(self):
        self.assertTrue(geo.point_in_multipolygon((17.3, 59.2), self.SQUARE))
        self.assertTrue(geo.point_in_multipolygon((17.3, 59.2), self.MULTI))

    def test_outside(self):
        self.assertFalse(geo.point_in_multipolygon((10.0, 59.2), self.SQUARE))

    def test_in_hole_counts_as_outside(self):
        self.assertFalse(geo.point_in_multipolygon((17.65, 59.55), self.SQUARE))

    def test_tolerates_empty_geometry(self):
        self.assertFalse(geo.point_in_multipolygon((17.3, 59.2), {}))
        self.assertFalse(geo.point_in_multipolygon((17.3, 59.2), None))
