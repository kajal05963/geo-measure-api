"""Read Shapefile (.zip) and KML uploads into raw features."""
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import geopandas as gpd
import pyogrio
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.config import get_settings

SHAPEFILE_PARTS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


class IngestError(Exception):
    """User-facing problem with the uploaded file (maps to HTTP 422)."""


class UnsupportedFormat(IngestError):
    """Extension is neither .zip nor .kml (maps to HTTP 415)."""


@dataclass
class RawFeature:
    layer: str
    geometry: BaseGeometry | None
    geojson: dict[str, Any] | None
    properties: dict[str, Any]
    crs: CRS


def read_upload(filename: str, data: bytes) -> list[RawFeature]:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in (".kml", ".zip"):
        raise UnsupportedFormat("Only .zip (Shapefile) and .kml files are supported")
    with tempfile.TemporaryDirectory(prefix="geo_") as tmp:
        if ext == ".kml":
            path = os.path.join(tmp, "upload.kml")
            with open(path, "wb") as fh:
                fh.write(data)
            paths = [path]
            default_crs: CRS | None = CRS.from_epsg(4326)  # KML is WGS84 by spec
        else:
            paths = _extract_shapefiles(data, tmp)
            default_crs = None  # a missing .prj must be reported, not guessed

        features: list[RawFeature] = []
        for p in paths:
            features.extend(_read_datasource(p, default_crs))
        return features


def _extract_shapefiles(data: bytes, dest: str) -> list[str]:
    cfg = get_settings()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IngestError("Upload is not a valid zip archive") from exc

    members = [m for m in zf.infolist() if not m.is_dir()]
    if len(members) > cfg.max_zip_members:
        raise IngestError("Zip contains too many files")
    if sum(m.file_size for m in members) > cfg.max_uncompressed_bytes:
        raise IngestError("Zip expands beyond the allowed size")

    root = os.path.realpath(dest)
    for m in members:
        pure = PurePosixPath(m.filename)
        if pure.suffix.lower() not in SHAPEFILE_PARTS or "__MACOSX" in pure.parts:
            continue  # ignore everything that is not a shapefile component
        target = os.path.realpath(os.path.join(root, *pure.parts))
        if os.path.commonpath([root, target]) != root:  # zip-slip guard
            raise IngestError("Zip contains an unsafe path")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(m) as src, open(target, "wb") as out:
            out.write(src.read())

    shps = sorted(
        os.path.join(d, f)
        for d, _, files in os.walk(root)
        for f in files
        if f.lower().endswith(".shp")
    )
    if not shps:
        raise IngestError("Zip does not contain a .shp file")
    return shps


def _read_datasource(path: str, default_crs: CRS | None) -> list[RawFeature]:
    try:
        layers = [row[0] for row in pyogrio.list_layers(path)]
    except Exception as exc:
        raise IngestError(f"Could not open {os.path.basename(path)}: {exc}") from exc

    out: list[RawFeature] = []
    for layer in layers:
        try:
            gdf = gpd.read_file(path, layer=layer, engine="pyogrio")
        except Exception as exc:
            raise IngestError(f"Could not read layer '{layer}': {exc}") from exc
        if gdf.empty:
            continue
        crs = gdf.crs or default_crs
        if crs is None:
            raise IngestError(
                f"'{os.path.basename(path)}' has no CRS (missing .prj); cannot measure safely"
            )
        # to_json handles NaN, timestamps, numpy types -> plain JSON-safe values
        feats = json.loads(gdf.to_json(drop_id=True))["features"]
        name = os.path.basename(path) if path.endswith(".shp") else layer
        crs = CRS.from_user_input(crs)
        for geom, feat in zip(gdf.geometry, feats):
            out.append(RawFeature(name, geom, feat["geometry"], feat["properties"] or {}, crs))
    return out
