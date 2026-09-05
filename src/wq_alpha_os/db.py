from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .config import Settings


SCHEMA_VERSION = 2


DDL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_snapshots (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    region TEXT,
    universe_name TEXT,
    delay INTEGER,
    raw_directory TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_key TEXT PRIMARY KEY,
    dataset_id TEXT,
    name TEXT NOT NULL,
    category TEXT,
    region TEXT,
    universe_name TEXT,
    delay INTEGER,
    field_count INTEGER,
    coverage REAL,
    date_coverage REAL,
    value_score REAL,
    alpha_count INTEGER,
    raw_json TEXT NOT NULL,
    snapshot_id TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES catalog_snapshots(id)
);

CREATE TABLE IF NOT EXISTS fields (
    field_key TEXT PRIMARY KEY,
    field_id TEXT,
    name TEXT NOT NULL,
    dataset_id TEXT,
    dataset_name TEXT,
    category TEXT,
    description TEXT,
    data_type TEXT,
    region TEXT,
    universe_name TEXT,
    delay INTEGER,
    coverage REAL,
    date_coverage REAL,
    alpha_count INTEGER,
    semantic_theme TEXT,
    semantic_direction TEXT,
    raw_json TEXT NOT NULL,
    snapshot_id TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES catalog_snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_fields_name ON fields(name);
CREATE INDEX IF NOT EXISTS idx_fields_dataset ON fields(dataset_name);
CREATE INDEX IF NOT EXISTS idx_fields_theme ON fields(semantic_theme);

CREATE TABLE IF NOT EXISTS operators (
    operator_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    signature TEXT,
    description TEXT,
    raw_json TEXT NOT NULL,
    snapshot_id TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES catalog_snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_operators_name ON operators(name);

CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    statement TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    expected_direction TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hypothesis_cards (
    id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    family TEXT NOT NULL,
    statement TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    expected_direction TEXT,
    horizon TEXT,
    data_themes_json TEXT NOT NULL,
    field_names_json TEXT NOT NULL,
    operator_roles_json TEXT NOT NULL,
    falsifier TEXT NOT NULL,
    novelty_json TEXT NOT NULL,
    status TEXT NOT NULL,
    generator TEXT NOT NULL,
    model_name TEXT,
    prompt_hash TEXT,
    evidence_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id)
);

CREATE INDEX IF NOT EXISTS idx_hypothesis_cards_status ON hypothesis_cards(status);
CREATE INDEX IF NOT EXISTS idx_hypothesis_cards_family ON hypothesis_cards(family);

CREATE TABLE IF NOT EXISTS alpha_artifacts (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    hypothesis_id TEXT,
    family TEXT NOT NULL,
    expression TEXT NOT NULL,
    canonical_expression TEXT NOT NULL,
    exact_hash TEXT NOT NULL UNIQUE,
    structural_hash TEXT NOT NULL,
    field_names_json TEXT NOT NULL,
    operator_names_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    mutation TEXT,
    generator TEXT NOT NULL,
    model_name TEXT,
    prompt_hash TEXT,
    prompt_version TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    complexity_nodes INTEGER NOT NULL,
    complexity_depth INTEGER NOT NULL,
    status TEXT NOT NULL,
    best_reward REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(parent_id) REFERENCES alpha_artifacts(id),
    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_status ON alpha_artifacts(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_family ON alpha_artifacts(family);
CREATE INDEX IF NOT EXISTS idx_artifacts_structure ON alpha_artifacts(structural_hash);

CREATE TABLE IF NOT EXISTS rejected_candidates (
    id TEXT PRIMARY KEY,
    expression TEXT NOT NULL,
    family TEXT,
    reason TEXT NOT NULL,
    details_json TEXT NOT NULL,
    generator TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    settings_hash TEXT NOT NULL,
    request_path TEXT,
    response_path TEXT,
    simulation_url TEXT,
    platform_alpha_id TEXT,
    platform_status TEXT NOT NULL,
    sharpe REAL,
    fitness REAL,
    turnover REAL,
    returns_value REAL,
    drawdown REAL,
    margin REAL,
    subuniverse_sharpe REAL,
    self_correlation REAL,
    checks_json TEXT NOT NULL,
    annual_json TEXT NOT NULL,
    error_text TEXT,
    reward REAL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(artifact_id) REFERENCES alpha_artifacts(id),
    UNIQUE(artifact_id, settings_hash, started_at)
);

CREATE INDEX IF NOT EXISTS idx_runs_artifact ON simulation_runs(artifact_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON simulation_runs(platform_status);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    simulation_run_id TEXT,
    reviewer TEXT NOT NULL,
    verdict TEXT NOT NULL,
    evidence_valid INTEGER NOT NULL,
    warnings_json TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(artifact_id) REFERENCES alpha_artifacts(id),
    FOREIGN KEY(simulation_run_id) REFERENCES simulation_runs(id)
);

CREATE TABLE IF NOT EXISTS research_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(artifact_id) REFERENCES alpha_artifacts(id)
);

CREATE TABLE IF NOT EXISTS family_stats (
    family TEXT PRIMARY KEY,
    completed_runs INTEGER NOT NULL DEFAULT 0,
    total_reward REAL NOT NULL DEFAULT 0,
    best_reward REAL,
    last_artifact_id TEXT,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or Settings.from_env().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextlib.contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(path: Path | None = None) -> Path:
    settings = Settings.from_env()
    db_path = path or settings.db_path
    with session(db_path) as connection:
        connection.executescript(DDL)
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    return db_path
