#!/bin/bash
# build.sh — Pre-deployment build script for Atlas Executive Insights
#
# Run this BEFORE `databricks bundle deploy`. Databricks Apps does not run
# build commands; the compiled frontend must be present in frontend/dist/.
#
# Usage:
#   chmod +x build.sh
#   ./build.sh
#
# After this completes, commit the frontend/dist/ folder and deploy.

set -e  # Exit on first error

echo "========================================="
echo " Atlas Executive Insights — Pre-deploy Build"
echo "========================================="

# ── 1. Build frontend ─────────────────────────────────────────────────────
echo ""
echo "[1/2] Building React frontend..."
cd frontend
npm install --prefer-offline
npm run build
cd ..
echo "✅ Frontend built → frontend/dist/"

# ── 2. Verify backend imports cleanly ─────────────────────────────────────
echo ""
echo "[2/2] Verifying backend imports..."
cd backend
python -c "
import sys; sys.path.insert(0, '.')
import main
routes = [r.path for r in main.app.routes if hasattr(r, 'path')]
print(f'  ✅ {len(routes)} routes registered')
" 2>&1 | grep -v "plotly\|Importing"
cd ..

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "========================================="
echo " Build complete. Ready to deploy."
echo ""
echo " Next steps:"
echo "   git add frontend/dist/"
echo "   git commit -m 'chore: pre-deployment frontend build'"
echo "   databricks bundle deploy"
echo "========================================="
