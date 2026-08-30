# Geography and GeoJSON

Tempus stores geographic values as GeoJSON in ordinary Django `JSONField`s.
Coordinates use WGS 84 and **longitude, latitude** order.

| Model field | Required geometry |
|---|---|
| `GeoArea.geometry` | `MultiPolygon` |
| `Route.geometry` | `LineString` |
| `RouteStop.location` | `Point` |
| `Observation.location` | `Point` |

Examples:

```json
{"type": "Point", "coordinates": [14.1567, 56.0294]}
```

```json
{
  "type": "LineString",
  "coordinates": [[14.15, 56.02], [14.22, 56.08]]
}
```

Serializers validate the geometry object type and require `coordinates`.
Detailed coordinate ranges, polygon topology, self-intersections, and native
database spatial operations are not currently validated by PostGIS.

## GeoArea

`GeoArea` has name, kind, two-letter country code, and MultiPolygon. Supported
kinds are country, county, province, nature reserve, and biological area.

Areas are shared reference data: authenticated users can read them, while
writes require staff. They scope phenograms and can be attached to checklists.

## Use by feature

- Phenograms send an area's geometry as an SOS geography filter.
- Route suggestions sample points along a LineString and search within
  `corridor_metres` of each point.
- Observations and route stops store user-entered Points.
- Checklist geography is context; automatic completion currently matches
  species and date, not polygon containment.

Because storage is JSON-based, geographic overlap, containment, route
buffering, and distance calculations live in application services rather than
database spatial indexes.

