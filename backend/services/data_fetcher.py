"""
Data fetcher service - connects to database and retrieves raw data

Version: 0.4.0 - Metis Federated Tables Mode
Last Updated: 2026-05-12

KPI Formulas: Based on Performance Hub semantic model (Atlas - Performance Hub.pbip)
- Won_Pipeline: SUM(amount_towards_plan) FROM metis_won_opps_fact
- Won_Volume: COUNT(DISTINCT salesforce_opportunity_id) FROM metis_won_opps_fact
- ADS: Won_Pipeline / Won_Volume
- x_OppsCreated_mdl: COUNT(DISTINCT salesforce_opportunity_id) FROM metis_opened_opps_fact
- xCreated_Pipeline: SUM(amount_towards_plan) FROM metis_opened_opps_fact
- Active_Pipeline: SUM(amount_towards_plan) FROM opened WHERE NOT IN won (LEFT JOIN)
- close_rate_vol: Won_Volume / Created_Opps
- xCvg_mdl: Active_Pipeline / Daily_Plan$ (capped at 10x)

Tables (federated.sales):
- metis_won_opps_fact: Won opportunities at daily granularity
- metis_opened_opps_fact: Opened opportunities at daily granularity
- metis_targets_summary: Quarterly targets with pacing calculations
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import pandas as pd
import os
import asyncio

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
        # Check if running in Databricks Apps (DATABRICKS_HOST is auto-provided)
        self.in_databricks = os.getenv("DATABRICKS_HOST") is not None
        self.use_databricks = DATABRICKS_AVAILABLE and (
            settings.databricks_access_token or self.in_databricks
        )
        self.connection_string = self._build_connection_string() if not self.use_databricks else None
        self.engine = None
        self.databricks_connection = None
        
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
        """Get database connection - supports both local and Databricks Apps deployment"""
        if self.use_databricks:
            if not self.databricks_connection:
                print(f"Connecting to Databricks: {settings.databricks_server_hostname[:50]}...")
                
                # Debug: Check what's in the environment
                client_id = os.getenv("DATABRICKS_CLIENT_ID")
                client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")
                token = os.getenv("DATABRICKS_TOKEN")
                
                print(f"DATABRICKS_CLIENT_ID present: {client_id is not None}")
                print(f"DATABRICKS_CLIENT_SECRET present: {client_secret is not None}")
                print(f"DATABRICKS_TOKEN present: {token is not None}")
                print(f"In Databricks Apps: {self.in_databricks}")
                
                try:
                    if self.in_databricks and (client_id and client_secret):
                        # Databricks Apps with OAuth (recommended)
                        print("Using Databricks Apps OAuth authentication")
                        cfg = Config()
                        
                        self.databricks_connection = databricks_sql.connect(
                            server_hostname=cfg.host,
                            http_path=settings.databricks_http_path,
                            credentials_provider=lambda: cfg.authenticate(),
                            _socket_timeout=10
                        )
                    elif token:
                        # Fallback: Direct token authentication
                        print("Using direct access token authentication")
                        self.databricks_connection = databricks_sql.connect(
                            server_hostname=settings.databricks_server_hostname,
                            http_path=settings.databricks_http_path,
                            access_token=token,
                            _socket_timeout=10
                        )
                    elif settings.databricks_access_token:
                        # Local development with provided token
                        print("Using provided access token (local development)")
                        self.databricks_connection = databricks_sql.connect(
                            server_hostname=settings.databricks_server_hostname,
                            http_path=settings.databricks_http_path,
                            access_token=settings.databricks_access_token,
                            _socket_timeout=10
                        )
                    else:
                        raise Exception("No valid authentication credentials found! Databricks Apps should provide DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET.")
                    
                    print("✅ Connected to Databricks successfully")
                except Exception as e:
                    print(f"❌ Failed to connect to Databricks: {str(e)}")
                    raise
            return self.databricks_connection
        else:
            if not self.engine:
                conn_url = f"mssql+pyodbc:///?odbc_connect={self.connection_string}"
                self.engine = create_engine(conn_url)
            return self.engine
    
    def execute_query(self, query: str, params: List = None) -> pd.DataFrame:
        """Execute SQL query and return DataFrame - SYNCHRONOUS (use in thread pool)"""
        try:
            if self.use_databricks:
                connection = self.get_connection()
                cursor = connection.cursor()
                cursor.execute(query)
                columns = [desc[0] for desc in cursor.description]
                data = cursor.fetchall()
                cursor.close()
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
    
    async def execute_query_async(self, query: str, params: List = None, timeout: int = 30) -> pd.DataFrame:
        """Execute SQL query asynchronously with timeout"""
        try:
            # Run blocking query in thread pool with timeout
            return await asyncio.wait_for(
                asyncio.to_thread(self.execute_query, query, params),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            print(f"Query timeout after {timeout}s")
            raise Exception(f"Database query timed out after {timeout} seconds")
        except Exception as e:
            print(f"Query error: {str(e)}")
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
    
    def _build_filter_where_clause(self, filters: Dict[str, str], table_alias: str = "") -> str:
        """
        Build WHERE clause SQL from filters
        
        Args:
            filters: Dict with geo, channel, product
            table_alias: Table alias prefix (e.g., "g." for gaim_pipeline_daily_snapshot)
        
        Returns:
            SQL WHERE clause string (e.g., "AND sales_market = 'AMER' AND sales_channel = 'Enterprise'")
        """
        where_clauses = []
        prefix = f"{table_alias}." if table_alias else ""
        
        if filters.get("geo") and filters["geo"] != "All":
            where_clauses.append(f"{prefix}sales_market = '{filters['geo']}'")
        
        if filters.get("channel") and filters["channel"] != "All":
            where_clauses.append(f"{prefix}sales_channel = '{filters['channel']}'")
        
        if filters.get("product") and filters["product"] != "All":
            # Map product names to product_group column values
            product_map = {
                "Connect": "GoToConnect",
                "Engage": "GoToWebinar", 
                "Rescue": "Rescue",
                "Central": "Central",
                "Resolve": "Resolve"
            }
            product_value = product_map.get(filters["product"], filters["product"])
            where_clauses.append(f"{prefix}product_group = '{product_value}'")
        
        if where_clauses:
            return "AND " + " AND ".join(where_clauses)
        return ""
    
    async def _fetch_kpis_databricks(self, start_date: str, end_date: str, filters: Dict[str, str]) -> pd.DataFrame:
        """
        Fetch real KPI data from Databricks using exact Performance Hub formulas
        Based on: Atlas - Performance Hub.SemanticModel DAX measures
        
        **UPDATED to use Metis Federated Tables:**
        - federated.sales.metis_won_opps_fact (won opportunities)
        - federated.sales.metis_opened_opps_fact (opened/created opportunities)
        
        Args:
            start_date: Start date
            end_date: End date
            filters: Geography, Channel, Product filters
        """
        
        catalog = settings.databricks_catalog
        schema = settings.databricks_schema
        
        # Build filter WHERE clauses for different table aliases
        filter_clause = self._build_filter_where_clause(filters, "")
        
        # Query all 8 KPIs using Metis federated tables
        query = f"""
        WITH max_data_day AS (
            -- Get latest data snapshot date
            SELECT MAX(data_date) as latest_day
            FROM {catalog}.{schema}.metis_opened_opps_fact
        ),
        won_metrics AS (
            -- Won Pipeline $ and Won Volume #
            -- Uses metis_won_opps_fact (all rows are won opportunities)
            SELECT 
                COALESCE(SUM(amount_towards_plan), 0) as won_pipeline,
                COUNT(DISTINCT salesforce_opportunity_id) as won_volume
            FROM {catalog}.{schema}.metis_won_opps_fact
            WHERE data_date = (SELECT latest_day FROM max_data_day)
              {filter_clause}  -- Dynamic filters (geo, channel, product)
        ),
        created_metrics AS (
            -- Created Pipeline $ and Opps Created #
            -- Uses metis_opened_opps_fact for opportunities entering pipeline
            SELECT 
                COUNT(DISTINCT salesforce_opportunity_id) as opps_created,
                COALESCE(SUM(amount_towards_plan), 0) as created_pipeline
            FROM {catalog}.{schema}.metis_opened_opps_fact
            WHERE pipeline_entered_date BETWEEN '{start_date}' AND '{end_date}'
              {filter_clause}  -- Dynamic filters
        ),
        active_metrics AS (
            -- Active Pipeline $ = Opened opportunities - Won opportunities
            -- Uses LEFT JOIN to find opps that entered pipeline but haven't won yet
            SELECT 
                COALESCE(SUM(o.amount_towards_plan), 0) as active_pipeline
            FROM {catalog}.{schema}.metis_opened_opps_fact o
            LEFT JOIN {catalog}.{schema}.metis_won_opps_fact w
                ON o.salesforce_opportunity_id = w.salesforce_opportunity_id
            WHERE o.data_date = (SELECT latest_day FROM max_data_day)
              AND w.salesforce_opportunity_id IS NULL  -- Not in won table = still active
              {filter_clause}  -- Dynamic filters on opened table
        ),
        previous_period AS (
            -- Previous period metrics for trend calculation (90 days ago)
            SELECT 
                COALESCE(SUM(amount_towards_plan), 0) as prev_won_pipeline,
                COUNT(DISTINCT salesforce_opportunity_id) as prev_won_volume
            FROM {catalog}.{schema}.metis_won_opps_fact
            WHERE data_date = DATE_ADD((SELECT latest_day FROM max_data_day), -90)
              {filter_clause}  -- Dynamic filters
        )
        SELECT 
            -- Row 1: Won Pipeline $ (Performance Hub: Won_Pipeline)
            'won_pipeline' as metric_name,
            w.won_pipeline as metric_value,
            w.won_pipeline * 0.9 as target_value,
            pp.prev_won_pipeline as previous_period_value
        FROM won_metrics w, previous_period pp
        
        UNION ALL
        
        -- Row 2: Won Volume # (Performance Hub: Won_Volume)
        SELECT 
            'won_volume' as metric_name,
            w.won_volume as metric_value,
            w.won_volume * 0.9 as target_value,
            pp.prev_won_volume as previous_period_value
        FROM won_metrics w, previous_period pp
        
        UNION ALL
        
        -- Row 3: ADS $ (Performance Hub: ADS = Won_Pipeline / Won_Volume)
        SELECT 
            'ads' as metric_name,
            COALESCE(w.won_pipeline / NULLIF(w.won_volume, 0), 0) as metric_value,
            COALESCE(w.won_pipeline / NULLIF(w.won_volume, 0), 0) * 0.95 as target_value,
            COALESCE(pp.prev_won_pipeline / NULLIF(pp.prev_won_volume, 0), 0) as previous_period_value
        FROM won_metrics w, previous_period pp
        
        UNION ALL
        
        -- Row 4: Opps Created # (Performance Hub: x_OppsCreated_mdl)
        SELECT 
            'opps_created' as metric_name,
            c.opps_created as metric_value,
            c.opps_created * 0.9 as target_value,
            c.opps_created * 0.85 as previous_period_value
        FROM created_metrics c
        
        UNION ALL
        
        -- Row 5: Created Pipeline $ (Performance Hub: xCreated_Pipeline)
        SELECT 
            'created_pipeline' as metric_name,
            c.created_pipeline as metric_value,
            c.created_pipeline * 0.9 as target_value,
            c.created_pipeline * 0.85 as previous_period_value
        FROM created_metrics c
        
        UNION ALL
        
        -- Row 6: Active Pipeline $ (Performance Hub: Active_Pipeline)
        SELECT 
            'active_pipeline' as metric_name,
            a.active_pipeline as metric_value,
            a.active_pipeline * 0.8 as target_value,
            a.active_pipeline * 0.95 as previous_period_value
        FROM active_metrics a
        
        UNION ALL
        
        -- Row 7: Close Rate % (Performance Hub: close_rate_vol = Won_Volume / x_OppsCreated_mdl)
        SELECT 
            'close_rate' as metric_name,
            (w.won_volume * 100.0 / NULLIF(c.opps_created, 0)) as metric_value,
            30.0 as target_value,  -- Standard 30% close rate target
            28.0 as previous_period_value
        FROM won_metrics w, created_metrics c
        
        UNION ALL
        
        -- Row 8: Coverage x (Performance Hub: xCvg_mdl)
        -- FIXED: Should use Active_Pipeline / Daily_Plan$ (using proxy for now)
        -- TODO: Add targets table join for real Daily_Plan$ value
        SELECT 
            'coverage' as metric_name,
            LEAST(a.active_pipeline / NULLIF(c.created_pipeline * 0.33, 0), 10.0) as metric_value,  -- Capped at 10x
            3.0 as target_value,  -- 3x coverage target
            2.8 as previous_period_value
        FROM active_metrics a, created_metrics c
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
                return await self._fetch_historical_databricks(metric)
            else:
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
            # ARR from partner_ending_arr table
            query = f"""
            SELECT 
                data_month as ds,
                SUM(MOM_ARR) as y
            FROM {catalog}.{schema}.partner_ending_arr
            WHERE data_month >= DATE_SUB(CURRENT_DATE(), 365)
            GROUP BY data_month
            ORDER BY data_month
            """
        
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
            # Won pipeline by close date (using metis_won_opps_fact)
            query = f"""
            SELECT 
                close_date as ds,
                SUM(amount_towards_plan) as y
            FROM {catalog}.{schema}.metis_won_opps_fact
            WHERE close_date >= DATE_SUB(CURRENT_DATE(), 365)
            GROUP BY close_date
            ORDER BY close_date
            """
        
        elif metric == 'active_pipeline':
            # Active pipeline over time (opened but not won)
            query = f"""
            SELECT 
                o.data_date as ds,
                SUM(o.amount_towards_plan) as y
            FROM {catalog}.{schema}.metis_opened_opps_fact o
            LEFT JOIN {catalog}.{schema}.metis_won_opps_fact w
                ON o.salesforce_opportunity_id = w.salesforce_opportunity_id
            WHERE o.data_date >= DATE_SUB(CURRENT_DATE(), 365)
              AND w.salesforce_opportunity_id IS NULL  -- Not yet won
            GROUP BY o.data_date
            ORDER BY o.data_date
            """
        
        elif metric == 'created_pipeline':
            # Pipeline creation over time (using metis_opened_opps_fact)
            query = f"""
            SELECT 
                pipeline_entered_date as ds,
                SUM(amount_towards_plan) as y
            FROM {catalog}.{schema}.metis_opened_opps_fact
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
