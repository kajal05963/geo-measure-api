# Geospatial File Measurement API

A FastAPI service that accepts a **Shapefile (`.zip`)** or **KML** file, extracts every feature
(ID, geometry type, geometry, CRS, properties) and returns **area / length measurements**
computed in a *projected* CRS — never in degrees.

## Setup

Requires Python 3.10+ (developed on 3.12). Wheels for GeoPandas / pyogrio / pyproj bundle GDAL and PROJ,
so no system GDAL install is needed.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload          # http://localhost:8000
pytest -q                              # run the tests
```

Interactive docs: <http://localhost:8000/docs>. Or with Docker:
`docker build -t geo-api . && docker run -p 8000:8000 geo-api`.

Configuration (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `GEO_DB_PATH` | `data/geo.db` | SQLite file |
| `GEO_MAX_UPLOAD_MB` | `50` | Max upload size (413 above this) |
| `GEO_MAX_UNCOMPRESSED_MB` | `300` | Max total uncompressed zip size (zip-bomb guard) |
| `GEO_MAX_ZIP_MEMBERS` | `200` | Max files inside a zip |

Try it: `curl -F "file=@samples/survey.kml" localhost:8000/api/files/`

## API

| Method | Path | Description |
|---|---|---|
| POST | `/api/files/` | Upload + process a `.kml` or `.zip` (multipart field `file`) |
| GET | `/api/files/` | List uploaded files (`limit`, `offset`) |
| GET | `/api/files/{id}/` | File information |
| GET | `/api/files/{id}/measurements/` | Per-feature measurements + summary (`limit`≤5000, `offset`) |
| GET | `/api/files/{id}/features/` | Full detail: GeoJSON geometry (source CRS), properties, measurements |
| GET | `/health` | Liveness check |

### `POST /api/files/` → 201
```json
{
  "id": "e4b7ac7e9eed",
  "filename": "survey.kml",
  "feature_count": 4,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "geometry_types": {"Polygon": 1, "LineString": 1, "Point": 1, "GeometryCollection": 1},
  "warnings": [],
  "error": null,
  "created_at": "2026-10-07T06:23:41.667241+00:00"
}
```
Errors: `415` unsupported extension · `413` too large · `422` unreadable/invalid file
(e.g. bad zip, no `.shp`, shapefile without `.prj`; a `FAILED` record is stored and its id returned in `detail.id`)
· `404` unknown id.

### `GET /api/files/{id}/measurements/`
```json
{
  "file_id": "e4b7ac7e9eed",
  "summary": {"total_area_m2": 1178825.216, "total_length_m": 1106.8708,
              "status_counts": {"MEASURED": 2, "NOT_REQUIRED": 1, "UNSUPPORTED": 1}},
  "limit": 1000, "offset": 0,
  "results": [
    {"index": 0, "layer": "upload", "geometry_type": "Polygon", "crs": "EPSG:4326",
     "measurement_status": "MEASURED",
     "measurements": {"area_m2": 1178825.216, "area_ha": 117.882522, "perimeter_m": 4343.756},
     "projected_crs": "EPSG:32643", "note": null},
    {"index": 1, "layer": "upload", "geometry_type": "LineString", "crs": "EPSG:4326",
     "measurement_status": "MEASURED",
     "measurements": {"length_m": 1106.8708, "length_km": 1.106871},
     "projected_crs": "EPSG:32643", "note": null},
    {"index": 2, "geometry_type": "Point", "measurement_status": "NOT_REQUIRED",
     "measurements": {}, "projected_crs": null, "note": "No measurement defined for points"},
    {"index": 3, "geometry_type": "GeometryCollection", "measurement_status": "UNSUPPORTED",
     "measurements": {}, "projected_crs": null,
     "note": "Measurement not supported for GeometryCollection"}
  ]
}
```
`measurement_status` is one of `MEASURED`, `NOT_REQUIRED` (points), `UNSUPPORTED`
(GeometryCollection, null/empty geometry) or `ERROR` (per-feature failure). Units: metres, m², hectares, km.

## Architecture

```
app/
  main.py            FastAPI app + lifespan (DB init)
  api/files.py       HTTP layer: validation, status codes, pagination
  schemas.py         Pydantic response models
  db.py              SQLite persistence (files, features)
  config.py          Env-driven settings
  services/
    ingest.py        Zip/KML -> RawFeature list (safe extraction, CRS detection)
    crs.py           Transformer cache, UTM zone selection
    measure.py       Geometry -> measurements (pure function, no I/O)
    pipeline.py      ingest -> measure -> storable records
