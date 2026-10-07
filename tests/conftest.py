import io
import os
import tempfile
import zipfile

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

os.environ["GEO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>plot</name><description>test plot</description>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      77.0,17.0 77.01,17.0 77.01,17.01 77.0,17.01 77.0,17.0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>road</name>
    <LineString><coordinates>77.0,17.0 77.0,17.01</coordinates></LineString></Placemark>
  <Placemark><name>well</name><Point><coordinates>77.0,17.0</coordinates></Point></Placemark>
  <Placemark><name>mix</name><MultiGeometry>
    <Point><coordinates>77.0,17.0</coordinates></Point>
    <LineString><coordinates>77.0,17.0 77.1,17.1</coordinates></LineString>
  </MultiGeometry></Placemark>
</Document></kml>"""


def shapefile_zip(*gdfs: gpd.GeoDataFrame, with_prj: bool = True) -> bytes:
    """Zip one shapefile per GeoDataFrame (shapefiles cannot mix geometry types)."""
    with tempfile.TemporaryDirectory() as d:
        for i, gdf in enumerate(gdfs):
            gdf.to_file(os.path.join(d, f"layer{i}.shp"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for f in sorted(os.listdir(d)):
                if f.endswith(".prj") and not with_prj:
                    continue
                zf.write(os.path.join(d, f), f)
        return buf.getvalue()


@pytest.fixture
def kml_bytes():
    return KML.encode()


@pytest.fixture
def utm_zip():
    # 100 m x 200 m rectangle, 500 m line and a point in EPSG:32643 (projected, metres)
    crs = "EPSG:32643"
    rect = Polygon([(500000, 1880000), (500100, 1880000), (500100, 1880200), (500000, 1880200)])
    return shapefile_zip(
        gpd.GeoDataFrame({"name": ["rect"]}, geometry=[rect], crs=crs),
        gpd.GeoDataFrame({"name": ["line"]}, geometry=[LineString([(500000, 1880000), (500300, 1880400)])], crs=crs),
        gpd.GeoDataFrame({"name": ["pt"]}, geometry=[Point(500000, 1880000)], crs=crs),
    )
