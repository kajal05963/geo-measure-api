import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app import db
from app.config import get_settings
from app.schemas import FeaturesResponse, FileInfo, MeasurementsResponse
from app.services.ingest import IngestError, UnsupportedFormat
from app.services.pipeline import process_upload

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])


def _require_file(file_id: str) -> dict:
    rec = db.get_file(file_id)
    if rec is None:
        raise HTTPException(404, "File not found")
    return rec


@router.post("/", response_model=FileInfo, status_code=201)
def upload_file(file: UploadFile = File(...)):
    """Upload a .kml or a .zip containing a Shapefile; parse and measure synchronously."""
    name = file.filename or "upload"
    limit = get_settings().max_upload_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {limit // (1024 * 1024)} MB limit")

    try:
        crs, features, warnings = process_upload(name, data)
    except UnsupportedFormat as exc:
        raise HTTPException(415, str(exc))
    except IngestError as exc:
        file_id = db.save_file(name, "FAILED", error=str(exc))
        raise HTTPException(422, {"id": file_id, "status": "FAILED", "error": str(exc)})
    except Exception:
        log.exception("Unexpected failure processing %s", name)
        raise HTTPException(500, "Unexpected error while processing file")

    file_id = db.save_file(name, "COMPLETED", crs, features, warnings)
    return db.get_file(file_id)


@router.get("/", response_model=list[FileInfo])
def list_files(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return db.list_files(limit, offset)


@router.get("/{file_id}/", response_model=FileInfo)
def get_file(file_id: str):
    return _require_file(file_id)


@router.get("/{file_id}/measurements/", response_model=MeasurementsResponse)
def get_measurements(
    file_id: str,
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    _require_file(file_id)
    return {
        "file_id": file_id,
        "summary": db.measurement_summary(file_id),
        "limit": limit,
        "offset": offset,
        "results": db.list_features(file_id, limit, offset),
    }


@router.get("/{file_id}/features/", response_model=FeaturesResponse)
def get_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Full feature detail: geometry (GeoJSON, source CRS), properties and measurements."""
    _require_file(file_id)
    return {
        "file_id": file_id,
        "limit": limit,
        "offset": offset,
        "features": db.list_features(file_id, limit, offset),
    }
