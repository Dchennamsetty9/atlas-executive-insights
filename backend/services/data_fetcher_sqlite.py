"""
SQLite-based data fetcher - uses local cache for fast performance
Falls back to Databricks if cache doesn't exist
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import sqlite3

try:
    from databricks import sql as databricks_sql
    DATABRICKS_AVAILABLE = True
except ImportError:
    DATABRICKS_AVAILABLE = False

from config.settings import settings

# SQLite cache path
CACHE_DB = Path(__file__).parent.parent / "data" / "cache.db"


class DataFetcherSQLite:
    """Fetch data from local SQLite cache (fast) with Databricks fallback"""
    
    def __init__(self):
        self.cache_exists = CACHE_DB.exists()
        self.use_cache = self.cache_exists
        print(f"💾 SQLite cache: {'FOUND' if self.cache_exists else 'NOT FOUND'} at {CACHE_DB}")
        
        if not self.cache_exists:
            print("⚠️ No local cache - run 'python scripts/extract_data.py' to create it")
            self.databricks_connection = None
    
    def get_cache_connection(self) -> sqlite3.Connection:
        """Get SQLite connection"""
        if not self.cache_exists:
            raise FileNotFoundError(f"Cache database not found: {CACHE_DB}")
        return sqlite3.connect(str(CACHE_DB))
    
    def get_databricks_connection(self):
        """Get Databricks connection as fallback"""
        if not DATABRICKS_AVAILABLE:
            raise ImportError("Databricks connector not available")
        
        if not self.databricks_connection:
            self.databricks_connection = databricks_sql.connect(
                server_hostname=settings.databricks_server_hostname,
                http_path=settings.databricks_http_path,
                access_token=settings.databricks_access_token
            )
        return self.databricks_connection
    
    def execute_query(self, query: str, use_cache: bool = True) -> pd.DataFrame:
        """Execute SQL query - prioritize cache, fallback to Databricks"""
        if use_cache and self.cache_exists:
            conn = self.get_cache_connection()
            df = pd.read_sql_query(query, conn)
            conn.close()
        else:
            # Fallback to Databricks
            conn = self.get_databricks_connection()
            cursor = conn.cursor()
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()
            cursor.close()
            df = pd.DataFrame(data, columns=columns)
        
        # Clean data for JSON serialization
        df = df.replace([float('inf'), float('-inf')], None)
        df = df.fillna(value=None)
        
        return df
    
    async def fetch_kpi_data(
        self, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetch 8 KPI metrics from local cache
        """
        
        # Default to current quarter if no dates provided
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            today = datetime.now()
            quarter = (today.month - 1) // 3 + 1
            start_date = datetime(today.year, (quarter - 1) * 3 + 1, 1).strftime("%Y-%m-%d")
        
        try:
            return await self._fetch_kpis_from_cache(start_date, end_date)
        except Exception as e:
            print(f"Error fetching KPI data: {e}")
            # Return mock data as last resort
            return self._get_mock_kpi_data()
    
    async def _fetch_kpis_from_cache(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch KPIs from SQLite cache"""
        
        query = f"""
        WITH latest_snapshot AS (
            SELECT MAX(snapshot_date) as latest_date
            FROM pipeline_daily
        ),
        kpi_aggregates AS (
            SELECT 
                kpi_name,
                SUM(kpi_value) as current_value,
                AVG(target_value) as target_avg,
                snapshot_date
            FROM pipeline_daily
            WHERE snapshot_date = (SELECT latest_date FROM latest_snapshot)
              AND snapshot_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY kpi_name, snapshot_date
        ),
        previous_period AS (
            SELECT 
                kpi_name,
                SUM(kpi_value) as prev_value
            FROM pipeline_daily
            WHERE snapshot_date BETWEEN date('{start_date}', '-90 days') AND date('{end_date}', '-90 days')
            GROUP BY kpi_name
        )
        SELECT 
            k.kpi_name as metric_name,
            k.current_value as metric_value,
            k.target_avg as target_value,
            COALESCE(p.prev_value, k.current_value * 0.9) as previous_period_value
        FROM kpi_aggregates k
        LEFT JOIN previous_period p ON k.kpi_name = p.kpi_name
        ORDER BY k.kpi_name
        """
        
        return self.execute_query(query, use_cache=True)
    
    async def fetch_historical_data(self, metric: str = "arr") -> pd.DataFrame:
        """
        Fetch historical data for forecasting
        Returns DataFrame with columns: [ds (date), y (value)]
        """
        
        try:
            query = f"""
            SELECT 
                snapshot_date as ds,
                SUM(kpi_value) as y
            FROM pipeline_daily
            WHERE kpi_name LIKE '%{metric}%'
              OR kpi_name LIKE '%pipeline%'
            GROUP BY snapshot_date
            ORDER BY snapshot_date
            """
            
            df = self.execute_query(query, use_cache=True)
            
            # Prophet expects columns named 'ds' and 'y'
            if 'ds' not in df.columns or 'y' not in df.columns:
                return self._get_mock_historical_data(metric)
            
            return df
            
        except Exception as e:
            print(f"Error fetching historical data: {e}")
            return self._get_mock_historical_data(metric)
    
    async def fetch_arr_history(self) -> pd.DataFrame:
        """Fetch ARR historical trend"""
        
        try:
            query = """
            SELECT 
                snapshot_date as date,
                SUM(CASE WHEN kpi_name LIKE '%arr%' OR kpi_name LIKE '%revenue%' THEN kpi_value ELSE 0 END) as arr
            FROM pipeline_daily
            WHERE snapshot_date >= date('now', '-12 months')
            GROUP BY snapshot_date
            ORDER BY snapshot_date
            """
            
            df = self.execute_query(query, use_cache=True)
            
            if df.empty:
                return self._get_mock_arr_history()
            
            return df
            
        except Exception as e:
            print(f"Error fetching ARR history: {e}")
            return self._get_mock_arr_history()
    
    async def fetch_pipeline_breakdown(self) -> pd.DataFrame:
        """Fetch pipeline breakdown by stage"""
        
        try:
            query = """
            SELECT 
                kpi_name as category,
                SUM(kpi_value) as value,
                AVG(target_value) as target
            FROM pipeline_daily
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM pipeline_daily)
              AND (kpi_name LIKE '%won%' OR kpi_name LIKE '%created%' OR kpi_name LIKE '%active%')
            GROUP BY kpi_name
            """
            
            df = self.execute_query(query, use_cache=True)
            
            if df.empty:
                return self._get_mock_pipeline_breakdown()
            
            return df
            
        except Exception as e:
            print(f"Error fetching pipeline breakdown: {e}")
            return self._get_mock_pipeline_breakdown()
    
    async def fetch_forecast_data(self) -> pd.DataFrame:
        """Fetch Prophet forecast data"""
        
        try:
            query = """
            SELECT 
                forecast_date as date,
                forecast_value as predicted,
                lower_bound as lower,
                upper_bound as upper
            FROM forecasts
            WHERE metric_name = 'arr'
            ORDER BY forecast_date
            """
            
            df = self.execute_query(query, use_cache=True)
            
            if df.empty:
                return self._get_mock_prophet_data()
            
            return df
            
        except Exception as e:
            print(f"Error fetching forecast data: {e}")
            return self._get_mock_prophet_data()
    
    async def fetch_win_probability(self) -> pd.DataFrame:
        """Fetch opportunity win probability data"""
        
        try:
            query = """
            SELECT 
                stage,
                COUNT(*) as count,
                AVG(probability) as avg_probability,
                AVG(win_score) as avg_win_score,
                SUM(amount) as total_amount
            FROM opportunities
            WHERE created_date >= date('now', '-90 days')
            GROUP BY stage
            ORDER BY avg_win_score DESC
            """
            
            df = self.execute_query(query, use_cache=True)
            
            if df.empty:
                return self._get_mock_win_probability()
            
            return df
            
        except Exception as e:
            print(f"Error fetching win probability: {e}")
            return self._get_mock_win_probability()
    
    async def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the cache"""
        
        if not self.cache_exists:
            return {
                "status": "not_found",
                "path": str(CACHE_DB),
                "message": "Run 'python scripts/extract_data.py' to create cache"
            }
        
        try:
            conn = self.get_cache_connection()
            cursor = conn.cursor()
            
            # Get row counts
            cursor.execute("SELECT COUNT(*) FROM pipeline_daily")
            pipeline_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM opportunities")
            opp_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM forecasts")
            forecast_count = cursor.fetchone()[0]
            
            # Get date ranges
            cursor.execute("SELECT MIN(snapshot_date), MAX(snapshot_date) FROM pipeline_daily")
            date_range = cursor.fetchone()
            
            # Get last refresh
            cursor.execute("SELECT MAX(refresh_date) FROM refresh_metadata")
            last_refresh = cursor.fetchone()[0]
            
            conn.close()
            
            # Get file size
            file_size_mb = CACHE_DB.stat().st_size / (1024 * 1024)
            
            return {
                "status": "ready",
                "path": str(CACHE_DB),
                "size_mb": round(file_size_mb, 2),
                "last_refresh": last_refresh,
                "date_range": {
                    "start": date_range[0],
                    "end": date_range[1]
                },
                "row_counts": {
                    "pipeline": pipeline_count,
                    "opportunities": opp_count,
                    "forecasts": forecast_count
                }
            }
            
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    
    # Mock data methods (fallback when cache is empty)
    
    def _get_mock_kpi_data(self) -> pd.DataFrame:
        """Mock KPI data for demo purposes"""
        return pd.DataFrame([
            {"metric_name": "won_pipeline", "metric_value": 2450000, "target_value": 2000000, "previous_period_value": 2150000},
            {"metric_name": "won_volume", "metric_value": 100, "target_value": 90, "previous_period_value": 95},
            {"metric_name": "ads", "metric_value": 24500, "target_value": 28000, "previous_period_value": 29800},
            {"metric_name": "opps_created", "metric_value": 195, "target_value": 220, "previous_period_value": 230},
            {"metric_name": "created_pipeline", "metric_value": 9200000, "target_value": 7500000, "previous_period_value": 7800000},
            {"metric_name": "active_pipeline", "metric_value": 12000000, "target_value": 10000000, "previous_period_value": 11500000},
            {"metric_name": "close_rate", "metric_value": 31.8, "target_value": 30.0, "previous_period_value": 31.3},
            {"metric_name": "coverage", "metric_value": 2.7, "target_value": 3.0, "previous_period_value": 3.1}
        ])
    
    def _get_mock_historical_data(self, metric: str) -> pd.DataFrame:
        """Mock historical data for Prophet"""
        dates = pd.date_range(start='2023-01-01', end='2026-04-01', freq='MS')
        values = [48000000 + i * 1000000 + (i % 4) * 500000 for i in range(len(dates))]
        return pd.DataFrame({"ds": dates, "y": values})
    
    def _get_mock_arr_history(self) -> pd.DataFrame:
        """Mock ARR history"""
        dates = pd.date_range(start='2025-01-01', end='2025-12-31', freq='MS')
        values = [48000000 + i * 1200000 for i in range(len(dates))]
        return pd.DataFrame({"date": dates.strftime('%Y-%m-%d'), "arr": values})
    
    def _get_mock_pipeline_breakdown(self) -> pd.DataFrame:
        """Mock pipeline breakdown"""
        return pd.DataFrame([
            {"category": "Won", "value": 2450000, "target": 2000000},
            {"category": "Created", "value": 8500000, "target": 7500000},
            {"category": "Active", "value": 12000000, "target": 10000000}
        ])
    
    def _get_mock_prophet_data(self) -> pd.DataFrame:
        """Mock Prophet forecast"""
        future_dates = pd.date_range(start='2026-05-01', end='2026-08-01', freq='MS')
        predicted = [50100000 + i * 2200000 for i in range(len(future_dates))]
        lower = [val * 0.90 for val in predicted]
        upper = [val * 1.15 for val in predicted]
        
        return pd.DataFrame({
            "date": future_dates.strftime('%Y-%m-%d'),
            "predicted": predicted,
            "lower": lower,
            "upper": upper
        })
    
    def _get_mock_win_probability(self) -> pd.DataFrame:
        """Mock win probability"""
        return pd.DataFrame([
            {"stage": "Closed Won", "count": 50, "avg_probability": 100.0, "avg_win_score": 0.95, "total_amount": 2450000},
            {"stage": "Negotiation", "count": 25, "avg_probability": 75.0, "avg_win_score": 0.78, "total_amount": 1200000},
            {"stage": "Proposal", "count": 40, "avg_probability": 50.0, "avg_win_score": 0.55, "total_amount": 2100000},
            {"stage": "Discovery", "count": 80, "avg_probability": 25.0, "avg_win_score": 0.30, "total_amount": 3800000}
        ])
    
    def close(self):
        """Clean up connections"""
        if hasattr(self, 'databricks_connection') and self.databricks_connection:
            self.databricks_connection.close()
