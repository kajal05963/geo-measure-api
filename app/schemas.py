from typing import Any

from pydantic import BaseModel


class FileInfo(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: str  # COMPLETED | FAILED
    geometry_types: dict[str, int] = {}
    warnings: list[str] = []
    error: str | None = None
    created_at: str


class FeatureMeasurement(BaseModel):
    index: int
    layer: str | None
    geometry_type: str | None
    crs: str | None
    measurement_status: str  # MEASURED | NOT_REQUIRED | UNSUPPORTED | ERROR
    measurements: dict[str, float] = {}
    projected_crs: str | None = None
    note: str | None = None


class MeasurementSummary(BaseModel):
    total_area_m2: float
    total_length_m: float
    status_counts: dict[str, int]


class MeasurementsResponse(BaseModel):
    file_id: str
    summary: MeasurementSummary
    limit: int
    offset: int
    results: list[FeatureMeasurement]


class Feature(FeatureMeasurement):
    geometry: dict[str, Any] | None
    properties: dict[str, Any]


class FeaturesResponse(BaseModel):
    file_id: str
    limit: int
    offset: int
    features: list[Feature]
