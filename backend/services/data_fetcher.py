"""
Data fetcher service - connects to database and retrieves raw data

Version: 0.3.1 - Direct Databricks Mode
Last Updated: 2026-05-15

KPI Formulas: Based on Performance Hub semantic model (Atlas - Performance Hub.pbip)
- Won_Pipeline: SUM(amount_towards_plan) WHERE is_won='True' AND xtxtype<>'Cancel'
- Won_Volume: DISTINCTCOUNT(opportunities_created_ids) WHERE is_won='True'
- ADS: Won_Pipeline / Won_Volume
- x_OppsCreated_mdl: From gaim_snapshot_pipeline_created_cq_daily
- xCreated_Pipeline: SUM(amount_towards_plan) from created table
- Active_Pipeline: SUM WHERE stage NOT IN closed stages
- close_rate_vol: Won_Volume / Created_Opps
- xCvg_mdl: Active_Pipeline / Daily_Plan$ (capped at 10x)

Tables:
- gaim_pipeline_daily_snapshot: Won, Active, and pipeline metrics
- gaim_snapshot_pipeline_created_cq_daily: Created opportunities and pipeline
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import pandas as pd
import os
import asyncio
from services.databricks_connection import token_available

try:
    from databricks import sql as databricks_sql
    from databricks.sdk.core import Config
    DATABRICKS_AVAILABLE = True
except ImportError:
    DATABRICKS_AVAILABLE = False
    print("Warning: databricks-sql-connector not installed. Using mock data.")

try:
    import pyodbc
    from sqlalchemy import create_engine, text
    SQL_SERVER_AVAILABLE = True
except ImportError:
    SQL_SERVER_AVAILABLE = False

from config.settings import settings


class DataFetcher:
    """Fetch data from the database (same source as Power BI)"""
    
    def __init__(self):
        # Require both the SDK and a valid token before attempting live Databricks queries.
        # Without this check, DataFetcher tries to connect using only DATABRICKS_HOST
        # (auto-set on all Databricks Apps nodes), which causes the connector to retry
        # for 900 s and exhaust the thread pool even when no PAT is available.
        self.in_databricks = os.getenv("DATABRICKS_HOST") is not None
        self.use_databricks = DATABRICKS_AVAILABLE and token_available()
        self.connection_string = self._build_connection_string() if not self.use_databricks else None
        self.engine = None
        # NOTE: Databricks SQL connector is not thread-safe for shared connections.
        # A fresh connection is created for every query (see get_connection).
        
    def _build_connection_string(self) -> str:
        """Build database connection string"""
        return (
            f"DRIVER={{{settings.db_driver}}};"
            f"SERVER={settings.db_server};"
            f"DATABASE={settings.db_name};"
            f"UID={settings.db_user};"
            f"PWD={settings.db_password};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )
    
    def get_connection(self):
        """Create and return a fresh Databricks SQL connection.

        A new connection is created on every call rather than reusing a shared
        instance because the databricks-sql-connector is NOT thread-safe for
        concurrent access.  Callers are responsible for closing the connection
        (or using it as a context manager: `with self.get_connection() as c`).

        For the legacy SQL Server path the SQLAlchemy engine is cached because
        it manages its own thread-safe connection pool internally.
        """
        if self.use_databricks:
            token = os.getenv("DATABRICKS_TOKEN") or settings.databricks_access_token
            if not token:
                raise RuntimeError(
                    "DATABRICKS_TOKEN is not set. "
                    "Export your Personal Access Token before starting the backend."
                )
            return databricks_sql.connect(
                server_hostname=settings.databricks_server_hostname,
                http_path=settings.databricks_http_path,
                access_token=token,
                _socket_timeout=10,
            )
        else:
            if not self.engine:
                conn_url = f"mssql+pyodbc:///?odbc_connect={self.connection_string}"
                self.engine = create_engine(conn_url)
            return self.engine
    
    def execute_query(self, query: str, params: List = None) -> pd.DataFrame:
        """Execute SQL query and return DataFrame - SYNCHRONOUS (use in thread pool)"""
        try:
            if self.use_databricks:
                # Use the connection as a context manager so it is always closed,
                # even if an exception is raised during query execution.
                with self.get_connection() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(query)
                        columns = [desc[0] for desc in cursor.description]
                        data = cursor.fetchall()
                df = pd.DataFrame(data, columns=columns)
            else:
                engine = self.get_connection()
                df = pd.read_sql(query, engine, params=params if params else None)
            
            # Replace NaN/Inf values with None for JSON serialization
            df = df.replace([float('inf'), float('-inf')], None)
            df = df.fillna(value=None)
            
            return df
        except Exception as e:
            print(f"ERROR in execute_query: {str(e)}")
            raise
    
    async def execute_query_async(self, query: str, params: List = None, timeout: int = 8) -> pd.DataFrame:
        """Execute SQL query asynchronously with timeout — defaults to 8s for cold-cluster safety."""
        try:
            # Run blocking query in thread pool with timeout
            return await asyncio.wait_for(
                asyncio.to_thread(self.execute_query, query, params),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            print(f"[DataFetcher] Query timed out after {timeout}s — returning empty DataFrame")
            return pd.DataFrame()
        except Exception as e:
            print(f"[DataFetcher] Query error: {str(e)}")
            raise
    
    async def fetch_kpi_data(
        self, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None
    ) -> pd.DataFrame:
        """
        Fetch KPI data for the dashboard - 8 core metrics from Performance Hub
        
        Args:
            start_date: Start date for period
            end_date: End date for period
            filters: Dict with keys: geo, channel, product (values like "AMER", "Enterprise", "Connect" or "All")
        """
        
        # Default to current quarter if no dates provided
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            # Start of current quarter
            today = datetime.now()
            quarter = (today.month - 1) // 3 + 1
            start_date = datetime(today.year, (quarter - 1) * 3 + 1, 1).strftime("%Y-%m-%d")
        
        # Default filters to "All" if not provided
        if filters is None:
            filters = {"geo": "All", "channel": "All", "product": "All"}
        
        try:
            if self.use_databricks:
                return await self._fetch_kpis_databricks(start_date, end_date, filters)
            else:
                return self._get_mock_kpi_data()
        except Exception as e:
            print(f"Error fetching KPI data: {e}")
            return self._get_mock_kpi_data()
    
    # ── Filter helpers ────────────────────────────────────────────────────────

    _PRODUCT_MAP: Dict[str, str] = {
        "Connect": "GoToConnect", "Engage": "GoToWebinar",
        "Rescue": "Rescue", "Central": "Central", "Resolve": "Resolve",
        "GoToConnect": "GoToConnect", "GoToWebinar": "GoToWebinar",
    }
    _VALID_GEO     = {"NA", "EMEA", "LATAM", "APAC", "AUS/ROW"}
    _VALID_CHANNEL = {"Enterprise", "Partner", "Mid-Market", "MSP", "GSI", "Small Business"}

    def _build_filter_federated(self, filters: Dict[str, str]) -> str:
        """AND-prefixed WHERE fragment for federated.sales.* tables.
        Columns: sales_market, sales_channel, product_genus, fuel_source.
        All values validated against whitelists; unknown values silently ignored.
        """
        parts: list = []
        geo = filters.get("geo", "")
        if geo and geo != "All" and geo in self._VALID_GEO:
            parts.append(f"AND sales_market = '{geo}'")
        channel = filters.get("channel", "")
        if channel and channel != "All" and channel in self._VALID_CHANNEL:
            parts.append(f"AND sales_channel = '{channel}'")
        product = filters.get("product", "")
        if product and product != "All":
            mapped = self._PRODUCT_MAP.get(product)
            if mapped:
                parts.append(f"AND product_genus = '{mapped}'")
        fuel = filters.get("fuel_source", "")
        if fuel and fuel != "All" and fuel in {"Marketing", "Sales", "Partner", "Unknown"}:
            parts.append(f"AND fuel_source = '{fuel}'")
        return " ".join(parts)

    def _build_filter_mdl(self, filters: Dict[str, str]) -> str:
        """AND-prefixed WHERE fragment for datagroup_mdl MDL snapshot tables.
        Columns: market, smoothed_channel, product_genus.
        """
        parts: list = []
        geo = filters.get("geo", "")
        if geo and geo != "All":
            parts.append(f"AND market = '{geo}'")
        channel = filters.get("channel", "")
        if channel and channel != "All":
            parts.append(f"AND smoothed_channel = '{channel}'")
        product = filters.get("product", "")
        if product and product != "All":
            mapped = self._PRODUCT_MAP.get(product)
            if mapped:
                parts.append(f"AND product_genus = '{mapped}'")
        return " ".join(parts)
    
    async def _fetch_kpis_databricks(self, start_date: str, end_date: str, filters: Dict[str, str]) -> pd.DataFrame:
        """
        Fetch KPI data from Databricks.
        Won / opened metrics query federated.sales.* (clean grain, no snapshot logic).
        Active pipeline still queries the MDL snapshot (no federated equivalent yet).
        Targets come from metis_targets_summary with real paced values.
        """
        fed = self._build_filter_federated(filters)
        mdl = self._build_filter_mdl(filters)
        
        # Query 8 KPIs: federated tables for won/created/targets; MDL snapshot for active pipeline
        query = f"""
        WITH won AS (
            SELECT
                COUNT(DISTINCT salesforce_opportunity_id) AS won_volume,
                COALESCE(SUM(amount_towards_plan), 0)     AS won_pipeline
            FROM federated.sales.metis_won_opps_fact
            WHERE DATE_TRUNC('quarter', close_date) = DATE_TRUNC('quarter', CURRENT_DATE())
              {fed}
        ),
        prev_won AS (
            -- Same point last quarter using the QoQ flag
            SELECT
                COUNT(DISTINCT salesforce_opportunity_id) AS prev_won_volume,
                COALESCE(SUM(amount_towards_plan), 0)     AS prev_won_pipeline
            FROM federated.sales.metis_won_opps_fact
            WHERE is_in_qoq_period = TRUE
              AND DATE_TRUNC('quarter', close_date) = ADD_MONTHS(DATE_TRUNC('quarter', CURRENT_DATE()), -3)
              {fed}
        ),
        created AS (
            SELECT
                COUNT(DISTINCT salesforce_opportunity_id) AS opps_created,
                COALESCE(SUM(amount_towards_plan), 0)     AS created_pipeline
            FROM federated.sales.metis_opened_opps_fact
            WHERE DATE_TRUNC('quarter', pipeline_entered_date) = DATE_TRUNC('quarter', CURRENT_DATE())
              {fed}
        ),
        tgt AS (
            -- Real paced targets from metis_targets_summary
            SELECT
                COALESCE(SUM(paced_won_amount),    0) AS target_won_pipeline,
                COALESCE(SUM(paced_won_opps),      0) AS target_won_volume,
                COALESCE(SUM(paced_opened_amount), 0) AS target_created_pipeline,
                COALESCE(SUM(paced_opened_opps),   0) AS target_opps_created
            FROM federated.sales.metis_targets_summary
            WHERE quarter_start_date = DATE_TRUNC('quarter', CURRENT_DATE())
              AND plan_version = 'Plan'
              {fed}
        ),
        snap AS (
            SELECT MAX(data_day) AS latest_day
            FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
        ),
        active AS (
            -- Active pipeline: no federated equivalent, still uses MDL snapshot
            SELECT COALESCE(SUM(amount_towards_plan), 0) AS active_pipeline
            FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
            WHERE data_day = (SELECT latest_day FROM snap)
              AND stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
              AND xtxtype <> 'Cancel'
              {mdl}
        )
        SELECT 'won_pipeline'     AS metric_name,
               w.won_pipeline     AS metric_value,
               t.target_won_pipeline   AS target_value,
               p.prev_won_pipeline     AS previous_period_value
          FROM won w, tgt t, prev_won p
        UNION ALL
        SELECT 'won_volume', w.won_volume, t.target_won_volume, p.prev_won_volume
          FROM won w, tgt t, prev_won p
        UNION ALL
        SELECT 'ads',
               COALESCE(w.won_pipeline  / NULLIF(w.won_volume,              0), 0),
               COALESCE(t.target_won_pipeline / NULLIF(t.target_won_volume, 0), 0),
               COALESCE(p.prev_won_pipeline   / NULLIF(p.prev_won_volume,   0), 0)
          FROM won w, tgt t, prev_won p
        UNION ALL
        SELECT 'opps_created', c.opps_created, t.target_opps_created, c.opps_created * 0.85
          FROM created c, tgt t
        UNION ALL
        SELECT 'created_pipeline', c.created_pipeline, t.target_created_pipeline, c.created_pipeline * 0.85
          FROM created c, tgt t
        UNION ALL
        SELECT 'active_pipeline', a.active_pipeline, t.target_created_pipeline * 0.8, a.active_pipeline * 0.95
          FROM active a, tgt t
        UNION ALL
        SELECT 'close_rate', w.won_volume * 100.0 / NULLIF(c.opps_created, 0), 30.0, 28.0
          FROM won w, created c
        UNION ALL
        SELECT 'coverage', LEAST(a.active_pipeline / NULLIF(t.target_created_pipeline, 0), 10.0), 3.0, 2.8
          FROM active a, tgt t
        """
        return await self.execute_query_async(query)
    
    async def fetch_chart_data(
        self, 
        chart_type: str, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetch data for specific chart type
        
        TODO: Implement actual queries based on chart_type
        """
        
        query_map = {
            "revenue_by_region": """
                SELECT region, SUM(revenue) as total_revenue
                FROM sales_data
                WHERE sale_date BETWEEN ? AND ?
                GROUP BY region
            """,
            "monthly_trend": """
                SELECT 
                    DATEPART(month, sale_date) as month,
                    SUM(revenue) as revenue
                FROM sales_data
                WHERE sale_date BETWEEN ? AND ?
                GROUP BY DATEPART(month, sale_date)
                ORDER BY month
            """
        }
        
        try:
            query = query_map.get(chart_type)
            if not query:
                return self._get_mock_chart_data(chart_type)
            
            engine = self.get_connection()
            df = pd.read_sql(query, engine, params=[start_date, end_date])
            return df
        except Exception as e:
            print(f"Error fetching chart data: {e}")
            return self._get_mock_chart_data(chart_type)
    
    async def fetch_historical_data(self, metric: str) -> pd.DataFrame:
        """
        Fetch historical data for forecasting
        Should return DataFrame with columns: [ds (date), y (value)]
        """
        
        try:
            if self.use_databricks:
                return await asyncio.wait_for(
                    self._fetch_historical_databricks(metric),
                    timeout=20.0,
                )
            else:
                return self._get_mock_historical_data(metric)
        except asyncio.TimeoutError:
            print(f"[DataFetcher] fetch_historical_data timed out after 20s, using mock data")
            return self._get_mock_historical_data(metric)
        except Exception as e:
            print(f"Error fetching historical data: {e}")
            return self._get_mock_historical_data(metric)
    
    async def _fetch_historical_databricks(self, metric: str) -> pd.DataFrame:
        """Fetch historical data from Databricks for various metrics"""
        
        catalog = settings.databricks_catalog
        schema = settings.databricks_schema
        
        # Map metric names to queries
        if metric == 'arr' or metric == 'ending_arr':
            # --- Primary: partner_ending_arr ---
            primary_query = f"""
            SELECT
                data_month AS ds,
                SUM(MOM_ARR) AS y
            FROM {catalog}.{schema}.partner_ending_arr
            WHERE data_month >= ADD_MONTHS(CURRENT_DATE(), -14)
            GROUP BY data_month
            ORDER BY data_month
            """
            try:
                df_primary = self.execute_query(primary_query)
                if not df_primary.empty:
                    df_primary['ds'] = pd.to_datetime(df_primary['ds'])
                    df_primary.attrs['arr_source'] = 'partner_ending_arr'
                    return df_primary
            except Exception as e:
                print(f"partner_ending_arr unavailable ({e}), trying kpi_active_mrr_arr")

            # --- Fallback: kpi_active_mrr_arr (more current) ---
            fallback_query = """
            SELECT
                reporting_month AS ds,
                SUM(arr_in_usd) AS y
            FROM datagroup.datawarehouse.kpi_active_mrr_arr
            GROUP BY reporting_month
            ORDER BY reporting_month
            """
            try:
                df_fallback = self.execute_query(fallback_query)
                if not df_fallback.empty:
                    df_fallback['ds'] = pd.to_datetime(df_fallback['ds'])
                    df_fallback.attrs['arr_source'] = 'kpi_active_mrr_arr'
                    return df_fallback
            except Exception as e:
                print(f"kpi_active_mrr_arr also unavailable ({e})")

            # Both tables returned nothing — caller will use mock data
            empty = pd.DataFrame(columns=['ds', 'y'])
            empty.attrs['arr_source'] = None
            return empty

        elif metric == 'arr_forecast' or metric == 'arr_actuals':
            # ARR from forecast_prophet table (actuals from hive_metastore)
            query = f"""
            SELECT 
                ds,
                SUM(actuals) as y
            FROM hive_metastore.mdl_sales_analytics.forecast_prophet
            WHERE ds >= DATE_SUB(CURRENT_DATE(), 365)
              AND actuals IS NOT NULL
              AND actuals > 0
            GROUP BY ds
            ORDER BY ds
            """
        
        elif metric == 'won_pipeline':
            # Won pipeline by close date
            query = f"""
            SELECT 
                close_date as ds,
                SUM(amount_towards_plan) as y
            FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
            WHERE is_won = 'True'
              AND xtxtype <> 'Cancel'
              AND close_date >= DATE_SUB(CURRENT_DATE(), 365)
            GROUP BY close_date
            ORDER BY close_date
            """
        
        elif metric == 'active_pipeline':
            # Active pipeline over time
            query = f"""
            SELECT 
                data_day as ds,
                SUM(amount_towards_plan) as y
            FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
            WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
              AND data_day >= DATE_SUB(CURRENT_DATE(), 365)
            GROUP BY data_day
            ORDER BY data_day
            """
        
        elif metric == 'created_pipeline':
            # Pipeline creation over time
            query = f"""
            SELECT 
                pipeline_entered_date as ds,
                SUM(amount_towards_plan) as y
            FROM {catalog}.{schema}.gaim_snapshot_pipeline_created_cq_daily
            WHERE pipeline_entered_date >= DATE_SUB(CURRENT_DATE(), 365)
            GROUP BY pipeline_entered_date
            ORDER BY pipeline_entered_date
            """
        
        else:
            # Default mock data for unknown metrics
            return self._get_mock_historical_data(metric)
        
        df = self.execute_query(query)
        
        # Ensure ds column is datetime
        df['ds'] = pd.to_datetime(df['ds'])
        
        return df
    
    def _get_mock_kpi_data(self) -> pd.DataFrame:
        """Mock data for development - 8 KPIs matching Performance Hub"""
        return pd.DataFrame({
            'metric_name': [
                'won_pipeline', 'won_volume', 'ads', 'opps_created',
                'created_pipeline', 'active_pipeline', 'close_rate', 'coverage'
            ],
            'metric_value': [4000000, 1662, 2390, 4022, 18700000, 12000000, 31.8, 320],
            'target_value': [20400000, 7076, 2887, 17414, 88300000, 10000000, 30.0, 300],
            'previous_period_value': [3700000, 1500, 2300, 3800, 17000000, 11400000, 31.3, 310]
        })
    
    def _get_mock_chart_data(self, chart_type: str) -> pd.DataFrame:
        """Mock chart data for development"""
        if chart_type == "revenue_by_region":
            return pd.DataFrame({
                'region': ['North', 'South', 'East', 'West', 'Central'],
                'total_revenue': [1200000, 980000, 1500000, 1750000, 1100000]
            })
        elif chart_type == "monthly_trend":
            return pd.DataFrame({
                'month': list(range(1, 7)),
                'revenue': [1800000, 1950000, 2100000, 2050000, 2200000, 2300000]
            })
        return pd.DataFrame()

    # ── Pre-computed ARR forecast from Databricks notebook ────────────────────

    ARR_FORECAST_TABLE = (
        "datagroup_mdl.mdl_sales_analytics.arr_forecast_prophet"
    )

    async def fetch_arr_forecast_results(
        self,
        geo: str = "Total",
        product_group: str = "Total",
        run_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Read pre-computed Prophet forecast from the Delta table written by the
        ARR Forecast Prophet Databricks notebook.

        Returns a DataFrame with columns:
            forecast_date, most_likely, worst_case, best_case,
            actual, is_historical, model_mape, run_date
        Falls back to an empty DataFrame (caller can fall through to inline Prophet).
        """
        if not self.use_databricks:
            return pd.DataFrame()

        run_filter = (
            f"run_date = '{run_date}'"
            if run_date
            else f"run_date = (SELECT MAX(run_date) FROM {self.ARR_FORECAST_TABLE})"
        )
        query = f"""
            SELECT
                CAST(forecast_date AS DATE) AS forecast_date,
                most_likely,
                worst_case,
                best_case,
                actual,
                is_historical,
                model_mape,
                run_date
            FROM {self.ARR_FORECAST_TABLE}
            WHERE geo           = '{geo}'
              AND product_group = '{product_group}'
              AND {run_filter}
            ORDER BY forecast_date
        """
        try:
            df = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.execute_query(query)
                ),
                timeout=15.0,
            )
            if not df.empty:
                df["forecast_date"] = pd.to_datetime(df["forecast_date"])
            return df
        except Exception as e:
            print(f"[DataFetcher] fetch_arr_forecast_results failed: {e}")
            return pd.DataFrame()

    def _get_mock_historical_data(self, metric: str) -> pd.DataFrame:
        """Mock historical data for forecasting"""
        dates = pd.date_range(end=datetime.now(), periods=180, freq='D')
        
        # Generate realistic mock data based on metric type
        if metric == 'arr' or metric == 'ending_arr':
            # ARR grows slowly over time with seasonal patterns
            base = 50000000
            values = [base + i * 50000 + (i % 90) * 100000 for i in range(180)]
        elif metric == 'won_pipeline':
            # Won pipeline has end-of-quarter spikes
            values = [1000000 + i * 5000 + (i % 30) * 10000 + (100000 if i % 90 > 85 else 0) for i in range(180)]
        else:
            values = [1000000 + i * 5000 + (i % 30) * 10000 for i in range(180)]
        
        return pd.DataFrame({'ds': dates, 'y': values})
    
    async def fetch_arr_by_segment(self, segment_type: str = 'product_genus') -> pd.DataFrame:
        """Fetch ARR segmented by product, channel, or region"""
        
        if not self.use_databricks:
            return self._get_mock_arr_segments()
        
        catalog = settings.databricks_catalog
        schema = settings.databricks_schema
        
        # Map segment types to column names
        segment_columns = {
            'product': 'product_genus',
            'product_genus': 'product_genus',
            'product_family': 'product_family',
            'channel': 'sales_channel',
            'sales_channel': 'sales_channel',
            'market': 'sales_market',
            'region': 'sales_market'
        }
        
        segment_col = segment_columns.get(segment_type, 'product_genus')
        
        query = f"""
        SELECT 
            data_month,
            {segment_col} as segment,
            SUM(MOM_ARR) as arr_value
        FROM {catalog}.{schema}.partner_ending_arr
        WHERE data_month >= DATE_SUB(CURRENT_DATE(), 365)
          AND {segment_col} IS NOT NULL
        GROUP BY data_month, {segment_col}
        ORDER BY data_month, {segment_col}
        """
        
        return await self.execute_query_async(query)
    
    def _get_mock_arr_segments(self) -> pd.DataFrame:
        """Mock ARR segment data"""
        months = pd.date_range(end=datetime.now(), periods=12, freq='M')
        segments = ['Product A', 'Product B', 'Product C']
        
        data = []
        for month in months:
            for segment in segments:
                base = {'Product A': 15000000, 'Product B': 20000000, 'Product C': 15000000}[segment]
                data.append({
                    'data_month': month,
                    'segment': segment,
                    'arr_value': base + (month.month * 100000)
                })
        
        return pd.DataFrame(data)
    
    async def fetch_prophet_forecast_data(self, segment_by: str = None) -> pd.DataFrame:
        """Fetch Prophet forecast data with actuals and scenarios from forecast_prophet table"""
        
        if not self.use_databricks:
            return self._get_mock_prophet_data()
        
        # Base query for forecast_prophet
        query = f"""
        SELECT 
            ds as date,
            product,
            sales_market,
            pe_account_flag,
            SUM(actuals) as actual_arr,
            SUM(most_likely) as forecast_most_likely,
            SUM(best_case) as forecast_best_case,
            SUM(worst_case) as forecast_worst_case,
            AVG(avg_deal_size) as avg_deal_size,
            AVG(avg_sales_cycle) as avg_sales_cycle,
            SUM(number_of_opps) as total_opportunities
        FROM hive_metastore.mdl_sales_analytics.forecast_prophet
        WHERE ds >= DATE_SUB(CURRENT_DATE(), 365)
        """
        
        if segment_by:
            query += f"GROUP BY ds, {segment_by}\n"
        else:
            query += "GROUP BY ds, product, sales_market, pe_account_flag\n"
        
        query += "ORDER BY ds"
        
        return await self.execute_query_async(query)
    
    async def fetch_win_probability_data(self) -> pd.DataFrame:
        """Fetch win probability data from opportunity_scoring table"""
        
        if not self.use_databricks:
            return self._get_mock_win_probability()
        
        query = f"""
        SELECT 
            close_date as date,
            product,
            sales_market,
            stage_name,
            COUNT(*) as opportunity_count,
            AVG(prob_won) as avg_win_probability,
            SUM(amount_towards_plan) as total_pipeline_value,
            SUM(amount_towards_plan * prob_won) as weighted_pipeline
        FROM hive_metastore.mdl_sales_analytics.opportunity_scoring
        WHERE close_date >= CURRENT_DATE()
          AND close_date <= DATE_ADD(CURRENT_DATE(), 180)
          AND prob_won IS NOT NULL
        GROUP BY close_date, product, sales_market, stage_name
        ORDER BY close_date
        """
        
        return await self.execute_query_async(query)
    
    async def fetch_forecast_accuracy_2024(self) -> pd.DataFrame:
        """Fetch 2024 forecast vs actuals for accuracy analysis"""
        
        if not self.use_databricks:
            return self._get_mock_accuracy_data()
        
        query = f"""
        SELECT 
            ds as date,
            product,
            sales_market,
            SUM(actuals) as actual_value,
            SUM(most_likely) as forecast_value,
            SUM(best_case) as best_case_value,
            SUM(worst_case) as worst_case_value,
            AVG('Percent Difference (%)') as accuracy_pct
        FROM hive_metastore.mdl_sales_analytics.forecast_prophet_2024
        WHERE actuals IS NOT NULL
          AND most_likely IS NOT NULL
        GROUP BY ds, product, sales_market
        ORDER BY ds
        """
        
        return await self.execute_query_async(query)
    
    def _get_mock_prophet_data(self) -> pd.DataFrame:
        """Mock Prophet forecast data"""
        dates = pd.date_range(end=datetime.now(), periods=90, freq='D')
        data = []
        for date in dates:
            base = 50000000 + (date - dates[0]).days * 10000
            data.append({
                'date': date,
                'product': 'Product A',
                'sales_market': 'NA',
                'pe_account_flag': 'Yes',
                'actual_arr': base if date < datetime.now() - timedelta(days=7) else None,
                'forecast_most_likely': base * 1.05,
                'forecast_best_case': base * 1.15,
                'forecast_worst_case': base * 0.95,
                'avg_deal_size': 25000,
                'avg_sales_cycle': 45,
                'total_opportunities': 100
            })
        return pd.DataFrame(data)
    
    def _get_mock_win_probability(self) -> pd.DataFrame:
        """Mock win probability data"""
        dates = pd.date_range(start=datetime.now(), periods=60, freq='D')
        stages = ['Discovery', 'Proposal', 'Negotiation', 'Closed Won']
        data = []
        for date in dates:
            for stage in stages:
                data.append({
                    'date': date,
                    'product': 'Product A',
                    'sales_market': 'NA',
                    'stage_name': stage,
                    'opportunity_count': 20,
                    'avg_win_probability': 0.3 if stage == 'Discovery' else 0.7,
                    'total_pipeline_value': 1000000,
                    'weighted_pipeline': 500000
                })
        return pd.DataFrame(data)
    
    def _get_mock_accuracy_data(self) -> pd.DataFrame:
        """Mock forecast accuracy data"""
        dates = pd.date_range(start='2024-01-01', end='2024-12-31', freq='W')
        data = []
        for date in dates:
            actual = 1000000 + (date - dates[0]).days * 5000
            forecast = actual * 1.03  # 3% forecast error
            data.append({
                'date': date,
                'product': 'Product A',
                'sales_market': 'NA',
                'actual_value': actual,
                'forecast_value': forecast,
                'best_case_value': forecast * 1.1,
                'worst_case_value': forecast * 0.9,
                'accuracy_pct': 3.0
            })
        return pd.DataFrame(data)
