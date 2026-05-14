"""
Load CSV files downloaded from Databricks into SQLite cache
Run this after manually downloading data from Databricks
"""
import pandas as pd
import sqlite3
from pathlib import Path
from datetime import datetime

# SQLite database path
DB_PATH = Path(__file__).parent.parent / "data" / "cache.db"
CSV_FOLDER = Path(__file__).parent.parent / "data" / "csv_imports"

def create_schema(conn):
    """Create SQLite tables"""
    cursor = conn.cursor()
    
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
    
    # Metadata table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS refresh_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT NOT NULL,
        refresh_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        row_count INTEGER,
        status TEXT
    )
    """)
    
    conn.commit()
    print("✅ Schema created")

def load_csv_files(conn):
    """Load all CSV files from csv_imports folder"""
    
    if not CSV_FOLDER.exists():
        print(f"❌ CSV folder not found: {CSV_FOLDER}")
        print(f"📁 Create folder and add CSV files:")
        print(f"   mkdir {CSV_FOLDER}")
        return False
    
    csv_files = list(CSV_FOLDER.glob("*.csv"))
    
    if not csv_files:
        print(f"⚠️ No CSV files found in: {CSV_FOLDER}")
        return False
    
    print(f"\n📂 Found {len(csv_files)} CSV file(s)")
    
    cursor = conn.cursor()
    
    for csv_file in csv_files:
        print(f"\n📊 Loading: {csv_file.name}")
        
        try:
            # Read CSV
            df = pd.read_csv(csv_file)
            print(f"   Rows: {len(df)}")
            print(f"   Columns: {', '.join(df.columns[:5])}{'...' if len(df.columns) > 5 else ''}")
            
            # Determine table based on filename or columns
            filename_lower = csv_file.stem.lower()
            
            if 'pipeline' in filename_lower or 'snapshot' in filename_lower:
                table_name = 'pipeline_daily'
                # Map columns (adjust based on your CSV structure)
                required_cols = ['snapshot_date', 'kpi_name', 'kpi_value']
                
            elif 'opportunity' in filename_lower or 'opp' in filename_lower:
                table_name = 'opportunities'
                required_cols = ['opportunity_id', 'created_date']
                
            elif 'forecast' in filename_lower:
                table_name = 'forecasts'
                required_cols = ['forecast_date', 'forecast_value']
                
            else:
                print(f"   ⚠️ Unknown file type - skipping")
                continue
            
            # Check if required columns exist
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                print(f"   ⚠️ Missing columns: {missing_cols}")
                print(f"   Available columns: {list(df.columns)}")
                continue
            
            # Clean data
            df = df.replace([float('inf'), float('-inf')], None)
            df = df.fillna(value=None)
            
            # Clear existing data
            cursor.execute(f"DELETE FROM {table_name}")
            
            # Insert data
            df.to_sql(table_name, conn, if_exists='append', index=False)
            
            # Record metadata
            cursor.execute("""
                INSERT INTO refresh_metadata (table_name, row_count, status)
                VALUES (?, ?, 'success')
            """, (table_name, len(df)))
            
            conn.commit()
            
            print(f"   ✅ Loaded {len(df)} rows into {table_name}")
            
        except Exception as e:
            print(f"   ❌ Error loading {csv_file.name}: {e}")
            continue
    
    return True

def main():
    print("=" * 60)
    print("📥 CSV Import - Manual Data Load")
    print("=" * 60)
    
    # Create folder if it doesn't exist
    CSV_FOLDER.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Connect to SQLite
    conn = sqlite3.connect(str(DB_PATH))
    
    # Create schema
    create_schema(conn)
    
    # Load CSV files
    success = load_csv_files(conn)
    
    if success:
        # Show database stats
        cursor = conn.cursor()
        
        print("\n" + "=" * 60)
        print("📊 Database Summary")
        print("=" * 60)
        
        for table in ['pipeline_daily', 'opportunities', 'forecasts']:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"{table:20s}: {count:,} rows")
        
        # Get file size
        file_size = DB_PATH.stat().st_size / (1024 * 1024)  # MB
        print(f"\n💾 Database size: {file_size:.2f} MB")
        print(f"📂 Location: {DB_PATH}")
        
        print("\n✅ IMPORT COMPLETE!")
        print("🚀 Restart backend to use the data: py main.py")
    else:
        print("\n" + "=" * 60)
        print("📋 Instructions:")
        print("=" * 60)
        print(f"1. Create CSV folder: {CSV_FOLDER}")
        print(f"2. Download data from Databricks and save as CSV")
        print(f"3. Place CSV files in the folder")
        print(f"4. Run this script again: py scripts/load_csv.py")
        print("\nSee MANUAL_DATA_LOAD.md for detailed instructions")
    
    conn.close()

if __name__ == "__main__":
    main()