tests/               pytest suite (API + accuracy checks against pyproj.Geod)
```

**File-processing flow**
1. `POST /api/files/` reads the upload (size-capped) and dispatches on extension.
2. KML is written to a temp file; a zip is extracted safely (only `.shp/.shx/.dbf/.prj/.cpg`,
   zip-slip check, member-count and uncompressed-size limits).
3. Every layer of every datasource is read with GeoPandas/pyogrio (KML folders = layers; a zip may hold several `.shp`).
4. Each feature becomes a record: index, layer, geometry type, GeoJSON geometry, CRS, properties.
5. Records and measurements are stored in one transaction; the file is `COMPLETED`. Unreadable input is stored as `FAILED`.

**Measurement flow** (`measure_geometry`)
1. Null/empty → `UNSUPPORTED`; Point/MultiPoint → `NOT_REQUIRED`; other non-areal/linear types → `UNSUPPORTED`.
2. Polygon/MultiPolygon → area (holes subtracted), hectares, perimeter. LineString/MultiLineString → length.
3. Any exception on a feature is caught and reported as `ERROR` for that feature only.

**CRS handling**
- KML is WGS84 by spec. Shapefiles use their `.prj`; **a missing `.prj` is rejected** rather than guessed.
- Each feature is reprojected to WGS84 to locate it, then to the **UTM zone of its bounding-box centre**
  (`EPSG:326xx` north / `327xx` south; UPS polar stereographic beyond 84°N / 80°S). Measurements are computed there
  and the `projected_crs` used is returned with every feature.
- Works the same for geographic and already-projected inputs. Transformers use `always_xy=True` to avoid axis-order bugs and are cached.
- Tests compare results with ellipsoidal (geodesic) values from `pyproj.Geod`; UTM agrees within 0.5% (typically ~0.1%).

## Design Decisions

| Decision | Why / alternatives considered |
|---|---|
| **FastAPI** over Django+DRF | Lightweight, typed, auto OpenAPI docs; no ORM/admin needed for this scope. |
| **Per-feature UTM zone** | Simple and accurate (<0.1% distortion inside a zone). Alternatives: a per-feature Lambert Azimuthal Equal-Area CRS (exact area, but less intuitive and not a standard EPSG code), or direct geodesic calculation with `Geod` (most accurate, but the brief asks for projection). A single per-file CRS would be wrong for datasets spanning zones. |
| **Synchronous processing** | Simpler, immediate result. The `status` field and endpoints are already shaped for async (see future scope). |
| **SQLite via stdlib** | Zero setup. A repository-style `db.py` makes swapping to Postgres/PostGIS straightforward. Original uploads are not retained, only parsed features. |
| **GeoPandas + pyogrio** | One reader for Shapefile and KML, handles encodings/types; `to_json` yields JSON-safe properties (NaN, timestamps). Alternatives: `fastkml` / `pyshp` (lighter, but two code paths and less robust). |
| **Reject missing `.prj`** | Guessing a CRS silently produces wrong areas. Explicit failure is safer. |
| **Unsupported ≠ failure** | Features get an explicit `measurement_status`, so a single odd geometry never fails a whole file. |
| **Security** | Whitelisted zip members, zip-slip guard, size/member limits, temp dirs cleaned up automatically. |

## Learnings

- Shapefiles can't mix geometry types and KML folders map to GDAL layers, so a layer-based reader handles both.
- Degrees-based area is wildly wrong; the unit tests guard against it by comparing with geodesic results.
- CRS pitfalls: axis order (`always_xy`), missing `.prj`, and choosing the zone from the feature location rather than the file.
- Zip uploads are an attack surface (zip-slip, zip bombs) and need explicit guards.

## Future Scope

- Background processing (Celery/RQ) with `PENDING → PROCESSING → COMPLETED/FAILED` and polling/webhooks for large files.
- PostGIS storage with spatial indexes, bbox queries and a GeoJSON export endpoint.
- More formats: KMZ, GeoJSON, GeoPackage; Z-aware (3D) lengths; ellipsoidal measurement as a selectable method.
- Antimeridian-crossing and multi-zone features (split, or use an equal-area CRS); optional geometry repair (`make_valid`).
- Auth, rate limiting, upload retention/cleanup, structured logging and metrics, CI (GitHub Actions) and Alembic migrations.
