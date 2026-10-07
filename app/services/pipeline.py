"""Glue: parse upload -> measure each feature -> plain records ready to store."""
from app.services.ingest import RawFeature, read_upload
from app.services.measure import measure_geometry


def crs_label(crs) -> str:
    auth = crs.to_authority(min_confidence=70)
    return f"{auth[0]}:{auth[1]}" if auth else (crs.name or "UNKNOWN")


def process_upload(filename: str, data: bytes) -> tuple[str | None, list[dict], list[str]]:
    raw: list[RawFeature] = read_upload(filename, data)
    records: list[dict] = []
    for i, f in enumerate(raw):
        result = measure_geometry(f.geometry, f.crs)
        records.append(
            {
                "index": i,
                "layer": f.layer,
                "geometry_type": f.geometry.geom_type if f.geometry is not None else None,
                "crs": crs_label(f.crs),
                "geometry": f.geojson,
                "properties": f.properties,
                **result,
            }
        )
    crs_set = sorted({r["crs"] for r in records})
    file_crs = crs_set[0] if len(crs_set) == 1 else ("MIXED" if crs_set else None)
    warnings = []
    if not records:
        warnings.append("File contained no features")
    if len(crs_set) > 1:
        warnings.append(f"Layers use different CRSs: {', '.join(crs_set)}")
    return file_crs, records, warnings
