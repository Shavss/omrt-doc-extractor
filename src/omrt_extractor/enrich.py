"""Geographic enrichment: PDOK BAG, 3D BAG, CBS, OSM.

Coordinate-driven enrichment. Takes the project centroid (auto-detect WGS84
vs RD New) and a buffer radius, queries the four open Dutch APIs, returns
a GeoContext.

Primary functions:
    enrich_geo(location, radius_m=500) -> GeoContext
    enrich_3d_bag(location, radius_m=500, lod='1.2') -> NearbyBuildingsSnapshot

GeoContext aggregates:
- nearby_buildings (NearbyBuildingsSnapshot): BAG 2D + optional 3D BAG
- demographics (NeighbourhoodDemographics): CBS buurt-level
- transit_access (TransitAccess): OSM Overpass

Hard rule from CLAUDE.md: every API call degrades gracefully. If an API
is unreachable or returns nothing useful, log via loguru, append the
api_name to GeoContext.data_sources_failed, and continue. Never raise
from a network call.

Cache all responses under data/cache/enrich/ by coordinate hash + buffer.
Hits are free; misses cost an API round-trip and an LLM-friendly summary
pass for the buildings snapshot.

Stages 4 and 4c of the build plan.
"""

from __future__ import annotations

# TODO Stage 4: implement enrich_geo (PDOK BAG, CBS, OSM)
# TODO Stage 4c: implement enrich_3d_bag (3D BAG context buildings)
