# gaim-executive-app — Repository Audit & Improvement Plan

**Audit type:** Read-only, evidence-based. No code was modified.
**Date:** 2026-07-21
**Reviewer scope:** Full repo, with depth on the backend API core, forecasting subsystem, and frontend dashboard (the ~20% of code doing ~80% of the work). Lighter review: `powerbi-reference/`, per-notebook internals (audited separately in prior forecasting review), and the Databricks bundle deploy mechanics.

> Citations are `file:line`. Claims are labelled **FACT** (verified in source) or **JUDGMENT** (reviewer assessment). Where a claim could not be verified it says so.

---

## 1. Executive Summary

**Overall health grade: C (functional and thoughtfully resilient in places, undermined by a critical auth flaw, data-integrity gaps, and poor repo hygiene).**

The app is a genuinely capable FastAPI + React + Databricks executive dashboard with real engineering maturity in spots — a tested graceful-degradation contract, CVE-annotated dependency pins, deliberate fast-fail DB timeouts, and disciplined DEMO/LIVE labeling in the forecasting panel. But three classes of problem pull the grade down. First, a **security-critical auth fallback** (`auth.py:114-131`) that accepts unverifiable forwarded tokens as valid identities whenever `DATABRICKS_HOST` is set, plus a raw-SQL-interpolation injection sink on an unauthenticated endpoint (`data_fetcher.py:561`). Second, **data-integrity hazards**: multiple live, executive-facing surfaces render fabricated or `Math.random()`-generated numbers with no "illustrative" label (`main.py:359,617,670`; `KPIDetailModal.jsx:451`; `BusinessPerformancePanel.jsx:44`), and writes can fail silently while reporting success (`user_preferences_service.py:83`). Third, **repo hygiene**: a 30-file Windows virtualenv and a 129-file Power BI cache are committed despite both being gitignored, and there is near-zero automated test coverage of the API surface.

**Top 3 risks:** (1) authentication is bypassable if the app is ever reachable without the Databricks proxy in front; (2) leadership may make decisions on fabricated numbers they believe are real; (3) silent write-loss and a non-recovering circuit breaker mean the dashboard can degrade to fake data invisibly and stay there until restart.

**Top 3 opportunities:** (1) a handful of small, surgical fixes remove the Critical/High items with low risk; (2) deleting committed build/venv/binary artifacts and consolidating 27 root docs dramatically improves onboarding and clone size; (3) the existing resilience-test pattern is a ready template to extend coverage across the 12 untested route modules.

---

## 2. Repo Map

**Purpose.** Internal executive analytics dashboard for GoTo ("Atlas"/"GAIM"): live KPI monitoring, pipeline analysis, and a multi-model ARR forecasting experience with AI-assisted insights, deployed as a Databricks App over Databricks/Unity Catalog data.

**Stack.**
- **Backend:** Python, FastAPI `0.109.0`, Uvicorn `0.27.0`; Databricks SQL connector + SDK; Prophet/statsmodels/LightGBM for in-process forecasting (largely legacy — live forecasts are precomputed by notebooks).
- **Frontend:** React 18 + Vite 7, Recharts, framer-motion, axios; Context + hooks for state (no Redux/React Query).
- **Data/Jobs:** Databricks notebooks (`notebooks/`) train models and write Delta tables the API reads.
- **Deploy:** Databricks Apps via `app.yaml` (runs `main:app`), `build.sh`, `databricks.yml`.

**Architecture sketch.**
```
Databricks notebooks ──write──> Delta tables (arr_forecast_v2, KPI tables, insights caches)
                                        │
                          backend/services (data_fetcher, gaim_data_service,
                                        │    databricks_connection, ai_service, …)
                          backend/routes/*  +  backend/main.py (also hosts ~15 endpoints)
                                        │  FastAPI, per-request Databricks user-token auth
                                   REST /api/*  +  /ws/refresh
                                        │
                          frontend (App.jsx → 4 tab views → Recharts components)
```

