from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .config import Settings


SCHEMA_VERSION = 4


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

CREATE VIEW IF NOT EXISTS active_brain_operators AS
WITH latest_snapshot AS (
    SELECT id
    FROM catalog_snapshots
    WHERE source = 'brain_api'
    ORDER BY created_at DESC, rowid DESC
    LIMIT 1
), ranked AS (
    SELECT o.*,
           row_number() OVER (
               PARTITION BY lower(o.name)
               ORDER BY length(coalesce(o.description, '')) DESC, o.rowid DESC
           ) AS name_rank
    FROM operators o
    JOIN latest_snapshot s ON s.id = o.snapshot_id
    WHERE lower(coalesce(o.category, '')) <> 'typed_registry'
)
SELECT operator_key,name,category,signature,description,raw_json,snapshot_id,updated_at
FROM ranked
WHERE name_rank = 1;

CREATE TABLE IF NOT EXISTS operator_profiles (
    operator_name TEXT PRIMARY KEY,
    snapshot_id TEXT,
    active INTEGER NOT NULL,
    primary_role TEXT NOT NULL,
    secondary_roles_json TEXT NOT NULL,
    stage TEXT NOT NULL,
    input_kind TEXT NOT NULL,
    output_kind TEXT NOT NULL,
    state_class TEXT NOT NULL,
    unit_effect TEXT NOT NULL,
    information_loss TEXT NOT NULL,
    tail_sensitivity TEXT NOT NULL,
    coverage_effect TEXT NOT NULL,
    turnover_tendency TEXT NOT NULL,
    preferred_field_forms_json TEXT NOT NULL,
    discouraged_field_forms_json TEXT NOT NULL,
    hard_rules_json TEXT NOT NULL,
    soft_rules_json TEXT NOT NULL,
    parameter_policy TEXT NOT NULL,
    source_confidence REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_profiles (
    field_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dataset_name TEXT,
    data_type TEXT NOT NULL,
    economic_theme TEXT NOT NULL,
    secondary_themes_json TEXT NOT NULL,
    semantic_form TEXT NOT NULL,
    update_cadence TEXT NOT NULL,
    signedness TEXT NOT NULL,
    unit_family TEXT NOT NULL,
    sparsity_class TEXT NOT NULL,
    peer_dependence TEXT NOT NULL,
    direction_prior TEXT NOT NULL,
    direction_confidence TEXT NOT NULL,
    horizon_prior_json TEXT NOT NULL,
    preferred_roles_json TEXT NOT NULL,
    discouraged_roles_json TEXT NOT NULL,
    classification_source TEXT NOT NULL,
    confidence REAL NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(field_key) REFERENCES fields(field_key)
);
CREATE INDEX IF NOT EXISTS idx_field_profiles_theme ON field_profiles(economic_theme);
CREATE INDEX IF NOT EXISTS idx_field_profiles_form ON field_profiles(semantic_form);

CREATE TABLE IF NOT EXISTS path_template_registry (
    template_id TEXT PRIMARY KEY,
    definition_json TEXT NOT NULL,
    enabled_by_default INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS alpha_plans (
    id TEXT PRIMARY KEY,
    hypothesis_id TEXT,
    card_id TEXT,
    family TEXT NOT NULL,
    template_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    resolved_json TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    status TEXT NOT NULL,
    artifact_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id),
    FOREIGN KEY(card_id) REFERENCES hypothesis_cards(id),
    FOREIGN KEY(artifact_id) REFERENCES alpha_artifacts(id)
);
CREATE INDEX IF NOT EXISTS idx_alpha_plans_template ON alpha_plans(template_id);
CREATE INDEX IF NOT EXISTS idx_alpha_plans_status ON alpha_plans(status);

CREATE TABLE IF NOT EXISTS artifact_motifs (
    artifact_id TEXT PRIMARY KEY,
    role_motif_hash TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    parameter_hash TEXT NOT NULL,
    role_path_json TEXT NOT NULL,
    field_themes_json TEXT NOT NULL,
    field_forms_json TEXT NOT NULL,
    subtree_hashes_json TEXT NOT NULL,
    parameter_normalized TEXT NOT NULL,
    novelty_score REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(artifact_id) REFERENCES alpha_artifacts(id)
);
CREATE INDEX IF NOT EXISTS idx_artifact_motifs_role ON artifact_motifs(role_motif_hash);
CREATE INDEX IF NOT EXISTS idx_artifact_motifs_semantic ON artifact_motifs(semantic_hash);
CREATE INDEX IF NOT EXISTS idx_artifact_motifs_parameter ON artifact_motifs(parameter_hash);

CREATE TABLE IF NOT EXISTS subtree_stats (
    subtree_hash TEXT PRIMARY KEY,
    artifact_count INTEGER NOT NULL,
    last_artifact_id TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(last_artifact_id) REFERENCES alpha_artifacts(id)
);

CREATE TABLE IF NOT EXISTS motif_stats (
    context_key TEXT PRIMARY KEY,
    role_motif_hash TEXT NOT NULL,
    field_theme TEXT NOT NULL,
    horizon_bucket TEXT NOT NULL,
    completed_runs INTEGER NOT NULL,
    median_sharpe REAL,
    median_fitness REAL,
    median_turnover REAL,
    median_self_correlation REAL,
    pass_rate REAL,
    annual_min_sharpe REAL,
    uncertainty REAL,
    stats_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_motif_stats_role ON motif_stats(role_motif_hash);
CREATE INDEX IF NOT EXISTS idx_motif_stats_theme ON motif_stats(field_theme);

CREATE TABLE IF NOT EXISTS family_trial_stats (
    family TEXT PRIMARY KEY,
    effective_trial_count INTEGER NOT NULL DEFAULT 0,
    semantic_branches INTEGER NOT NULL DEFAULT 0,
    parameter_only_trials INTEGER NOT NULL DEFAULT 0,
    stopped INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT,
    updated_at TEXT NOT NULL
);

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
