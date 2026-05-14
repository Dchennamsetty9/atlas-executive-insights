"""
Test Databricks connection for Atlas Executive Insights
Run this to verify your connection before starting the full backend
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

try:
    from databricks import sql
    print("✅ databricks-sql-connector is installed")
except ImportError:
    print("❌ databricks-sql-connector is NOT installed")
    print("   Run: pip install databricks-sql-connector")
    sys.exit(1)

from config.settings import settings

print("\n📋 Connection Settings:")
print(f"   Hostname: {settings.databricks_server_hostname}")
print(f"   HTTP Path: {settings.databricks_http_path}")
print(f"   Catalog: {settings.databricks_catalog}")
print(f"   Schema: {settings.databricks_schema}")
print(f"   Token: {'***' + settings.databricks_access_token[-4:] if settings.databricks_access_token else 'NOT SET'}")

if not settings.databricks_access_token:
    print("\n❌ DATABRICKS_ACCESS_TOKEN is not set in .env")
    print("   Generate a personal access token from Databricks and add it to backend/.env")
    sys.exit(1)

print("\n🔌 Connecting to Databricks...")

try:
    connection = sql.connect(
        server_hostname=settings.databricks_server_hostname,
        http_path=settings.databricks_http_path,
        access_token=settings.databricks_access_token
    )
    print("✅ Connection established!")
    
    cursor = connection.cursor()
    
    # Test 1: Count rows in main table
    print("\n📊 Test 1: Querying gaim_pipeline_daily_snapshot...")
    query1 = f"SELECT COUNT(*) as row_count FROM {settings.databricks_catalog}.{settings.databricks_schema}.gaim_pipeline_daily_snapshot"
    cursor.execute(query1)
    result = cursor.fetchone()
    print(f"   ✅ Found {result[0]:,} rows in gaim_pipeline_daily_snapshot")
    
    # Test 2: Get latest data date
    print("\n📅 Test 2: Checking latest data date...")
    query2 = f"SELECT MAX(data_day) as latest_date FROM {settings.databricks_catalog}.{settings.databricks_schema}.gaim_pipeline_daily_snapshot"
    cursor.execute(query2)
    result = cursor.fetchone()
    print(f"   ✅ Latest data: {result[0]}")
    
    # Test 3: Sample KPI query
    print("\n💰 Test 3: Sample KPI - Won Pipeline (Current Quarter)...")
    query3 = f"""
    SELECT 
        SUM(amount_towards_plan) as won_pipeline,
        COUNT(DISTINCT opportunities_created_ids) as won_deals
    FROM {settings.databricks_catalog}.{settings.databricks_schema}.gaim_pipeline_daily_snapshot
    WHERE is_won = 'True'
      AND YEAR(close_date) = YEAR(CURRENT_DATE())
      AND QUARTER(close_date) = QUARTER(CURRENT_DATE())
    """
    cursor.execute(query3)
    result = cursor.fetchone()
    won_pipeline = result[0] or 0
    won_deals = result[1] or 0
    print(f"   ✅ Won Pipeline: ${won_pipeline:,.0f}")
    print(f"   ✅ Won Deals: {won_deals:,}")
    if won_deals > 0:
        print(f"   ✅ Average Deal Size: ${won_pipeline/won_deals:,.0f}")
    
    cursor.close()
    connection.close()
    
    print("\n" + "="*60)
    print("🎉 All tests passed! Your connection is working.")
    print("="*60)
    print("\n✅ You can now start the backend server:")
    print("   python main.py")
    
except Exception as e:
    print(f"\n❌ Connection failed: {e}")
    print("\n💡 Troubleshooting:")
    print("   1. Verify your Databricks token is valid")
    print("   2. Check if you're on VPN (if required)")
    print("   3. Confirm you have access to datagroup_mdl.mdl_sales_analytics")
    print("   4. Try generating a new personal access token")
    sys.exit(1)
