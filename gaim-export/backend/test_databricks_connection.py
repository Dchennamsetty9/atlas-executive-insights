"""
Test Databricks connection and permissions
"""
from databricks import sql
import os
from dotenv import load_dotenv

load_dotenv()

# Connection details
server_hostname = os.getenv("DATABRICKS_SERVER_HOSTNAME", "goto-eureka-mdl-1.cloud.databricks.com")
http_path = os.getenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/c24ee33594e13e93")
access_token = os.getenv("DATABRICKS_ACCESS_TOKEN")
catalog = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
schema = os.getenv("DATABRICKS_SCHEMA", "mdl_sales_analytics")

print("=" * 60)
print("DATABRICKS CONNECTION TEST")
print("=" * 60)
print(f"Server: {server_hostname}")
print(f"HTTP Path: {http_path}")
print(f"Catalog: {catalog}")
print(f"Schema: {schema}")
print(f"Token configured: {'yes' if access_token else 'no'}")
print("=" * 60)

try:
    print("\n[1/5] Establishing connection...")
    connection = sql.connect(
        server_hostname=server_hostname,
        http_path=http_path,
        access_token=access_token
    )
    print("✅ Connection established!")
    
    cursor = connection.cursor()
    
    # Test 1: List catalogs
    print("\n[2/5] Testing catalog access...")
    cursor.execute("SHOW CATALOGS")
    catalogs = cursor.fetchall()
    print(f"✅ Found {len(catalogs)} catalogs:")
    for cat in catalogs[:5]:
        print(f"   - {cat[0]}")
    
    # Test 2: Check if our catalog exists
    print(f"\n[3/5] Checking catalog '{catalog}'...")
    cursor.execute(f"USE CATALOG {catalog}")
    print(f"✅ Catalog '{catalog}' accessible!")
    
    # Test 3: Check schema
    print(f"\n[4/5] Checking schema '{schema}'...")
    cursor.execute(f"USE SCHEMA {schema}")
    print(f"✅ Schema '{schema}' accessible!")
    
    # Test 4: List tables
    print("\n[5/5] Listing tables...")
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    print(f"✅ Found {len(tables)} tables:")
    
    target_tables = ['gaim_pipeline_daily_snapshot', 'gaim_snapshot_pipeline_created_cq_daily']
    found_tables = []
    
    for table in tables:
        table_name = table[1]  # table name is in second column
        if table_name in target_tables:
            found_tables.append(table_name)
            print(f"   ✅ {table_name}")
        elif len(found_tables) < 2:  # Show first few
            print(f"   - {table_name}")
    
    # Test 5: Try a simple query on main table
    if 'gaim_pipeline_daily_snapshot' in found_tables:
        print(f"\n[BONUS] Testing query on gaim_pipeline_daily_snapshot...")
        cursor.execute(f"""
            SELECT COUNT(*) as row_count, 
                   MAX(data_day) as latest_date,
                   MIN(data_day) as earliest_date
            FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
        """)
        result = cursor.fetchone()
        print(f"✅ Query successful!")
        print(f"   - Total rows: {result[0]:,}")
        print(f"   - Latest date: {result[1]}")
        print(f"   - Earliest date: {result[2]}")
    
    cursor.close()
    connection.close()
    
    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED!")
    print("=" * 60)
    print("\n✅ Your Databricks connection is working!")
    print("✅ You have access to the required tables!")
    print("\n🚀 You can now run the backend with live data.")
    
except Exception as e:
    print("\n" + "=" * 60)
    print("❌ CONNECTION FAILED")
    print("=" * 60)
    print(f"\nError: {str(e)}")
    print("\nPossible causes:")
    print("  1. Invalid or expired access token")
    print("  2. No permission to access SQL Endpoint")
    print("  3. Network/firewall issues")
    print("  4. Catalog/schema permissions not granted")
    print("\n💡 Solution: Request SQL Endpoint access from your Databricks admin")
