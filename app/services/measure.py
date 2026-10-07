"""Measurement calculation. Never computes metrics in degrees."""
from typing import Any

import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.services.crs import WGS84, reproject, utm_epsg_for

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}

# measurement_status values
MEASURED = "MEASURED"
NOT_REQUIRED = "NOT_REQUIRED"
UNSUPPORTED = "UNSUPPORTED"
ERROR = "ERROR"


def _result(status: str, measurements=None, projected_crs=None, note=None) -> dict[str, Any]:
    return {
        "measurement_status": status,
        "measurements": measurements or {},
        "projected_crs": projected_crs,
        "note": note,
    }


def measure_geometry(geom: BaseGeometry | None, src_crs: CRS) -> dict[str, Any]:
    """Measure one geometry.

    Flow: source CRS -> WGS84 (to locate the feature) -> local UTM zone -> metric calc.
    Always returns a dict; failures are reported via ``measurement_status``.
    """
    if geom is None or geom.is_empty:
        return _result(UNSUPPORTED, note="Null or empty geometry")

    gtype = geom.geom_type
    if gtype in POINT_TYPES:
        return _result(NOT_REQUIRED, note="No measurement defined for points")
    if gtype not in AREA_TYPES | LENGTH_TYPES:
        return _result(UNSUPPORTED, note=f"Measurement not supported for {gtype}")

    try:
        geom = shapely.force_2d(geom)
        wgs = reproject(geom, src_crs, WGS84)
        note = None
        if gtype in AREA_TYPES and not shapely.is_valid(wgs):
            note = "Invalid geometry (e.g. self-intersection); area may be unreliable"
        minx, miny, maxx, maxy = wgs.bounds
        epsg = utm_epsg_for((minx + maxx) / 2, (miny + maxy) / 2)
        projected = CRS.from_epsg(epsg)
        metric = reproject(wgs, WGS84, projected)

        if gtype in AREA_TYPES:
            m = {
                "area_m2": round(metric.area, 4),
                "area_ha": round(metric.area / 10_000, 6),
                "perimeter_m": round(metric.length, 4),
            }
        else:
            m = {"length_m": round(metric.length, 4), "length_km": round(metric.length / 1000, 6)}
        if not all(_finite(v) for v in m.values()):
            return _result(ERROR, note="Non-finite result; check coordinates and CRS")
        return _result(MEASURED, m, f"EPSG:{epsg}", note)
    except Exception as exc:  # one bad feature must not fail the whole file
        return _result(ERROR, note=f"Measurement failed: {exc}")


def _finite(v: float) -> bool:
    return v == v and v not in (float("inf"), float("-inf"))
