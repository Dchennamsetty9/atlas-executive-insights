"""
Data extraction script - pulls 3 years of data from Databricks to local SQLite cache
Run this script to populate or refresh the local database
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path to import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from databricks import sql
import pandas as pd
import sqlite3
from config.settings import settings

# Target date range: last 3 years
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=3*365)

# SQLite database path
DB_PATH = Path(__file__).parent.parent / "data" / "cache.db"
DB_PATH.parent.mkdir(exist_ok=True)

def get_databricks_connection():
    """Create Databricks connection"""
    print(f"Connecting to Databricks: {settings.databricks_server_hostname}")
    return sql.connect(
        server_hostname=settings.databricks_server_hostname,
        http_path=settings.databricks_http_path,
        access_token=settings.databricks_access_token,
        catalog=settings.databricks_catalog,
        schema=settings.databricks_schema
    )

def extract_pipeline_data(conn):
    """Extract pipeline daily snapshot data"""
    print("\n📊 Extracting pipeline daily snapshot...")
    
    query = f"""
    SELECT 
        snapshot_date,
        fiscal_quarter,
        fiscal_year,
        kpi_name,
        kpi_value,
        target_value,
        segment,
        region,
        product_line
    FROM gaim_pipeline_daily_snapshot
    WHERE snapshot_date >= '{START_DATE.strftime('%Y-%m-%d')}'
    ORDER BY snapshot_date DESC
    """
    
    cursor = conn.cursor()
    cursor.execute(query)
    
    # Fetch all rows
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    
    df = pd.DataFrame(rows, columns=columns)
    df = df.replace([float('inf'), float('-inf')], None).fillna(value=None)
    
    print(f"✅ Extracted {len(df)} rows")
    return df

def extract_opportunity_data(conn):
    """Extract opportunity scoring data for win probability"""
    print("\n📊 Extracting opportunity scoring data...")
    
    query = f"""
    SELECT 
        opportunity_id,
        opportunity_name,
        created_date,
        close_date,
        amount,
        stage,
        probability,
        win_score,
        segment,
        region,
        owner_name
    FROM opportunity_scoring
    WHERE created_date >= '{START_DATE.strftime('%Y-%m-%d')}'
    ORDER BY created_date DESC
    """
    
    cursor = conn.cursor()
    cursor.execute(query)
    
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    
    df = pd.DataFrame(rows, columns=columns)
    df = df.replace([float('inf'), float('-inf')], None).fillna(value=None)
    
    print(f"✅ Extracted {len(df)} rows")
    return df

def extract_forecast_data(conn):
    """Extract Prophet forecast data"""
    print("\n📊 Extracting forecast data...")
    
    query = """
    SELECT 
        forecast_date,
        metric_name,
        forecast_value,
        lower_bound,
        upper_bound,
        model_version,
        created_at
    FROM forecast_prophet
    ORDER BY forecast_date DESC
    """
    
    cursor = conn.cursor()
    cursor.execute(query)
    
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    
    df = pd.DataFrame(rows, columns=columns)
    df = df.replace([float('inf'), float('-inf')], None).fillna(value=None)
    
    print(f"✅ Extracted {len(df)} rows")
    return df

def create_sqlite_schema(sqlite_conn):
    """Create SQLite tables with proper schema"""
    print("\n🔧 Creating SQLite schema...")
    
    cursor = sqlite_conn.cursor()
    
    # Pipeline data table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date DATE NOT NULL,
        fiscal_quarter TEXT,
        fiscal_year INTEGER,
        kpi_name TEXT NOT NULL,
        kpi_value REAL,
        target_value REAL,
        segment TEXT,
        region TEXT,
        product_line TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_date ON pipeline_daily(snapshot_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_kpi ON pipeline_daily(kpi_name)")
    
    # Opportunity data table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        opportunity_id TEXT UNIQUE NOT NULL,
        opportunity_name TEXT,
        created_date DATE,
        close_date DATE,
        amount REAL,
        stage TEXT,
        probability REAL,
        win_score REAL,
        segment TEXT,
        region TEXT,
        owner_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_opp_created ON opportunities(created_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_opp_stage ON opportunities(stage)")
    
    # Forecast data table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS forecasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forecast_date DATE NOT NULL,
        metric_name TEXT NOT NULL,
        forecast_value REAL,
        lower_bound REAL,
        upper_bound REAL,
        model_version TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_forecast_date ON forecasts(forecast_date)")
    
    # Metadata table to track refreshes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS refresh_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT NOT NULL,
        refresh_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        row_count INTEGER,
        status TEXT
    )
    """)
    
    sqlite_conn.commit()
    print("✅ Schema created")

def store_data(sqlite_conn, pipeline_df, opportunity_df, forecast_df):
    """Store extracted data into SQLite"""
    print("\n💾 Storing data in SQLite...")
    
    cursor = sqlite_conn.cursor()
    
    # Clear existing data
    cursor.execute("DELETE FROM pipeline_daily")
    cursor.execute("DELETE FROM opportunities")
    cursor.execute("DELETE FROM forecasts")
    
    # Insert new data
    pipeline_df.to_sql('pipeline_daily', sqlite_conn, if_exists='append', index=False)
    print(f"✅ Stored {len(pipeline_df)} pipeline records")
    
    opportunity_df.to_sql('opportunities', sqlite_conn, if_exists='append', index=False)
    print(f"✅ Stored {len(opportunity_df)} opportunity records")
    
    forecast_df.to_sql('forecasts', sqlite_conn, if_exists='append', index=False)
    print(f"✅ Stored {len(forecast_df)} forecast records")
    
    # Record refresh metadata
    cursor.execute("""
        INSERT INTO refresh_metadata (table_name, row_count, status)
        VALUES ('pipeline_daily', ?, 'success')
    """, (len(pipeline_df),))
    
    cursor.execute("""
        INSERT INTO refresh_metadata (table_name, row_count, status)
        VALUES ('opportunities', ?, 'success')
    """, (len(opportunity_df),))
    
    cursor.execute("""
        INSERT INTO refresh_metadata (table_name, row_count, status)
        VALUES ('forecasts', ?, 'success')
    """, (len(forecast_df),))
    
    sqlite_conn.commit()
    
    # Show database stats
    file_size = DB_PATH.stat().st_size / (1024 * 1024)  # MB
    print(f"\n📦 Database size: {file_size:.2f} MB")

def main():
    """Main extraction workflow"""
    print("=" * 60)
    print("🚀 ATLAS Executive Insights - Data Extraction")
    print("=" * 60)
    print(f"📅 Date range: {START_DATE.date()} to {END_DATE.date()}")
    print(f"💾 Target database: {DB_PATH}")
    
    try:
        # Connect to Databricks
        db_conn = get_databricks_connection()
        
        # Extract data
        pipeline_df = extract_pipeline_data(db_conn)
        opportunity_df = extract_opportunity_data(db_conn)
        forecast_df = extract_forecast_data(db_conn)
        
        db_conn.close()
        print("\n✅ Databricks connection closed")
        
        # Connect to SQLite
        sqlite_conn = sqlite3.connect(str(DB_PATH))
        
        # Create schema
        create_sqlite_schema(sqlite_conn)
        
        # Store data
        store_data(sqlite_conn, pipeline_df, opportunity_df, forecast_df)
        
        sqlite_conn.close()
        
        print("\n" + "=" * 60)
        print("✅ EXTRACTION COMPLETE!")
        print("=" * 60)
        print(f"🎯 Data is ready at: {DB_PATH}")
        print("🔄 Next: Restart backend to use local data")
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
