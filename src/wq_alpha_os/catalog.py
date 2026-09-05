from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable

from .db import json_dumps, session, utc_now
from .dsl.fingerprint import fingerprint
from .dsl.nodes import node_count, node_depth
from .dsl.parser import ParseError, parse
from .operator_registry import deduplicate_brain_operators


THEMES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("value_cashflow", ("value", "cash flow", "cashflow", "cfp", "book to", "earnings yield"), "reverse"),
    ("profitability_quality", ("profit", "quality", "margin", "roa", "roe", "accrual"), "ambiguous"),
    ("analyst_revision", ("analyst", "estimate", "revision", "recommendation", "target price"), "ambiguous"),
    ("earnings_dispersion", ("dispersion", "surprise", "standard deviation of estimate"), "ambiguous"),
    ("growth", ("growth", "change in", "cagr"), "ambiguous"),
    ("leverage", ("leverage", "debt", "liability"), "reverse"),
    ("risk", ("risk", "volatility", "beta", "drawdown"), "reverse"),
    ("price_volume", ("price", "return", "volume", "vwap", "close", "open", "high", "low"), "ambiguous"),
    ("options", ("option", "implied volatility", "put call"), "ambiguous"),
    ("sentiment", ("sentiment", "news", "social"), "ambiguous"),
    ("short_interest", ("short interest", "short ratio"), "reverse"),
    ("insider", ("insider", "director dealing"), "ambiguous"),
    ("relationship", ("relationship", "supplier", "customer", "network"), "ambiguous"),
)


def classify_field(name: str, description: str = "") -> tuple[str, str]:
    text = f"{name} {description}".lower().replace("_", " ")
    for theme, needles, direction in THEMES:
        if any(needle in text for needle in needles):
            return theme, direction
    return "generic", "ambiguous"


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(x or "") for x in parts).encode()).hexdigest()


def _snapshot(connection: sqlite3.Connection, source: str, region: str, universe: str, delay: int, raw: str = "") -> str:
    snapshot_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO catalog_snapshots VALUES(?,?,?,?,?,?,?)",
        (snapshot_id, source, region, universe, delay, raw, utc_now()),
    )
    return snapshot_id


