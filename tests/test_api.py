import pytest
from pyproj import Geod
from shapely.geometry import Polygon

from tests.conftest import shapefile_zip
import geopandas as gpd

GEOD = Geod(ellps="WGS84")


def upload(client, name, data):
    return client.post("/api/files/", files={"file": (name, data)})


def test_kml_upload_and_measurements(client, kml_bytes):
    r = upload(client, "survey.kml", kml_bytes)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["status"] == "COMPLETED"
    assert info["crs"] == "EPSG:4326"
    assert info["feature_count"] == 4

    assert client.get(f"/api/files/{info['id']}/").json()["filename"] == "survey.kml"

    body = client.get(f"/api/files/{info['id']}/measurements/").json()
    by_type = {m["geometry_type"]: m for m in body["results"]}

    # polygon area must match the geodesic (ellipsoidal) area to within 0.5%
    poly = Polygon([(77, 17), (77.01, 17), (77.01, 17.01), (77, 17.01)])
    geodesic_area = abs(GEOD.geometry_area_perimeter(poly)[0])
    area = by_type["Polygon"]["measurements"]["area_m2"]
    assert area == pytest.approx(geodesic_area, rel=5e-3)
    assert by_type["Polygon"]["projected_crs"] == "EPSG:32643"
    assert area > 1_000  # sanity: metres, not degrees (0.0001 deg^2)

    length = by_type["LineString"]["measurements"]["length_m"]
    assert length == pytest.approx(GEOD.line_length([77, 77], [17, 17.01]), rel=5e-3)

    assert by_type["Point"]["measurement_status"] == "NOT_REQUIRED"
    # mixed geometry collection is handled gracefully, not a crash
    assert by_type["GeometryCollection"]["measurement_status"] == "UNSUPPORTED"
    assert body["summary"]["status_counts"]["UNSUPPORTED"] == 1


def test_projected_shapefile(client, utm_zip):
    r = upload(client, "parcels.zip", utm_zip)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["crs"] == "EPSG:32643"
    res = client.get(f"/api/files/{info['id']}/measurements/").json()["results"]
    by_type = {m["geometry_type"]: m for m in res}
    assert by_type["Polygon"]["measurements"]["area_m2"] == pytest.approx(20_000, rel=2e-3)
    assert by_type["LineString"]["measurements"]["length_m"] == pytest.approx(500, rel=2e-3)


def test_features_endpoint_returns_geometry_and_properties(client, kml_bytes):
    fid = upload(client, "a.kml", kml_bytes).json()["id"]
    feats = client.get(f"/api/files/{fid}/features/").json()["features"]
    assert feats[0]["geometry"]["type"] == "Polygon"
    assert feats[0]["properties"]["Name"] == "plot"


def test_pagination(client, kml_bytes):
    fid = upload(client, "a.kml", kml_bytes).json()["id"]
    body = client.get(f"/api/files/{fid}/measurements/?limit=2&offset=1").json()
    assert [m["index"] for m in body["results"]] == [1, 2]


def test_wgs84_shapefile_polygon_not_in_degrees(client):
    gdf = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])], crs="EPSG:4326"
    )
    fid = upload(client, "deg.zip", shapefile_zip(gdf)).json()["id"]
    area = client.get(f"/api/files/{fid}/measurements/").json()["results"][0]["measurements"]["area_m2"]
    assert area == pytest.approx(1.2308e8, rel=5e-3)  # ~123 km2 at the equator


def test_missing_prj_is_rejected(client):
    gdf = gpd.GeoDataFrame(geometry=[Polygon([(0, 0), (1, 0), (1, 1)])], crs="EPSG:4326")
    r = upload(client, "noprj.zip", shapefile_zip(gdf, with_prj=False))
    assert r.status_code == 422
    fid = r.json()["detail"]["id"]
    assert client.get(f"/api/files/{fid}/").json()["status"] == "FAILED"


def test_bad_inputs(client):
    assert upload(client, "x.geojson", b"{}").status_code == 415
    assert upload(client, "x.zip", b"not a zip").status_code == 422
    assert upload(client, "x.kml", b"<not-kml").status_code == 422
    assert client.get("/api/files/nope/").status_code == 404
    assert client.get("/api/files/nope/measurements/").status_code == 404


def test_zip_slip_rejected(client):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.shp", b"x")
    r = upload(client, "slip.zip", buf.getvalue())
    assert r.status_code == 422
    assert "unsafe" in r.json()["detail"]["error"]
