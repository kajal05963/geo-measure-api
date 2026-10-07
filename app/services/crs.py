"""CRS helpers: choose a projected CRS suited to a geometry's location."""
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

WGS84 = CRS.from_epsg(4326)


@lru_cache(maxsize=256)
def _transformer(src: CRS, dst: CRS) -> Transformer:
    # always_xy => (lon, lat) / (easting, northing) regardless of authority axis order
    return Transformer.from_crs(src, dst, always_xy=True)


def reproject(geom: BaseGeometry, src: CRS, dst: CRS) -> BaseGeometry:
    return transform(_transformer(src, dst).transform, geom)


def utm_epsg_for(lon: float, lat: float) -> int:
    """UTM zone EPSG for a lon/lat; UPS (polar stereographic) beyond 84N / 80S."""
    if lat > 84:
        return 32661
    if lat < -80:
        return 32761
    zone = min(max(int((lon + 180) // 6) + 1, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone
