from __future__ import annotations

"""Materialize all deterministic research knowledge into SQLite."""

import sqlite3
from typing import Any

from ..db import json_dumps, utc_now
from .empirical import rebuild_motif_stats
from .field_profiles import materialize_field_profiles
from .motifs import backfill_motifs
from .operator_kb import active_operator_knowledge, assert_semantic_coverage
from .path_templates import PATH_TEMPLATES
from .scheduler import rebuild_family_trial_stats


def materialize_operator_profiles(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute("SELECT name,snapshot_id FROM active_brain_operators").fetchall()
    snapshot_by_name = {str(row["name"]).lower(): row["snapshot_id"] for row in rows}
    profiles = active_operator_knowledge(connection)
    connection.execute("UPDATE operator_profiles SET active=0")
    for name, profile in profiles.items():
        connection.execute(
            """INSERT INTO operator_profiles(
                operator_name,snapshot_id,active,primary_role,secondary_roles_json,stage,input_kind,output_kind,
                state_class,unit_effect,information_loss,tail_sensitivity,coverage_effect,turnover_tendency,
                preferred_field_forms_json,discouraged_field_forms_json,hard_rules_json,soft_rules_json,
                parameter_policy,source_confidence,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(operator_name) DO UPDATE SET
                snapshot_id=excluded.snapshot_id,active=excluded.active,primary_role=excluded.primary_role,
                secondary_roles_json=excluded.secondary_roles_json,stage=excluded.stage,input_kind=excluded.input_kind,
                output_kind=excluded.output_kind,state_class=excluded.state_class,unit_effect=excluded.unit_effect,
                information_loss=excluded.information_loss,tail_sensitivity=excluded.tail_sensitivity,
                coverage_effect=excluded.coverage_effect,turnover_tendency=excluded.turnover_tendency,
                preferred_field_forms_json=excluded.preferred_field_forms_json,
                discouraged_field_forms_json=excluded.discouraged_field_forms_json,
                hard_rules_json=excluded.hard_rules_json,soft_rules_json=excluded.soft_rules_json,
                parameter_policy=excluded.parameter_policy,source_confidence=excluded.source_confidence,
                updated_at=excluded.updated_at""",
            (
                name, snapshot_by_name.get(name), 1, profile.primary_role, json_dumps(profile.secondary_roles),
                profile.stage, profile.input_kind, profile.output_kind, profile.state_class, profile.unit_effect,
                profile.information_loss, profile.tail_sensitivity, profile.coverage_effect, profile.turnover_tendency,
                json_dumps(profile.preferred_field_forms), json_dumps(profile.discouraged_field_forms),
                json_dumps(profile.hard_rules), json_dumps(profile.soft_rules), profile.parameter_policy, 1.0, utc_now(),
            ),
        )
    coverage = assert_semantic_coverage(connection)
    return {"materialized": len(profiles), **coverage}


def materialize_path_templates(connection: sqlite3.Connection) -> dict[str, int]:
    for template in PATH_TEMPLATES:
        connection.execute(
            """INSERT INTO path_template_registry(template_id,definition_json,enabled_by_default,updated_at)
               VALUES(?,?,?,?) ON CONFLICT(template_id) DO UPDATE SET
               definition_json=excluded.definition_json,enabled_by_default=excluded.enabled_by_default,
               updated_at=excluded.updated_at""",
            (template.id, json_dumps(template.to_dict()), int(template.enabled_by_default), utc_now()),
        )
    return {"materialized": len(PATH_TEMPLATES)}


def rebuild_all(connection: sqlite3.Connection) -> dict[str, Any]:
    operator_result = materialize_operator_profiles(connection)
    field_result = materialize_field_profiles(connection)
    template_result = materialize_path_templates(connection)
    motif_result = backfill_motifs(connection)
    empirical_result = rebuild_motif_stats(connection)
    trial_result = rebuild_family_trial_stats(connection)
    return {
        "operators": operator_result,
        "fields": field_result,
        "templates": template_result,
        "motifs": motif_result,
        "empirical": empirical_result,
        "trials": trial_result,
    }


__all__ = ["materialize_operator_profiles", "materialize_path_templates", "rebuild_all"]
