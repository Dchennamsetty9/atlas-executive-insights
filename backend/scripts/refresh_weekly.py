"""
Weekly refresh script - updates local cache from Databricks
Can be run manually or scheduled as a cron job/Windows Task
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the extraction script
from scripts.extract_data import main as extract_main

if __name__ == "__main__":
    print("🔄 Running weekly data refresh...")
    extract_main()
    print("✅ Weekly refresh complete!")
