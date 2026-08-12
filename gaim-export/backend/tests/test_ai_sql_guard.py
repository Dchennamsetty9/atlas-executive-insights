import sys
from pathlib import Path

# Ensure backend package root is importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai_service import AIService


def test_read_only_sql_guard_accepts_select_and_with():
    svc = AIService()

    assert svc._is_safe_read_only_sql("SELECT 1")
    assert svc._is_safe_read_only_sql("WITH t AS (SELECT 1) SELECT * FROM t;")


def test_read_only_sql_guard_rejects_mutating_and_multi_statement():
    svc = AIService()

    assert not svc._is_safe_read_only_sql("DROP TABLE foo")
    assert not svc._is_safe_read_only_sql("INSERT INTO foo VALUES (1)")
    assert not svc._is_safe_read_only_sql("SELECT 1; DELETE FROM foo")


def test_warehouse_id_extraction_from_http_path():
    svc = AIService()

    assert svc._warehouse_id_from_http_path("/sql/1.0/warehouses/abc123") == "abc123"
    assert svc._warehouse_id_from_http_path("/bad/path") == "c24ee33594e13e93"
