"""Registry of the external data sources prefetched for a Locale's padded area.

``tasks.fetch_locale_land_cover``, ``LocaleViewSet.land_cover_fetch`` and
``LandCoverFetchAdmin`` all iterate ``SOURCES`` instead of naming each source
themselves, so adding one is: write its fetch function, add a
``LandCoverFetch`` field for it (this needs a migration), and append one
``LocaleSource`` below.

"""

from dataclasses import dataclass
from typing import Any, Callable

from tempus.services import lantmateriet, openstreetmap, trafikverket

Bbox = tuple[float, float, float, float]


@dataclass(frozen=True)
class LocaleSource:
    key: str
    field: str
    label: str
    fetch: Callable[[dict[str, Any], Bbox], dict[str, Any]]


SOURCES: tuple[LocaleSource, ...] = (
    LocaleSource(
        key="land_cover",
        field="result",
        label="Land cover",
        fetch=lambda geometry, bbox: lantmateriet.land_cover_map(geometry),
    ),
    LocaleSource(
        key="hydrography",
        field="hydrography",
        label="Hydrography",
        fetch=lambda geometry, bbox: lantmateriet.hydrography_map(geometry),
    ),
    LocaleSource(
        key="place_names",
        field="place_names",
        label="Place names",
        fetch=lambda geometry, bbox: openstreetmap.place_names_in_geometry(geometry),
    ),
    LocaleSource(
        key="buildings",
        field="buildings",
        label="Buildings",
        fetch=lambda geometry, bbox: openstreetmap.buildings_in_geometry(geometry),
    ),
    LocaleSource(
        key="roads",
        field="roads",
        label="Roads",
        fetch=lambda geometry, bbox: trafikverket.roads_in_geometry(geometry),
    ),
)