**Key directories.**
- `backend/routes/` — 15 route modules, ~73 endpoints (forecast_v2 is the live forecast surface).
- `backend/services/` — 18 service modules (data access, caching, AI, notifications, prefs).
- `backend/queries/` — externalized SQL templates loaded by `query_loader.py`.
- `frontend/src/components/` — 41 live components (+ ~20 orphaned); `ForecastingPanel.jsx` dominates at 2,160 lines.
- `notebooks/` — forecast/precompute jobs (Prophet, ensemble, ITSG/UCC writers).
- `powerbi-reference/` — 129 tracked Power BI semantic-model files (should not be tracked).
- `schemas/` — Unity Catalog DDL for the "atlas" gold layer.
- 27 root-level `.md` docs + 6 root `.docx` review artifacts.

**Surprises.** (1) `.gitignore` explicitly ignores `.venv/` and `powerbi-reference/`, yet both are tracked (`auth.py`-adjacent hygiene failure). (2) The deployed entrypoint `main.py` (734 lines) hosts ~15 endpoints directly *and* mounts 16 routers from `bootstrap.py` — a split composition root. (3) CI import-smokes `bootstrap`, not the `main` entrypoint it actually deploys. (4) Two charting engines shipped (recharts + unused chart.js). (5) Three Python versions in play (3.9 on-disk venv, 3.12 tracked .venv, 3.12 in CI).

---

## 3. Audit Report

### Security

**[CRITICAL] Auth fallback accepts forged/unverifiable tokens as valid identities — FACT.**
`auth.py:114-131`: when `_verify_forwarded_token` raises 401, if `DATABRICKS_HOST` is set (always true on Databricks Apps) and `AUTH_TRUST_FORWARDED_TOKEN` is enabled — which it is **by default** (`auth.py:42-47`) — the 401 is swallowed and a pseudonymous id is derived from the token hash (`_fallback_user_id_from_token`, `auth.py:50-52,125`). **Consequence:** `require_authenticated_user` cannot reject a caller in the deployed environment; any string in `x-forwarded-access-token` becomes a stable identity. If the app is ever reachable without the Databricks auth proxy (direct pod access, ingress misconfig), auth is fully bypassable and per-user data (prefs/actions/notifications keyed by this id) is forgeable. The header is trusted blindly.

**[HIGH] SQL injection on an unauthenticated endpoint — FACT.**
`/api/arr/forecast` (`main.py:457-462`) has no auth dependency and passes `geo`/`product_group` query params to `data_fetcher.fetch_arr_forecast_results`, which interpolates them raw into SQL (`data_fetcher.py:561-563`, also `run_date` at `:546`) — no whitelist, no binding. **Consequence:** classic injection sink (`geo=Total' OR '1'='1`). Notably the codebase *has* the right pattern elsewhere (whitelist filter builders); this path bypassed it.

**[MEDIUM] Latent injection sinks in dead code — FACT.** `data_fetcher.py:675` (`segment_by` into GROUP BY) and `gaim_data_service.py:389-413` (`start_date`/`end_date` into `DATE('{...}')`) interpolate raw; both currently have no live caller, so they are latent rather than active.

**[MEDIUM] Hardcoded infrastructure identifiers — FACT.** Workspace host `goto-data-dock.cloud.databricks.com` (`settings.py:15`, `databricks_connection.py:27`, `genie_service.py:26`), warehouse id `c24ee33594e13e93` (`settings.py:16`, `app.yaml:33,37`), Genie space id (`genie_service.py:27`). Not credentials, but internal infra baked into source.

**[LOW] `settings.py:104` `extra="ignore"`** silently drops mistyped env vars (e.g. a fat-fingered token var → silent demo mode). CORS is correctly scoped to an explicit origin list (`bootstrap.py:63-69`) — **healthy**. No hardcoded secrets anywhere (`git grep` for credential patterns returns zero real hits) — **healthy**.

### Correctness

