"""Tiny SQLite persistence layer (stdlib only)."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    crs TEXT,
    feature_count INTEGER NOT NULL DEFAULT 0,
    geometry_types TEXT NOT NULL DEFAULT '{}',
    warnings TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS features (
    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    layer TEXT,
    geometry_type TEXT,
    crs TEXT,
    geometry TEXT,
    properties TEXT NOT NULL,
    measurement_status TEXT NOT NULL,
    projected_crs TEXT,
    measurements TEXT NOT NULL,
    note TEXT,
    area_m2 REAL,
    length_m REAL,
    PRIMARY KEY (file_id, idx)
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = get_settings().db_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _file_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["geometry_types"] = json.loads(d["geometry_types"])
    d["warnings"] = json.loads(d["warnings"])
    return d


def save_file(
    filename: str,
    status: str,
    crs: str | None = None,
    features: list[dict] | None = None,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> str:
    """Persist a file record and its features in a single transaction."""
    features = features or []
    file_id = uuid.uuid4().hex[:12]
    types: dict[str, int] = {}
    for f in features:
        key = f["geometry_type"] or "None"
        types[key] = types.get(key, 0) + 1
    with connect() as conn:
        conn.execute(
            "INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?)",
            (file_id, filename, status, crs, len(features), json.dumps(types),
             json.dumps(warnings or []), error,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.executemany(
            "INSERT INTO features VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (file_id, f["index"], f["layer"], f["geometry_type"], f["crs"],
                 json.dumps(f["geometry"]), json.dumps(f["properties"]),
                 f["measurement_status"], f["projected_crs"],
                 json.dumps(f["measurements"]), f["note"],
                 f["measurements"].get("area_m2"), f["measurements"].get("length_m"))
                for f in features
            ],
        )
    return file_id


def get_file(file_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _file_row(row) if row else None


def list_files(limit: int, offset: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM files ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [_file_row(r) for r in rows]


def list_features(file_id: str, limit: int, offset: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM features WHERE file_id = ? ORDER BY idx LIMIT ? OFFSET ?",
            (file_id, limit, offset),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["index"] = d.pop("idx")
        for k in ("geometry", "properties", "measurements"):
            d[k] = json.loads(d[k])
        out.append(d)
    return out


def measurement_summary(file_id: str) -> dict:
    with connect() as conn:
        tot = conn.execute(
            "SELECT COALESCE(SUM(area_m2),0) a, COALESCE(SUM(length_m),0) l "
            "FROM features WHERE file_id = ?", (file_id,)
        ).fetchone()
        by_status = conn.execute(
            "SELECT measurement_status s, COUNT(*) c FROM features "
            "WHERE file_id = ? GROUP BY s", (file_id,)
        ).fetchall()
    return {
        "total_area_m2": round(tot["a"], 4),
        "total_length_m": round(tot["l"], 4),
        "status_counts": {r["s"]: r["c"] for r in by_status},
    }
