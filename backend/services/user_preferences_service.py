"""
services/user_preferences_service.py
======================================
Stores and retrieves per-user preferences in a Databricks Delta table.

Tables (auto-created on first use):
  atlas_user_preferences  — filter presets + role-based default views
  atlas_executive_actions — executive action tracking (mark done, assign owner)

User identity comes from the x-forwarded-access-token header (Databricks Apps
user passthrough).  Falls back to "anonymous" in local dev.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# DDL executed once to bootstrap the tables if they don't exist.
_DDL_PREFS = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.atlas_user_preferences (
  user_id        STRING NOT NULL,
  pref_key       STRING NOT NULL,
  pref_value     STRING,          -- JSON-encoded value
  updated_at     TIMESTAMP
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
"""

_DDL_ACTIONS = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.atlas_executive_actions (
  action_id      STRING NOT NULL,
  user_id        STRING,
  text           STRING NOT NULL,
  owner          STRING,
  status         STRING NOT NULL DEFAULT 'pending',   -- pending | done
  priority       STRING,                              -- high | medium | low
  source         STRING,                              -- forecast | insight | manual
  created_at     TIMESTAMP,
  completed_at   TIMESTAMP
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
"""


class UserPreferencesService:
    """CRUD layer for user preferences and executive action tracking."""

    def __init__(self):
        from config.settings import settings
        from services.databricks_connection import get_connection

        self._get_connection = get_connection
        self._catalog = settings.user_prefs_catalog
        self._schema  = settings.user_prefs_schema
        self._prefs_table   = settings.user_prefs_table
        self._actions_table = settings.actions_table
        self._bootstrapped  = False

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _fqn(self, table: str) -> str:
        return f"`{self._catalog}`.`{self._schema}`.`{table}`"

    def _bootstrap(self):
        """Create tables on first call (idempotent)."""
        if self._bootstrapped:
            return
        try:
            with self._get_connection() as conn, conn.cursor() as cur:
                cur.execute(_DDL_PREFS.format(
                    catalog=self._catalog, schema=self._schema))
                cur.execute(_DDL_ACTIONS.format(
                    catalog=self._catalog, schema=self._schema))
            self._bootstrapped = True
            logger.info("User preferences tables ready.")
        except Exception as exc:
            logger.error("Could not bootstrap prefs tables: %s", exc)
            raise HTTPException(status_code=503, detail="Preferences storage unavailable") from exc

    def _exec(self, sql: str, params: tuple = ()):
        try:
            self._bootstrap()
            with self._get_connection() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                if not cur.description:
                    return []
                rows = cur.fetchall()
                cols = [column[0] for column in cur.description]
                return [dict(zip(cols, row)) for row in rows]
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("UserPrefs SQL error: %s", exc)
            raise HTTPException(status_code=503, detail="Preferences storage unavailable") from exc

    # ── Filter presets ─────────────────────────────────────────────────────────

    def get_presets(self, user_id: str) -> List[Dict[str, Any]]:
        """Return all saved filter presets for the user."""
        rows = self._exec(
            f"SELECT pref_value FROM {self._fqn(self._prefs_table)} "
            "WHERE user_id = ? AND pref_key = 'filter_presets'",
            (user_id,)
        )
        if rows:
            try:
                return json.loads(rows[0]["pref_value"] or "[]")
            except Exception:
                pass
        return []

    def save_preset(self, user_id: str, name: str, filters: Dict[str, Any]) -> bool:
        """Upsert a named filter preset."""
        presets = self.get_presets(user_id)
        # Replace if name exists, else append
        presets = [p for p in presets if p.get("name") != name]
        presets.append({"name": name, "filters": filters, "created_at": datetime.utcnow().isoformat()})
        return self._upsert_pref(user_id, "filter_presets", presets)

    def delete_preset(self, user_id: str, name: str) -> bool:
        """Remove a named filter preset."""
        presets = [p for p in self.get_presets(user_id) if p.get("name") != name]
        return self._upsert_pref(user_id, "filter_presets", presets)

    # ── Generic preferences ────────────────────────────────────────────────────

    def get_pref(self, user_id: str, key: str, default: Any = None) -> Any:
        rows = self._exec(
            f"SELECT pref_value FROM {self._fqn(self._prefs_table)} "
            "WHERE user_id = ? AND pref_key = ?",
            (user_id, key)
        )
        if rows:
            try:
                return json.loads(rows[0]["pref_value"])
            except Exception:
                return rows[0]["pref_value"]
        return default

    def set_pref(self, user_id: str, key: str, value: Any) -> bool:
        return self._upsert_pref(user_id, key, value)

    def _upsert_pref(self, user_id: str, key: str, value: Any) -> bool:
        fqn = self._fqn(self._prefs_table)
        encoded = json.dumps(value)
        now = datetime.utcnow().isoformat()
        self._exec(
            f"MERGE INTO {fqn} AS target "
            "USING (SELECT ? AS user_id, ? AS pref_key, ? AS pref_value, CAST(? AS TIMESTAMP) AS updated_at) AS incoming "
            "ON target.user_id = incoming.user_id AND target.pref_key = incoming.pref_key "
            "WHEN MATCHED THEN UPDATE SET pref_value = incoming.pref_value, updated_at = incoming.updated_at "
            "WHEN NOT MATCHED THEN INSERT (user_id, pref_key, pref_value, updated_at) "
            "VALUES (incoming.user_id, incoming.pref_key, incoming.pref_value, incoming.updated_at)",
            (user_id, key, encoded, now),
        )
        return True

    # ── Executive actions ──────────────────────────────────────────────────────

    def list_actions(self, user_id: Optional[str] = None,
                     status: Optional[str] = None) -> List[Dict[str, Any]]:
        if not user_id:
            return []
        fqn = self._fqn(self._actions_table)
        wheres, params = [], []
        if user_id:
            wheres.append("user_id = ?")
            params.append(user_id)
        if status:
            wheres.append("status = ?")
            params.append(status)
        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        return self._exec(
            f"SELECT * FROM {fqn} {where_clause} ORDER BY created_at DESC",
            tuple(params)
        )

    def create_action(self, text: str, owner: Optional[str] = None,
                      priority: str = "medium", source: str = "manual",
                      user_id: Optional[str] = None) -> Dict[str, Any]:
        import uuid
        action_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        fqn = self._fqn(self._actions_table)
        self._exec(
            f"INSERT INTO {fqn} "
            "(action_id, user_id, text, owner, status, priority, source, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (action_id, user_id, text, owner, priority, source, now)
        )
        return {"action_id": action_id, "text": text, "owner": owner,
                "status": "pending", "priority": priority, "source": source,
                "created_at": now}

    def _owns_action(self, user_id: str, action_id: str) -> bool:
        if not user_id:
            return False
        return bool(self._exec(
            f"SELECT action_id FROM {self._fqn(self._actions_table)} WHERE action_id = ? AND user_id = ?",
            (action_id, user_id),
        ))

    def update_action_status(self, action_id: str, status: str,
                             owner: Optional[str] = None, *, user_id: str) -> bool:
        if not self._owns_action(user_id, action_id):
            return False
        if status not in ("pending", "done"):
            raise ValueError("Invalid action status")
        fqn = self._fqn(self._actions_table)
        completed_at = datetime.utcnow().isoformat() if status == "done" else None
        assignments = "status = ?, completed_at = ?"
        params = [status, completed_at]
        if owner is not None:
            assignments += ", owner = ?"
            params.append(owner)
        self._exec(
            f"UPDATE {fqn} SET {assignments} WHERE action_id = ? AND user_id = ?",
            tuple(params + [action_id, user_id]),
        )
        return True

    def delete_action(self, action_id: str, *, user_id: str) -> bool:
        if not self._owns_action(user_id, action_id):
            return False
        fqn = self._fqn(self._actions_table)
        self._exec(f"DELETE FROM {fqn} WHERE action_id = ? AND user_id = ?", (action_id, user_id))
        return True

    # ── Action metadata + governance log (JSON in prefs table) ──────────────

    def _action_meta_key(self) -> str:
        return "action_metadata"

    def _governance_log_key(self) -> str:
        return "forecast_governance_log"

    def list_action_metadata(self, user_id: str) -> Dict[str, Any]:
        data = self.get_pref(user_id, self._action_meta_key(), default={})
        return data if isinstance(data, dict) else {}

    def get_action_metadata(self, user_id: str, action_id: str) -> Dict[str, Any]:
        return self.list_action_metadata(user_id).get(action_id, {})

    def upsert_action_metadata(self, user_id: str, action_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        if not self._owns_action(user_id, action_id):
            raise LookupError("Action not found")
        all_meta = self.list_action_metadata(user_id)
        current = all_meta.get(action_id, {})
        merged = {**current, **{k: v for k, v in metadata.items() if v is not None}}
        merged["updated_at"] = datetime.utcnow().isoformat()
        all_meta[action_id] = merged
        self.set_pref(user_id, self._action_meta_key(), all_meta)
        return merged

    def list_governance_log(self, user_id: str) -> List[Dict[str, Any]]:
        rows = self.get_pref(user_id, self._governance_log_key(), default=[])
        return rows if isinstance(rows, list) else []

    def append_governance_log(self, user_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        import uuid
        rows = self.list_governance_log(user_id)
        payload = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat(),
            **entry,
        }
        rows.insert(0, payload)
        self.set_pref(user_id, self._governance_log_key(), rows[:500])
        return payload


# Singleton
user_prefs_service = UserPreferencesService()