**[HIGH] Live endpoints serve canned/fabricated data as real, HTTP 200, no flag — FACT.**
- `/api/kpis` catches all exceptions and returns `_demo_kpis_payload()` fabricated numbers with no demo marker (`main.py:359-361`, payload `:36-94`).
- `/api/insights/kpi/{id}` computes from a hardcoded fabricated KPI dict (`main.py:617-643`, comment "For now, using demo data").
- `/api/insights/alerts` from a hardcoded KPI list (`main.py:670-683`).
**Consequence:** the primary dashboard endpoint cannot be distinguished from fallback by the client. (`/api/arr/history` does it correctly with `demo_mode:true` at `main.py:569` — the standard exists, it's just not applied.)

**[HIGH] Fabricated `Math.random()` trends in live UI, unlabeled — FACT.** `KPIDetailModal.jsx:451-453` (`syntheticTrend`/`syntheticWeekly`, `:113-135`) renders random-noise weekly history when a KPI lacks `trend_data`; `BusinessPerformancePanel.jsx:44-46` manufactures sparklines the same way. Both are rendered in the default views with no "illustrative" badge — contradicting the disciplined labeling in `ForecastingPanel.jsx:707,1566`.

**[HIGH] Silent write-failure reported as success — FACT.** `user_preferences_service.py:83-97` and `notification_service.py:70-84` wrap INSERT/UPDATE/DELETE in try/except that logs and returns `[]`; callers unconditionally return success (`user_preferences_service.py:143,166,199,222,227`; `notification_service.py:128`). **Consequence:** failed prefs/action writes surface to the user as saved.

**[HIGH] Non-recovering, process-global circuit breaker — FACT.** `gaim_data_service.py:120` sets `_db_reachable=True`, flipped to `False` on first timeout (`:150,153`), gated in `fetch_kpis` (`:142`), and **never reset**. **Consequence:** one transient Databricks timeout pins the shared singleton into demo mode for all users until process restart — combined with the unflagged fallback above, the dashboard can silently serve fake data indefinitely.

**[MEDIUM] Fire-and-forget alert task** (`main.py:354`) not retained (GC risk), exceptions lost, no dedup — can re-hit Slack/email on every cache miss. **[MEDIUM]** `data_fetcher.py:113-114` `fillna(value=None)` is a pandas no-op — NaNs may survive into JSON. **[LOW]** Unlocked global caches (`data_cache.py`, `auth.py:19` unbounded `_VERIFY_CACHE`, `genie_service.py:134`).

### Architecture & Design

**[MEDIUM] `main.py` is 734 lines and overlaps route modules — FACT.** It registers ~15 endpoints directly on `app` while `bootstrap.py:118-133` mounts 16 routers; the `/api/insights` namespace is split between `main.py:420` and `routes/insights.py:22` — a layering violation and split composition root.

**[MEDIUM] Per-request instantiation shadowing singletons — FACT.** `main.py:612,666` `new EnhancedInsightsEngineV2()/EnhancedInsightsEngine()` inside handlers, shadowing the `bootstrap.py:113` singleton (three insight-engine objects total).

**[MEDIUM] Substantial dead code — FACT.** Backend: `data_fetcher.fetch_prophet_forecast_data/fetch_win_probability_data/fetch_forecast_accuracy_2024` + mock generators (`:650-791`), `gaim_data_service.fetch_trend_data/_query_trend` — no callers. Frontend: ~20 orphaned components (~2,500 lines) never imported (`AIInsights`, `InsightsPanel`, `FilterPanel` 453L, `GenieAssistant` 328L, `ProductWheel`, etc.), plus a checked-in `ForecastingPanel.v1.bak.jsx` (669L) and the retired `charts/ForecastChart.jsx` (397L). **JUDGMENT:** the orphaned `FilterPanel.jsx`/`TimePeriodFilter.jsx` mean there may be **no interactive filter control** wired into the dashboard (filters set only via URL) — confirm whether this is a regression.

### Testing

**[HIGH] Near-zero API coverage — FACT.** 3 test files, ~15 functions, for 15 route modules / ~73 endpoints and 18 services. Only `forecast_v2` (~7 of 18 endpoints via `test_forecast_v2_resilience.py`) and `ai_service` (`test_ai_sql_guard.py`) have coverage; `test_auth_guard.py` covers the auth paths. 12+ route modules have zero tests. **The existing tests are high quality** — they assert behavior with Databricks properly mocked (see Strengths). **[HIGH] Zero frontend tests — FACT** (no runner, no `test` script).

### Performance

**[HIGH] No connection pooling — FACT.** `databricks_connection.py:87-127` opens a fresh `sql.connect` per query; `gaim_data_service._query_kpis` runs 3 sequential connections per `/api/kpis` request (`:219-221`). **Consequence:** 3 auth handshakes per KPI request. The connector's non-thread-safety is real, but a per-thread pool or combining the 3 CTEs (as `data_fetcher._fetch_kpis_databricks:234-315` already does) would cut this ~3×.

**[MEDIUM] Blocking DB I/O on the event loop — FACT.** `notification_service.broadcast_alert` (`async`, `:265`) calls synchronous `store_notification`/DDL (`:273,55-65`) without `asyncio.to_thread`, inside the fire-and-forget task — stalls concurrent requests. (SES/SMTP are correctly async — pattern understood but not applied to DB.)

**[MEDIUM] Frontend:** two charting engines bundled; `ForecastingPanel` (2,160L) statically imported (no `React.lazy`), loads even when its tab is unopened; 60s countdown re-renders the whole App tree (`App.jsx:80-83`). **[LOW]** `FilterContext.jsx:29` value object not memoized.

### Dependencies

**[MEDIUM] 5 of 12 frontend runtime deps unused — FACT:** `chart.js`, `react-chartjs-2` (only used by an orphan), `date-fns`, `react-router-dom` (routing done via `history.replaceState`), `howler` (imported, never called). **[MEDIUM] Duplicate requirements files — FACT:** root `requirements.txt` and `backend/requirements.txt` byte-identical; deploy uses root, backend copy will drift. **[MEDIUM] Stale pins — FACT:** fastapi/uvicorn ~2 years old; three Python versions across on-disk/tracked/CI. Lockfile hygiene is good (committed `package-lock.json`). **Strength:** dependency pins carry CVE rationale comments.

### DevEx & Operations

**[HIGH] CI smoke-tests the wrong app object — FACT.** `ci.yml:35` imports `bootstrap`; deploy runs `main:app` (`app.yaml`, `start.py:22`, `build.sh:34`). A broken import in the 734-line `main.py` passes CI. **[MEDIUM] No Python lint/format config — FACT:** no ruff/flake8/black/pre-commit; `ci.yml:16` job is labelled "lint" but has no backend lint step (frontend eslint exists). **Strengths:** CI exists (pinned runtimes, caching, `npm ci`, import-smoke); SIGTERM graceful shutdown, structured request-logging middleware, GZip (`bootstrap.py:53-106`).

### Documentation

**[MEDIUM] Doc sprawl and staleness — FACT.** 27 root `.md` files with heavy overlap (`START_HERE`/`GETTING_STARTED`/`QUICKSTART`/`SETUP`/`EXACT_STEPS`/…). `GETTING_STARTED.md:32-40` hardcodes another author's Windows OneDrive path and the old project name "atlas-executive-insights." `DOCUMENT_INDEX.md` describes an aspirational "22 table families / 11 roles" architecture marked "COMPLETE & DEPLOYMENT-READY" while `databricks.yml` ships one weekly job. `databricks.yml` references a stale `goto-eureka-mdl-1` host vs the live `goto-data-dock`.

### Repo Hygiene (Critical)

**[CRITICAL] Windows virtualenv committed — FACT.** 30 files under `backend/.venv/` including `python.exe`, `pythonw.exe`, and ~15 `.exe` shims — Windows binaries in a Linux-deployed app, despite `.gitignore:8` listing `.venv/`. Supply-chain/AV liability + bloat.

**[CRITICAL] Power BI cache committed — FACT.** 129 files under `powerbi-reference/` (the 3 largest tracked files: 2.6MB/1.6MB/1.3MB) despite `.gitignore:13` ignoring it with the note "large binary caches, not needed for deployment."

**[MEDIUM] 6 `.docx` review binaries at repo root — FACT.** **[LOW, defensible] `frontend/dist/` committed — FACT** but intentional (`.gitignore:38-39`, required by Databricks Apps per `build.sh`).

### Strengths (preserve these)

1. **Tested graceful-degradation contract** — `test_forecast_v2_resilience.py` asserts every v2 endpoint returns 200+`source:demo` (never 500) when Databricks denies access, Databricks mocked.
2. **Whitelist SQL construction** for KPI/filter paths (`gaim_data_service.py:45-89`, `data_fetcher.py:174-221`) — the correct pattern (the injection sinks are the exceptions that skipped it).
3. **Parameterized queries** for all prefs/actions/notifications (`?` bindings, backtick-quoted FQNs).
4. **Deliberate fast-fail timeouts** with documented rationale (`databricks_connection.py:33-37,104-122`), 5s health ping.
5. **No hardcoded secrets**; CVE-annotated pins; three `.env.example` templates; real `.env` gitignored.
6. **Robust frontend error boundary** (`AppErrorBoundary.jsx`, DEV-gated traces), disciplined DEMO/LIVE labeling in ForecastingPanel, resilient `Promise.allSettled` insight fetching.

---

## 4. Improvement Strategy

**Theme 1 — Auth and input trust boundaries are porous.** The forwarded-token fallback and the raw-SQL endpoint both trust unverified external input. *Target state:* verification failures fail closed; all user input reaching SQL is bound or whitelisted. *Principle:* never trust a header or a query param.

**Theme 2 — "Fail soft" is applied without honesty.** Demo/random fallbacks, swallowed write errors, and a stuck circuit breaker all degrade silently and report success. *Target state:* every fallback is labelled to the client, write failures propagate, the breaker self-heals. *Principle:* degrade visibly, never fabricate silently — especially for an exec audience.

**Theme 3 — No enforced quality gates.** Near-zero API tests, no backend lint, CI testing the wrong entrypoint. *Target state:* CI imports `main`, runs ruff + a route smoke suite, fails on lint. *Principle:* the pipeline should catch what humans miss.

**Theme 4 — Repo hygiene has decayed.** Committed venv/PBI/dist/docx, 27 overlapping docs, dead code, duplicate requirements. *Target state:* only source and required artifacts tracked; one canonical setup doc; dead code deleted. *Principle:* the working tree should reflect what runs.

**Explicit non-goals (not worth fixing now).** Don't introduce Redux/React Query (Context fits this scale). Don't build a full connection-pool abstraction if combining the 3 KPI CTEs gets the win. Don't chase 80% coverage everywhere — cover auth, SQL-building, and the forecast/KPI money paths only. Don't refactor `main.py` into perfect layering before the Critical fixes land. Leave `frontend/dist/` committed (platform requires it). Don't rewrite the notebooks from the app repo.

**Definition of done (measurable).** Zero Critical findings; auth fails closed by default (fallback opt-in only, off in prod); no unauthenticated raw-SQL params; every demo/synthetic surface labelled; CI imports `main`, runs ruff + route smoke, fails on lint; committed `.venv`/`powerbi-reference`/`.docx` removed from tracking; clone size materially reduced; one canonical GETTING_STARTED.

---

## 5. Task Plan

### Quick wins (high impact, S effort — do immediately)
- **QW1** — `git rm -r --cached backend/.venv powerbi-reference *.docx` and confirm `.gitignore` covers them. Removes both Criticals' bloat + supply-chain risk in one commit. (does not rewrite history — see OQ)
- **QW2** — Flip `AUTH_TRUST_FORWARDED_TOKEN` default to **off** (`auth.py:42-47`) so verification fails closed unless explicitly opted in.
- **QW3** — Point CI import-smoke at `main` not `bootstrap` (`ci.yml:35`).
- **QW4** — Delete `ForecastingPanel.v1.bak.jsx` and remove 5 unused frontend deps (`chart.js`, `react-chartjs-2`, `date-fns`, `react-router-dom`, `howler`).
- **QW5** — Delete `backend/requirements.txt` (byte-identical dup of root).

### Milestone 0 — Safety net (before refactoring)
| ID | Task | Files | Acceptance | Effort | Risk | Deps |
|----|------|-------|-----------|--------|------|------|
| T0.1 | Add route smoke tests (import `main`, assert every router mounts + 200/401 on a sample per module, Databricks mocked) | `backend/tests/` | New tests pass in CI; ≥1 assertion per route module | M | Low | — |
| T0.2 | Add ruff config + CI backend lint step | `pyproject.toml`, `ci.yml` | CI fails on lint errors; baseline clean | S | Low | — |
| T0.3 | Fix CI to import `main` | `ci.yml:35` | CI catches a deliberately broken `main.py` import | S | Low | QW3 |

### Milestone 1 — Critical fixes (security & correctness)
| ID | Task | Files | Acceptance | Effort | Risk | Deps |
|----|------|-------|-----------|--------|------|------|
| T1.1 | Harden auth fallback: fail closed by default; if fallback kept, gate behind explicit prod-off flag + log loudly | `auth.py:42-47,114-131` | Invalid token → 401 in prod; unit test proves rejection | M | **Med** (could break real Databricks token quirk — verify against a live forwarded token) | T0.1 |
| T1.2 | Fix SQL injection: whitelist/bind `geo`/`product_group`/`run_date`; add auth to `/api/arr/forecast` | `main.py:457`, `data_fetcher.py:546,561` | Injection payload rejected; test asserts | M | Low | — |
| T1.3 | Label all demo/synthetic data to the client (add `demo_mode`/`source` flags; UI badge) | `main.py:359,617,670`; `KPIDetailModal.jsx:451`; `BusinessPerformancePanel.jsx:44` | No live surface shows fabricated numbers without a badge | M | Low | — |
| T1.4 | Propagate write failures (return errors from prefs/notification `_exec`) | `user_preferences_service.py:83`, `notification_service.py:70` | Failed write → non-200/`ok:false`; test asserts | M | Med (callers assume success) | T0.1 |
| T1.5 | Self-healing circuit breaker (retry-after TTL, not permanent) | `gaim_data_service.py:120,142` | Breaker resets after cooldown; test asserts recovery | S | Low | — |

### Milestone 2 — High-leverage improvements
| ID | Task | Files | Acceptance | Effort | Risk | Deps |
|----|------|-------|-----------|--------|------|------|
| T2.1 | Combine the 3 KPI CTE queries into one (or per-thread pool) | `gaim_data_service.py:219`, `databricks_connection.py` | 1 connection per `/api/kpis`; latency measured lower | M | Med | T0.1 |
| T2.2 | Offload blocking DB writes with `asyncio.to_thread`; retain + error-log the alert task | `notification_service.py:265,273`; `main.py:354` | No blocking DB call on event loop; task exceptions logged | S | Low | — |
| T2.3 | Delete backend + frontend dead code (~3,000 lines) | `data_fetcher.py:650-791`, ~20 orphan components | Files removed; build + smoke pass; **confirm filter-UI question first** | M | Med | OQ answered |
| T2.4 | Move `main.py`'s ~15 handlers into route modules; thin `main.py` to assembly | `main.py`, `backend/routes/` | `main.py` < ~150 lines; no endpoint behavior change; tests pass | L | Med | T0.1 |
| T2.5 | `React.lazy` the 4 tab views; extract shared `<DarkTooltip>`/`formatValue` | `App.jsx`, `frontend/src/components/charts/` | Initial bundle smaller; tooltips dedup'd | M | Low | QW4 |

### Milestone 3 — Quality & polish
| ID | Task | Files | Acceptance | Effort | Risk |
|----|------|-------|-----------|--------|------|
| T3.1 | Consolidate 27 root docs → one canonical GETTING_STARTED; fix stale host/path/name | root `*.md`, `databricks.yml`, `GETTING_STARTED.md` | One setup path; no stale refs | M | Low |
| T3.2 | Move infra IDs to env/config with docs | `settings.py`, `genie_service.py`, `app.yaml` | No infra IDs hardcoded in `.py` | S | Low |
| T3.3 | Bump fastapi/uvicorn; reconcile to one Python version | `requirements.txt`, `ci.yml` | Deps current; single Python version | M | Med |
| T3.4 | Add a minimal frontend test runner (vitest) + tests for the data-fallback paths | `frontend/` | `npm test` runs; fallback logic covered | M | Low |

### Implementation sketch — top 3 tasks

**T1.1 (auth fail-closed).** Approach: default `_trusted_forwarded_fallback_enabled()` to `False`; keep the fallback available only when an operator sets `AUTH_TRUST_FORWARDED_TOKEN=true`, and even then never in `ENVIRONMENT=production`. Steps: (1) invert the default at `auth.py:42-47`; (2) add `and settings.environment != "production"` to the guard at `:120-124`; (3) add unit tests to `test_auth_guard.py` — invalid token → 401 in prod, fallback only when flag+non-prod. **Gotcha:** the comment at `:117-119` claims Databricks sometimes forwards app tokens valid for access but rejected by `/current-user/me`. Verify against a real forwarded token in staging *before* shipping, or you may lock out legitimate users. This is the one Critical fix with real behavioral risk — do it behind the safety net (T0.1) and test in staging.

**T1.2 (SQL injection).** Approach: reuse the existing whitelist pattern (`gaim_data_service._VALID_GEO`/`_PRODUCT_MAP`). Steps: (1) validate `geo`/`product_group` against known sets, drop unknowns; (2) validate `run_date` as ISO date or bind it; (3) add `Depends(require_authenticated_user)` to `/api/arr/forecast` (`main.py:457`); (4) test with `geo=Total' OR '1'='1`. **Gotcha:** confirm no dashboard caller relies on passing arbitrary geo strings; the whitelist must include every value the UI actually sends.

**T1.3 (label fabricated data).** Approach: make fabrication impossible to mistake for real. Steps: (1) backend — add `"source":"demo"` / `"demo_mode":true` to the three `main.py` payloads, mirroring `/api/arr/history`; (2) frontend — in `KPIDetailModal`/`BusinessPerformancePanel`, either render an empty/"insufficient history" state or stamp an "illustrative" badge like ForecastingPanel's; (3) prefer removing `Math.random()` entirely in favor of an explicit empty state. **Gotcha:** some execs may prefer *a* line over a blank chart — a labelled "illustrative trend" is an acceptable compromise, silent random noise is not. Align with the product owner on which.

---

## 6. Open Questions (need a human)

1. **Filter UI:** Are `FilterPanel.jsx`/`TimePeriodFilter.jsx` orphaned by intent or is this a regression? If intentional, is URL-only filtering the desired UX? (Blocks T2.3.)
2. **Auth fallback:** Is the forwarded-token fallback (`auth.py:117`) load-bearing for a real Databricks token quirk, or leftover dev convenience? Determines whether T1.1 can hard-remove it or must keep an opt-in. **Needs a staging test with a live forwarded token.**
3. **Git history rewrite:** Removing the committed `.venv`/`powerbi-reference` from *tracking* (QW1) is safe and low-risk. Purging them from *history* (to shrink clone size) rewrites history and needs coordination — is that wanted, or is untracking going forward sufficient?
4. **Demo data policy:** For exec KPIs with no real trend data, is a labelled "illustrative" line acceptable, or should the UI show an empty state? (Shapes T1.3.)
5. **Deprecation:** Can the ~20 orphaned frontend components and the legacy in-process forecasting stack (`services/forecasting*.py`) be deleted, or are they staged for reuse?
6. **`main.py` vs routes:** Is the split composition root deliberate, or should T2.4 consolidate everything into route modules?

---

*Areas that received lighter review:* `powerbi-reference/` (treated as removable, not read), individual notebook internals (covered in a separate forecasting-model review), and the Databricks bundle/`build.sh` deploy mechanics (read for config facts, not exhaustively traced).
