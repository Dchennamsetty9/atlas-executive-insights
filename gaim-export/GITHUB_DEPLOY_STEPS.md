# Quick Deploy to GitHub - goto-shared

## After creating repository on GitHub, run these commands:

```powershell
# Navigate to project root
cd "C:\Users\dchennamsetty\OneDrive - GoTo Technologies USA LLC\Documents\atlas-executive-insights"

# Connect to GitHub
git remote add origin https://github.com/goto-shared/atlas-executive-insights.git

# Stage all files
git add .

# Commit
git commit -m "Initial commit - Databricks Apps deployment ready with auto MDL data fetch"

# Push to GitHub
git branch -M main
git push -u origin main
```

## ✅ Verify on GitHub

Go to: https://github.com/goto-shared/atlas-executive-insights

You should see all your files including:
- backend/ (Python API)
- frontend/dist/ (Built React app)
- app.yaml (Databricks config)
- All documentation files

## 🚀 Next: Deploy to Databricks Apps

1. Go to: https://goto-eureka-mdl-1.cloud.databricks.com/
2. Sidebar → **Workspace** → **Repos**
3. Click **Add Repo**
4. URL: `https://github.com/goto-shared/atlas-executive-insights`
5. Click **Create Repo**

Then:
6. Sidebar → **Apps**
7. Click **Create App**
8. Name: `atlas-executive-insights`
9. Source: Your repo
10. Click **Deploy**

**Done!** Your dashboard will auto-fetch from MDL tables! 🎉
