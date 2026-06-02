# GAIM Executive App

GAIM Executive App is the Atlas Databricks application for executive KPI monitoring, pipeline analysis, forecasting, and AI-assisted insight delivery.

## Overview

The project combines:
- Live and cached KPI APIs over Databricks data
- Forecasting APIs for scenario-based ARR and pipeline outlooks
- React dashboard experiences for executive monitoring and drill-downs
- Notification, preference, action, and AI assistant routes for workflow support

The current forecasting direction is a precomputed, model-driven pipeline that can evolve from Prophet-only scenarios to a multi-model engine with accuracy tracking and AI narratives.

## Repository Layout

```text
gaim-executive-app/
|- app.yaml                     Databricks App entry config
|- backend/                     FastAPI backend, routes, services, config
|- frontend/                    React + Vite application
|- notebooks/                   Forecast and precompute jobs
|- powerbi-reference/           Power BI semantic model reference assets
|- schemas/                     Unity Catalog DDL, grants, and gold-layer setup
`- docs/                        Supporting implementation notes
```

## Current Architecture

- Backend bootstrap lives in `backend/bootstrap.py` and mounts route modules for forecast, insights, preferences, notifications, performance hub, deals, coverage, and AI workflows.
- API entrypoints and static app serving live in `backend/main.py`.
- Frontend is a Vite React app with dashboard components, hooks, contexts, and an API service layer.
- Databricks remains the system of record for GAIM tables and forecast source data.
- Power BI semantic model files under `powerbi-reference/` are the reference surface for ARR forecast lineage.

## Local Development

### Prerequisites
- Python 3.10+
- Node.js 18+
- Databricks access or configured local mock/demo fallback

### Backend

```powershell
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Current Focus Areas

- Stabilize forecast serving around precomputed-first, live-fallback behavior
- Align forecast table naming and contracts across app, notebooks, and Power BI reference
- Expand executive insights beyond placeholder responses
- Keep the UI stable while real KPI and forecast sources are progressively hardened

## Key Reference Docs

- `ARCHITECTURE.md`
- `ARR_FORECAST_ANALYSIS.md`
- `PROJECT_STATUS.md`
- `DASHBOARD_REFERENCE.md`

## License

Internal use only.
