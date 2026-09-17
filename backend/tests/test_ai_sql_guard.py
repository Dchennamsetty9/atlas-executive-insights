import sys
import asyncio
import types
from pathlib import Path

import pytest

# Ensure backend package root is importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai_service import AIService
from services.ai_sql_policy import prepare_read_only_sql


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


@pytest.mark.parametrize("sql", [
    "SELECT * FROM other_catalog.private_schema.private_table",
    "SELECT * FROM metis_won_opps_fact",
    "SELECT * FROM read_files('s3://private')",
    "SELECT ai_query('endpoint', 'prompt')",
    "SELECT secret('scope', 'key')",
    "SELECT reflect('java.lang.System', 'getenv')",
    "SELECT federated.sales.custom_function(1)",
    "WITH hidden AS (SELECT * FROM private.data.secrets) SELECT * FROM hidden",
    "SELECT * FROM federated.sales.metis_won_opps_fact UNION ALL SELECT * FROM private.data.secrets",
    "WITH RECURSIVE numbers AS (SELECT 1 UNION ALL SELECT * FROM numbers) SELECT * FROM numbers",
    "SELECT 1; SELECT 2", "SELECT 1 INTO OUTFILE '/tmp/output'",
])
def test_ai_sql_rejects_unapproved_tables_functions_and_commands(sql):
    assert not AIService._is_safe_read_only_sql(sql)
    with pytest.raises(ValueError):
        prepare_read_only_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT SUM(amount_towards_plan) FROM federated.sales.metis_won_opps_fact",
    "WITH won AS (SELECT * FROM federated.sales.metis_won_opps_fact) SELECT COUNT(*) FROM won",
    "SELECT COUNT(DISTINCT salesforce_opportunity_id) FROM federated.sales.metis_opened_opps_fact WHERE pipeline_entered_date >= DATE_TRUNC('quarter', CURRENT_DATE())",
    "SELECT * FROM federated.sales.metis_targets_summary WHERE plan_version = 'Plan'",
    "SELECT 'DROP TABLE; -- not a command' AS note",
])
def test_ai_sql_accepts_approved_reporting_queries_and_caps_rows(sql):
    prepared = prepare_read_only_sql(sql)
    assert prepared.endswith("LIMIT 100")


def test_ai_sql_preserves_smaller_limits_and_caps_large_limits():
    assert prepare_read_only_sql("SELECT 1 LIMIT 5").endswith("LIMIT 5")
    assert prepare_read_only_sql("SELECT 1 LIMIT 10000").endswith("LIMIT 100")
    assert prepare_read_only_sql("SELECT 1 LIMIT 0").endswith("LIMIT 0")


def test_ai_sql_uses_shared_connector_not_workspace_client(monkeypatch):
    calls = []
    connector = types.ModuleType("services.databricks_connection")
    connector.execute_query = lambda sql, **kwargs: calls.append((sql, kwargs)) or [{"count": 5}]
    monkeypatch.setitem(sys.modules, "services.databricks_connection", connector)
    service = AIService()
    monkeypatch.setattr(service, "_get_client", lambda: pytest.fail("SQL must not use the service-principal SDK"))
    assert service._execute_sql_sync("SELECT COUNT(*) FROM federated.sales.metis_won_opps_fact") == [{"count": 5}]
    assert calls[0][0].endswith("LIMIT 100")
    assert calls[0][1] == {"max_attempts": 1, "max_rows": 100}
    with pytest.raises(ValueError):
        service._execute_sql_sync("SELECT secret('scope', 'key')")
    assert len(calls) == 1


def test_ai_query_failure_does_not_fallback_or_expose_error(monkeypatch):
    service = AIService()
    monkeypatch.setattr(service, "_generate_sql_sync", lambda _: {"sql": "SELECT 1"})

    def failed(_sql):
        raise RuntimeError("private credential details")

    monkeypatch.setattr(service, "_execute_sql_sync", failed)
    genie = types.ModuleType("services.genie_service")
    genie.genie_service = types.SimpleNamespace(ask_kpi_question=lambda _: pytest.fail("No alternate principal fallback"))
    monkeypatch.setitem(sys.modules, "services.genie_service", genie)
    result = asyncio.run(service.ask_ai("What is revenue?"))
    assert result["data"] == []
    assert result["source"] == "sql-error"
    assert "private" not in result["answer"]


def test_ai_sql_rejects_oversized_result_before_interpretation(monkeypatch):
    connector = types.ModuleType("services.databricks_connection")
    connector.execute_query = lambda *_args, **_kwargs: [{"payload": "x" * 262145}]
    monkeypatch.setitem(sys.modules, "services.databricks_connection", connector)
    with pytest.raises(ValueError, match="size limit"):
        AIService()._execute_sql_sync("SELECT 1")