def import_legacy(source: Path, target: Path | None = None) -> dict[str, int]:
    if not source.exists():
        raise FileNotFoundError(source)
    old = sqlite3.connect(source)
    old.row_factory = sqlite3.Row
    counts = {"datasets": 0, "fields": 0, "operators": 0, "legacy_artifacts": 0, "legacy_skipped": 0}
    try:
        with session(target) as connection:
            snapshot_id = _snapshot(connection, f"legacy:{source.name}", "USA", "TOP3000", 1)
            for row in old.execute("SELECT * FROM datasets"):
                data = dict(row)
                name = str(data.get("dataset_name") or "unknown")
                region = str(data.get("region") or "USA")
                universe = str(data.get("universe") or "TOP3000")
                delay = int(data.get("delay") or 1)
                connection.execute(
                    """INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (_hash(name, region, universe, delay), None, name, data.get("category"), region,
                     universe, delay, data.get("fields_count"), data.get("coverage"), data.get("date_coverage"),
                     data.get("value_score"), data.get("alphas_count"), json_dumps(data), snapshot_id, utc_now()),
                )
                counts["datasets"] += 1
            for row in old.execute("SELECT * FROM fields"):
                data = dict(row)
                name = str(data.get("field_name") or "").strip()
                if not name:
                    continue
                dataset = str(data.get("dataset_name") or "unknown")
                theme, direction = classify_field(name, str(data.get("description") or ""))
                connection.execute(
                    """INSERT OR REPLACE INTO fields VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (_hash(name, dataset, "USA", "TOP3000", 1), name, name, None, dataset, data.get("category"),
                     data.get("description"), str(data.get("field_type") or "MATRIX").upper(), "USA", "TOP3000", 1,
                     data.get("coverage"), data.get("date_coverage"), data.get("alphas_count"), theme, direction,
                     json_dumps(data), snapshot_id, utc_now()),
                )
                counts["fields"] += 1
            seen: set[str] = set()
            for row in old.execute("SELECT * FROM operators ORDER BY length(coalesce(description,'')) DESC"):
                data = dict(row)
                name = str(data.get("operator_name") or "").strip().lower()
                if not name or name in seen:
                    continue
                seen.add(name)
                connection.execute(
                    """INSERT OR IGNORE INTO operators VALUES(?,?,?,?,?,?,?,?)""",
                    (_hash("legacy", snapshot_id, name), name, data.get("category"), data.get("signature"), data.get("description"),
                     json_dumps(data), snapshot_id, utc_now()),
                )
                counts["operators"] += 1
            table_exists = old.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alpha_candidates'"
            ).fetchone()
            if table_exists:
                for row in old.execute("SELECT * FROM alpha_candidates"):
                    data = dict(row)
                    expression = str(data.get("expression") or "").strip()
                    if not expression:
                        counts["legacy_skipped"] += 1
                        continue
                    try:
                        root = parse(expression)
                        fp = fingerprint(expression)
                    except (ParseError, ValueError):
                        counts["legacy_skipped"] += 1
                        continue
                    cursor = connection.execute(
                        """INSERT OR IGNORE INTO alpha_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()), None, None, str(data.get("family") or "legacy_unclassified"), expression,
                         fp.canonical, fp.exact_hash, fp.structural_hash, json_dumps(fp.fields), json_dumps(fp.operators),
                         str(data.get("hypothesis") or "Di sản chưa có kết quả mô phỏng liên kết."), None,
                         "legacy_import", None, None, "legacy-v1",
                         json_dumps({"valid": None, "reason": "legacy_unverified"}), node_count(root), node_depth(root),
                         "legacy_unverified", None, str(data.get("created_at") or utc_now())),
                    )
                    if cursor.rowcount:
                        counts["legacy_artifacts"] += 1
    finally:
        old.close()
    return counts


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
    return []


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        selected = value.get("id") or value.get("name") or value.get("description")
        return str(selected) if selected is not None else json_dumps(value)
    return str(value)


def _percent(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number * 100 if 0 <= number <= 1 else number


def import_brain_snapshot(raw_dir: Path, target: Path | None, region: str,
                          universe: str, delay: int) -> dict[str, int]:
    required = {name: raw_dir / f"{name}.json" for name in ("datasets", "fields", "operators")}
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Thiếu tệp bản chụp: " + ", ".join(missing))
    datasets_payload = json.loads(required["datasets"].read_text(encoding="utf-8"))
    fields_payload = json.loads(required["fields"].read_text(encoding="utf-8"))
    operators_payload = json.loads(required["operators"].read_text(encoding="utf-8"))
    counts = {"datasets": 0, "fields": 0, "operators": 0}
    with session(target) as connection:
        snapshot_id = _snapshot(connection, "brain_api", region, universe, delay, str(raw_dir))
        for data in _items(datasets_payload):
            dataset_id = str(data.get("id") or data.get("datasetId") or "")
            name = str(data.get("name") or dataset_id)
            connection.execute(
                """INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_hash(dataset_id or name, region, universe, delay), dataset_id, name, _text_value(data.get("category")), region,
                 universe, delay, data.get("fieldCount") or data.get("field_count"), _percent(data.get("coverage")),
                 _percent(data.get("dateCoverage")), data.get("valueScore"), data.get("alphaCount"), json_dumps(data),
                 snapshot_id, utc_now()),
            )
            counts["datasets"] += 1
        for data in _items(fields_payload):
            name = str(data.get("id") or data.get("name") or "").strip()
            if not name:
                continue
            dataset_value = data.get("dataset")
            dataset_id = dataset_value.get("id") if isinstance(dataset_value, dict) else data.get("datasetId")
            dataset_name = dataset_value.get("name") if isinstance(dataset_value, dict) else data.get("datasetName")
            theme, direction = classify_field(name, str(data.get("description") or ""))
            connection.execute(
                """INSERT OR REPLACE INTO fields VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_hash(name, dataset_id, region, universe, delay), name, name, _text_value(dataset_id), _text_value(dataset_name),
                 _text_value(data.get("category")), data.get("description"), str(data.get("type") or "MATRIX").upper(), region,
                 universe, delay, _percent(data.get("coverage")), _percent(data.get("dateCoverage")), data.get("alphaCount"), theme,
                 direction, json_dumps(data), snapshot_id, utc_now()),
            )
            counts["fields"] += 1
        for data in deduplicate_brain_operators(_items(operators_payload)):
            name = data["name"]
            connection.execute(
                "INSERT INTO operators VALUES(?,?,?,?,?,?,?,?)",
                (_hash("brain", snapshot_id, name), name, data["category"], data["definition"],
                 data["description"], json_dumps(data), snapshot_id, utc_now()),
            )
            counts["operators"] += 1
    return counts


def sync_from_brain(client: Any, target: Path | None, region: str, universe: str, delay: int) -> dict[str, int]:
    raw_dir = client.new_evidence_directory("catalog")
    filters = {"instrumentType": "EQUITY", "region": region, "universe": universe, "delay": delay}
    datasets_payload = client.get_all("/data-sets", filters, progress_label="Bo du lieu")
    fields_payload = client.get_all("/data-fields", filters, progress_label="Truong du lieu")
    operators_payload = client.get_all("/operators", {}, progress_label="Toan tu")
    (raw_dir / "datasets.json").write_text(json_dumps(datasets_payload), encoding="utf-8")
    (raw_dir / "fields.json").write_text(json_dumps(fields_payload), encoding="utf-8")
    (raw_dir / "operators.json").write_text(json_dumps(operators_payload), encoding="utf-8")
    return import_brain_snapshot(raw_dir, target, region, universe, delay)
