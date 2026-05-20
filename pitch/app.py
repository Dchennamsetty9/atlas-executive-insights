"""
Atlas Executive Insights — Interactive Pitch Presentation
Deploy as a SEPARATE Databricks App (pitch/app.yaml).
Zero dependency on the main atlas app — completely standalone.

Endpoints:
  GET  /            → The interactive presentation (14 slides)
  POST /api/feedback → Submit feedback (saved to Delta table or local JSON)
  GET  /api/feedback → View all submissions  (add ?key=<FEEDBACK_KEY> in prod)
  GET  /api/health  → Health check
"""
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="Atlas Pitch")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Feedback storage ────────────────────────────────────────────────────────

FEEDBACK_TABLE = os.getenv("FEEDBACK_TABLE", "main.default.atlas_pitch_feedback")
FEEDBACK_FILE  = os.getenv("FEEDBACK_FILE",  "pitch_feedback.json")


def _get_conn():
    from databricks import sql  # noqa: PLC0415

    host = (
        os.getenv("DATABRICKS_HOST", "goto-data-dock.cloud.databricks.com")
        .removeprefix("https://").removeprefix("http://").rstrip("/")
    )
    http_path = os.getenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/c24ee33594e13e93")
    token     = os.getenv("DATABRICKS_TOKEN") or os.getenv("DATABRICKS_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("No Databricks token available")
    return sql.connect(server_hostname=host, http_path=http_path, access_token=token,
                       _socket_timeout=10, _retry_stop_after_attempts_duration=15)


def _save_to_delta(data: dict) -> str:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {FEEDBACK_TABLE} (
                    submitted_at   STRING,
                    name           STRING,
                    role           STRING,
                    overall_rating INT,
                    most_valuable  STRING,
                    main_concern   STRING,
                    would_use      STRING,
                    comments       STRING,
                    reactions      STRING
                )
            """)
            cur.execute(f"""
                INSERT INTO {FEEDBACK_TABLE}
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                data.get("submitted_at", ""),
                data.get("name", ""),
                data.get("role", ""),
                int(data.get("overall_rating") or 0),
                data.get("most_valuable", ""),
                data.get("main_concern", ""),
                data.get("would_use", ""),
                data.get("comments", ""),
                json.dumps(data.get("reactions", {})),
            ])
    return f"databricks:{FEEDBACK_TABLE}"


def _save_local(data: dict) -> str:
    entries = []
    if os.path.exists(FEEDBACK_FILE):
        try:
            with open(FEEDBACK_FILE) as f:
                entries = json.load(f)
        except Exception:
            pass
    entries.append(data)
    with open(FEEDBACK_FILE, "w") as f:
        json.dump(entries, f, indent=2)
    return f"local:{FEEDBACK_FILE}"


def save_feedback(data: dict) -> str:
    data["submitted_at"] = datetime.now(timezone.utc).isoformat()
    try:
        return _save_to_delta(data)
    except Exception as e:
        logger.warning("Delta save failed (%s), using local JSON", e)
        return _save_local(data)


def load_feedback() -> list:
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {FEEDBACK_TABLE} ORDER BY submitted_at DESC")
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        pass
    if os.path.exists(FEEDBACK_FILE):
        try:
            with open(FEEDBACK_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


# ── API routes ───────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "atlas-pitch"}


@app.post("/api/feedback")
async def submit_feedback(request: Request):
    try:
        data  = await request.json()
        where = save_feedback(data)
        return JSONResponse({"success": True, "saved_to": where})
    except Exception as exc:
        logger.exception("Feedback submit error")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/api/feedback")
def get_feedback():
    try:
        entries = load_feedback()
        return JSONResponse({"count": len(entries), "entries": entries})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Presentation HTML ────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Atlas Executive Insights — Team Pitch</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap"/>
<style>
:root{--bg:#080c14;--surface:#0f1623;--surface2:#161e2e;--border:rgba(255,255,255,0.07);--blue:#4f9cf9;--purple:#a78bfa;--green:#34d399;--amber:#fbbf24;--red:#f87171;--text:#e2e8f0;--muted:#64748b;--accent-grd:linear-gradient(135deg,#4f9cf9,#a78bfa)}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:'Inter',sans-serif;background:var(--bg);color:var(--text)}
#deck{width:100vw;height:100vh;position:relative}
.slide{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:56px 80px 80px;opacity:0;pointer-events:none;transition:opacity .3s ease;visibility:hidden}
.slide.active{opacity:1;pointer-events:all;visibility:visible}
.slide-inner{width:100%;max-width:1100px;animation:fadeUp .4s ease both}
@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;padding:4px 12px;border-radius:20px;margin-bottom:16px;background:rgba(79,156,249,.15);color:var(--blue);border:1px solid rgba(79,156,249,.3)}
h1{font-size:clamp(2rem,5vw,3.6rem);font-weight:900;line-height:1.1;margin-bottom:18px}
h2{font-size:clamp(1.5rem,3.2vw,2.4rem);font-weight:800;line-height:1.2;margin-bottom:14px}
h3{font-size:1rem;font-weight:700;margin-bottom:6px}
p{font-size:1rem;line-height:1.7;color:#94a3b8}
.grad{background:var(--accent-grd);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:20px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:22px;transition:border-color .25s}
.card:hover{border-color:rgba(79,156,249,.4)}
.card .icon{font-size:1.6rem;margin-bottom:10px}
.card h3{font-size:.95rem;font-weight:700;margin-bottom:5px}
.card p{font-size:.85rem;line-height:1.6;color:var(--muted)}
.chip{font-size:.76rem;font-weight:600;padding:3px 10px;border-radius:20px;background:rgba(79,156,249,.1);color:var(--blue);border:1px solid rgba(79,156,249,.2)}
.chip.green{background:rgba(52,211,153,.1);color:var(--green);border-color:rgba(52,211,153,.2)}
.chip.purple{background:rgba(167,139,250,.1);color:var(--purple);border-color:rgba(167,139,250,.2)}
.chip.amber{background:rgba(251,191,36,.1);color:var(--amber);border-color:rgba(251,191,36,.2)}
.chip.red{background:rgba(248,113,113,.1);color:var(--red);border-color:rgba(248,113,113,.2)}
.chip-list{display:flex;flex-wrap:wrap;gap:7px}
/* kpi cards */
.kpi-row{display:flex;gap:12px;margin-top:20px;flex-wrap:wrap}
.kpi-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 20px;flex:1;min-width:140px}
.kpi-card .label{font-size:.72rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.kpi-card .value{font-size:1.5rem;font-weight:900;line-height:1}
.kpi-card .vs{font-size:.8rem;margin-top:4px;font-weight:600}
.kpi-card .vs.up{color:var(--green)}.kpi-card .vs.down{color:var(--red)}.kpi-card .vs.warn{color:var(--amber)}
/* atlas says box */
.atlas-box{background:linear-gradient(135deg,rgba(79,156,249,.08),rgba(167,139,250,.08));border:1px solid rgba(79,156,249,.3);border-radius:16px;padding:24px 28px;margin-top:20px}
.atlas-box .head{font-size:.8rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--blue);margin-bottom:14px;display:flex;align-items:center;gap:8px}
.atlas-box .insight{font-size:.95rem;line-height:1.6;color:var(--text);margin-bottom:10px}
.atlas-box .action{background:rgba(52,211,153,.1);border:1px solid rgba(52,211,153,.25);border-radius:10px;padding:10px 16px;font-size:.88rem;color:var(--green);font-weight:600;margin-top:12px}
/* forecast */
.forecast-bar{height:10px;background:var(--surface2);border-radius:10px;margin-top:6px;overflow:hidden}
.forecast-bar .fill{height:100%;border-radius:10px;background:var(--accent-grd);transition:width 1s ease}
.forecast-bar .fill.warn{background:linear-gradient(90deg,var(--amber),var(--red))}
.prob-circle{width:88px;height:88px;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;font-weight:900;font-size:1.3rem;border:3px solid}
.prob-hi{color:var(--green);border-color:var(--green)}
.prob-md{color:var(--amber);border-color:var(--amber)}
.prob-lo{color:var(--red);border-color:var(--red)}
/* scenario cards */
.scenario{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:start;margin-bottom:14px}
.scenario-num{width:36px;height:36px;border-radius:50%;background:var(--accent-grd);color:#fff;font-weight:800;font-size:.9rem;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.scenario h3{font-size:.95rem;font-weight:700;margin-bottom:4px;color:var(--text)}
.scenario p{font-size:.85rem;color:var(--muted);margin-bottom:8px;line-height:1.5}
.scenario .result{font-size:.83rem;background:rgba(52,211,153,.08);border:1px solid rgba(52,211,153,.2);border-radius:8px;padding:8px 12px;color:var(--green);font-weight:600}
/* phase roadmap */
.phase{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px 24px;position:relative;overflow:hidden}
.phase::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%;border-radius:2px 0 0 2px}
.phase.p1::before{background:var(--green)}.phase.p2::before{background:var(--blue)}.phase.p3::before{background:var(--purple)}.phase.p4::before{background:var(--amber)}
.phase .ph-label{font-size:.72rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px}
.phase.p1 .ph-label{color:var(--green)}.phase.p2 .ph-label{color:var(--blue)}.phase.p3 .ph-label{color:var(--purple)}.phase.p4 .ph-label{color:var(--amber)}
.phase h3{font-size:.95rem;font-weight:700;margin-bottom:8px}
.phase ul{list-style:none;display:flex;flex-direction:column;gap:5px}
.phase ul li{font-size:.82rem;color:var(--muted);display:flex;align-items:flex-start;gap:6px}
.phase ul li::before{content:'·';color:var(--muted);margin-top:1px;flex-shrink:0}
/* comparison */
.cmp-table{width:100%;border-collapse:collapse;font-size:.88rem;margin-top:18px}
.cmp-table th{padding:10px 14px;text-align:left;font-size:.76rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);font-weight:700}
.cmp-table td{padding:11px 14px;border-bottom:1px solid var(--border);vertical-align:middle;line-height:1.5}
.cmp-table tr:last-child td{border-bottom:none}
.cmp-table .col-pbi{color:#64748b}.cmp-table .col-atlas{color:var(--blue)}
.badge-no{display:inline-block;font-size:.74rem;font-weight:600;padding:2px 9px;border-radius:20px;background:rgba(100,116,139,.12);color:var(--muted)}
.badge-yes{display:inline-block;font-size:.74rem;font-weight:600;padding:2px 9px;border-radius:20px;background:rgba(52,211,153,.12);color:var(--green)}
.badge-wip{display:inline-block;font-size:.74rem;font-weight:600;padding:2px 9px;border-radius:20px;background:rgba(251,191,36,.12);color:var(--amber)}
/* pain list */
.pain-list{list-style:none;display:flex;flex-direction:column;gap:12px;margin-top:18px}
.pain-list li{display:flex;align-items:flex-start;gap:12px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 18px}
.pain-list li .num{min-width:26px;height:26px;border-radius:50%;background:rgba(248,113,113,.15);color:var(--red);display:flex;align-items:center;justify-content:center;font-size:.78rem;font-weight:700;border:1px solid rgba(248,113,113,.3)}
.pain-list li .txt{font-size:.9rem;line-height:1.5;color:var(--text)}
/* arch */
.arch{display:flex;align-items:center;gap:0;margin-top:26px;flex-wrap:wrap}
.arch-node{background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:16px 18px;text-align:center;flex:1;min-width:110px}
.arch-node .icon{font-size:1.4rem;margin-bottom:6px}.arch-node h3{font-size:.8rem;font-weight:700;margin-bottom:3px}.arch-node p{font-size:.72rem;color:var(--muted)}
.arch-arrow{font-size:1.2rem;color:var(--muted);padding:0 4px;flex-shrink:0}
/* concerns */
.concern{display:grid;grid-template-columns:1fr 1.5fr;gap:14px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:12px}
.concern .lbl{font-size:.75rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;margin-bottom:5px}
.concern .risk .lbl{color:var(--red)}.concern .fix .lbl{color:var(--green)}
.concern p{font-size:.85rem;line-height:1.5;color:var(--muted)}
/* role table */
.role-table{width:100%;border-collapse:collapse;font-size:.86rem;margin-top:18px}
.role-table th{padding:10px 12px;text-align:left;font-size:.74rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);font-weight:700}
.role-table td{padding:11px 12px;border-bottom:1px solid var(--border);line-height:1.5}
.role-table tr:last-child td{border-bottom:none}
/* ask list */
.ask-list{list-style:none;display:flex;flex-direction:column;gap:10px;margin-top:18px}
.ask-list li{display:flex;align-items:flex-start;gap:14px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 20px}
.ask-num{min-width:28px;height:28px;border-radius:50%;background:var(--accent-grd);display:flex;align-items:center;justify-content:center;font-size:.78rem;font-weight:800;color:#fff;flex-shrink:0}
/* vision quote */
.vision-quote{background:var(--surface);border-left:4px solid var(--blue);border-radius:0 14px 14px 0;padding:24px 28px;margin-top:24px}
.vision-quote blockquote{font-size:clamp(1.05rem,2.3vw,1.5rem);font-weight:700;line-height:1.5;color:var(--text)}
.vision-quote blockquote em{font-style:normal;color:var(--blue)}
/* nav */
#nav{position:fixed;bottom:0;left:0;right:0;height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 40px;background:rgba(8,12,20,.9);backdrop-filter:blur(12px);border-top:1px solid var(--border);z-index:100}
.dots{display:flex;gap:5px;align-items:center}
.dot-btn{width:7px;height:7px;border-radius:50%;background:var(--border);border:none;cursor:pointer;transition:all .25s;padding:0}
.dot-btn.active{width:22px;border-radius:3px;background:var(--blue)}
.nav-btn{display:flex;align-items:center;gap:6px;background:var(--surface);border:1px solid var(--border);color:var(--text);padding:7px 16px;border-radius:7px;cursor:pointer;font-size:.82rem;font-weight:600;transition:border-color .2s;font-family:'Inter',sans-serif}
.nav-btn:hover{border-color:var(--blue);background:rgba(79,156,249,.08)}
.nav-btn:disabled{opacity:.3;cursor:default}
.slide-counter{font-size:.78rem;color:var(--muted);font-weight:600;min-width:46px;text-align:center}
/* reaction */
#reaction-bar{position:fixed;top:16px;right:18px;display:flex;gap:7px;align-items:center;z-index:100}
.rxn-btn{background:var(--surface);border:1px solid var(--border);border-radius:28px;padding:5px 12px;cursor:pointer;font-size:.88rem;transition:all .2s;color:var(--text);font-family:'Inter',sans-serif}
.rxn-btn:hover{border-color:var(--blue);transform:scale(1.08)}
.rxn-btn.active{border-color:var(--green);background:rgba(52,211,153,.1)}
/* modal */
#modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);backdrop-filter:blur(6px);z-index:200;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .3s}
#modal-overlay.open{opacity:1;pointer-events:all}
#modal{background:var(--surface);border:1px solid var(--border);border-radius:18px;width:min(500px,90vw);max-height:90vh;overflow-y:auto;padding:32px;transform:translateY(18px);transition:transform .3s}
#modal-overlay.open #modal{transform:translateY(0)}
#modal h2{font-size:1.3rem;font-weight:800;margin-bottom:6px}
#modal p.sub{font-size:.88rem;color:var(--muted);margin-bottom:22px}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:.78rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:5px}
.form-group input,.form-group select,.form-group textarea{width:100%;background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:9px;padding:9px 13px;font-size:.88rem;font-family:'Inter',sans-serif;outline:none;transition:border-color .2s;resize:vertical}
.form-group input:focus,.form-group select:focus,.form-group textarea:focus{border-color:var(--blue)}
.form-group select option{background:var(--surface2)}
.star-row{display:flex;gap:7px}
.star{font-size:1.5rem;cursor:pointer;filter:grayscale(1);transition:filter .15s,transform .15s}
.star.on{filter:grayscale(0);transform:scale(1.12)}
.btn-row{display:flex;gap:10px;margin-top:22px}
.btn-submit{flex:1;padding:11px;background:var(--accent-grd);color:#fff;font-weight:700;border:none;border-radius:9px;cursor:pointer;font-family:'Inter',sans-serif;font-size:.92rem;transition:opacity .2s}
.btn-submit:hover{opacity:.88}
.btn-cancel{padding:11px 18px;background:var(--surface2);border:1px solid var(--border);color:var(--muted);border-radius:9px;cursor:pointer;font-family:'Inter',sans-serif;font-size:.92rem}
.success-msg{text-align:center;padding:22px 0}
.success-msg .check{font-size:2.2rem;margin-bottom:10px}
#progress{position:fixed;top:0;left:0;height:3px;background:var(--accent-grd);z-index:300;transition:width .35s ease}
</style>
</head>
<body>
<div id="progress"></div>
<div id="deck">

<!-- 1: Title -->
<div class="slide" data-idx="0">
<div class="slide-inner" style="text-align:center">
<div class="tag">Internal Pitch · May 2026</div>
<h1>Atlas<br/><span class="grad">Executive Insights</span></h1>
<p style="font-size:1.1rem;max-width:520px;margin:0 auto 28px">Not another dashboard. A decision intelligence layer on top of GoTo's live data — giving executives and business planning leaders the "so what" behind every number.</p>
<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
<span class="chip">Built for SFO Business Planning</span>
<span class="chip green">Executive Intelligence</span>
<span class="chip purple">AI-Powered Insights</span>
<span class="chip amber">Your Data · Your Access</span>
</div>
</div>
</div>

<!-- 2: The Problem -->
<div class="slide" data-idx="1">
<div class="slide-inner">
<div class="tag">The Problem</div>
<h2>What sales leaders deal with today</h2>
<ul class="pain-list">
<li><span class="num">1</span><span class="txt"><strong>Numbers without context.</strong> Win rate is 28%. Is that good or bad? Vs last quarter? Vs which segment? KPI Trends shows the number — nothing else.</span></li>
<li><span class="num">2</span><span class="txt"><strong>No "so what."</strong> Pipeline coverage is 2.1x. Should you be worried? What does 2.1x mean for end-of-quarter attainment? Nobody tells you.</span></li>
<li><span class="num">3</span><span class="txt"><strong>Insights arrive too late.</strong> MQL count dropped 18% WoW. You find out in Friday's report. By then the pipeline gap is already baked in for next quarter.</span></li>
<li><span class="num">4</span><span class="txt"><strong>Disconnected dashboards.</strong> KPI Trends shows pacing. Performance Hub shows history. Neither tells you how today's win rate connects to your Q3 quota number.</span></li>
<li><span class="num">5</span><span class="txt"><strong>Every question requires an analyst.</strong> "What's driving the ADS drop in Enterprise NA?" — that's a 2-day Databricks query. It should be a 10-second chat message.</span></li>
</ul>
</div>
</div>

<!-- 3: The Vision -->
<div class="slide" data-idx="2">
<div class="slide-inner">
<div class="tag">The Vision</div>
<h2>From reporting to decision intelligence</h2>
<div class="vision-quote">
<blockquote>“Our dashboards tell you the score.<br/><em>Atlas Executive Insights tells you the play to run next.”</em></blockquote>
<p style="margin-top:10px;font-size:.85rem;color:var(--muted);font-weight:600">— The core idea behind every design decision</p>
</div>
<div class="grid3" style="margin-top:20px">
<div class="card"><div class="icon">🔭</div><h3>Predictive</h3><p>Where will your quarter land based on today's pipeline, win rate, and coverage trend?</p></div>
<div class="card"><div class="icon">⚡</div><h3>Proactive</h3><p>Surfaces risks before your weekly pipeline review — not after. Alerts when a metric crosses a threshold that historically signals attainment risk.</p></div>
<div class="card"><div class="icon">🎯</div><h3>Actionable</h3><p>Every insight ends with a specific recommendation tied to the data — not generic advice.</p></div>
</div>
</div>
</div>

<!-- 4: Real Example -->
<div class="slide" data-idx="3">
<div class="slide-inner">
<div class="tag">Real Example</div>
<h2>Week 8 of Q2 — here’s what Atlas Executive Insights does</h2>
<div class="kpi-row">
<div class="kpi-card"><div class="label">Won Pipeline</div><div class="value" style="color:var(--green)">$18.4M</div><div class="vs up">↑ on pace (67% of target)</div></div>
<div class="kpi-card"><div class="label">Win Rate</div><div class="value" style="color:var(--red)">28.1%</div><div class="vs down">↓ 3.2 pts vs last Q</div></div>
<div class="kpi-card"><div class="label">Coverage</div><div class="value" style="color:var(--amber)">2.1×</div><div class="vs warn">⚠ below 2.5× threshold</div></div>
<div class="kpi-card"><div class="label">Pipeline Att.</div><div class="value">67%</div><div class="vs up">60% of quarter elapsed</div></div>
<div class="kpi-card"><div class="label">MQL Count</div><div class="value" style="color:var(--red)">412</div><div class="vs down">↓ 18% WoW</div></div>
</div>
<div class="atlas-box">
<div class="head">🤖 Atlas Executive Insights</div>
<div class="insight">Pipeline attainment is on pace, but two risk signals need attention: <strong>Win Rate dropped 3.2 pts QoQ</strong> — disproportionately in <strong>Enterprise NA</strong> where it fell from 34% to 27%. Coverage at <strong>2.1× is below the 2.5× historical threshold</strong> that correlates with quota attainment. Combined with the MQL drop, late-quarter pipeline replenishment is at risk.</div>
<div class="action">▶ Recommended: Accelerate top 5 Enterprise NA deals in next 2 weeks. Review conversion drop from MQL → Opp — likely a lead quality or response time issue in that segment.</div>
</div>
</div>
</div>

<!-- 5: Power BI vs Atlas -->
<div class="slide" data-idx="4">
<div class="slide-inner">
<div class="tag">Comparison</div>
<h2>Current dashboards vs Atlas Executive Insights</h2>
<table class="cmp-table">
<thead><tr><th>Capability</th><th class="col-pbi">Current Power BI Dashboards</th><th class="col-atlas">Atlas Executive Insights</th></tr></thead>
<tbody>
<tr><td>Shows live metric values</td><td><span class="badge-yes">Yes</span></td><td><span class="badge-yes">Yes — same GoTo federated data</span></td></tr>
<tr><td>Explains <em>why</em> a metric moved</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">AI narrative per metric</span></td></tr>
<tr><td>Quarter-end attainment projection</td><td><span class="badge-no">No</span></td><td><span class="badge-wip">Planned — pacing model</span></td></tr>
<tr><td>Coverage → attainment probability</td><td><span class="badge-no">No</span></td><td><span class="badge-wip">Planned — statistical model</span></td></tr>
<tr><td>Proactive risk alerts</td><td><span class="badge-no">No</span></td><td><span class="badge-wip">Planned — threshold monitoring</span></td></tr>
<tr><td>Natural language chat about your data</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">Ask anything about the numbers</span></td></tr>
<tr><td>Recommended next actions</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">Built in to every insight</span></td></tr>
<tr><td>Per-user data access</td><td><span class="badge-yes">Role-based</span></td><td><span class="badge-yes">Same — your identity, your data</span></td></tr>
</tbody>
</table>
</div>
</div>

<!-- 6: Forecasting & Prediction -->
<div class="slide" data-idx="5">
<div class="slide-inner">
<div class="tag">Prediction &amp; Forecasting</div>
<h2>Three models — not AI guesses, math with AI narrative</h2>
<div style="display:flex;flex-direction:column;gap:14px;margin-top:18px">

<div class="card" style="padding:18px 22px">
<div style="display:flex;align-items:center;gap:16px">
<div class="prob-circle prob-hi" style="flex-shrink:0"><span>87%</span><span style="font-size:.6rem;font-weight:600">attain</span></div>
<div style="flex:1">
<h3>🔢 Pacing Model</h3>
<p style="font-size:.86rem;margin-bottom:8px">Won Pipeline = $18.4M at 60% of quarter elapsed. Linear extrapolation → <strong style="color:var(--green)">projected $30.7M</strong> vs $27.4M target = 112% attainment.</p>
<div class="forecast-bar"><div class="fill" style="width:87%"></div></div>
<div style="display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted);margin-top:4px"><span>0%</span><span>Target: 100%</span><span>Projected: 112%</span></div>
</div>
</div>
</div>

<div class="card" style="padding:18px 22px">
<div style="display:flex;align-items:center;gap:16px">
<div class="prob-circle prob-md" style="flex-shrink:0"><span>64%</span><span style="font-size:.6rem;font-weight:600">prob</span></div>
<div style="flex:1">
<h3>📊 Coverage Model</h3>
<p style="font-size:.86rem;margin-bottom:8px">Coverage 2.1× with 40% of quarter left. Historically, <strong style="color:var(--amber)">coverage below 2.5× at this stage</strong> yields quota attainment 64% of the time (vs 89% at 2.5×+).</p>
<div class="forecast-bar"><div class="fill warn" style="width:64%"></div></div>
<div style="display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted);margin-top:4px"><span>0%</span><span style="color:var(--amber)">Risk zone (below 2.5×)</span><span>Safe zone</span></div>
</div>
</div>
</div>

<div class="card" style="padding:18px 22px">
<div style="display:flex;align-items:center;gap:16px">
<div class="prob-circle prob-lo" style="flex-shrink:0"><span>↓</span><span style="font-size:.6rem;font-weight:600">trend</span></div>
<div style="flex:1">
<h3>📉 Win Rate Trend Model</h3>
<p style="font-size:.86rem;margin-bottom:8px">Win rate declining at <strong style="color:var(--red)">-0.4 pts/week</strong> for 4 weeks. If trend continues: <strong style="color:var(--red)">projected 26.5%</strong> at quarter end vs 30% target. Early intervention window is now.</p>
<div class="forecast-bar"><div class="fill warn" style="width:53%"></div></div>
<div style="display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted);margin-top:4px"><span>Current: 28.1%</span><span style="color:var(--red)">Projected: 26.5%</span><span>Target: 30%</span></div>
</div>
</div>
</div>

</div>
<p style="margin-top:12px;font-size:.82rem;color:var(--muted)">⚠ These are deterministic statistical models. The LLM adds the narrative — it never does the math.</p>
</div>
</div>

<!-- 7: AI in Action — Scenarios -->
<div class="slide" data-idx="6">
<div class="slide-inner">
<div class="tag">AI in Action</div>
<h2>Three questions Atlas Executive Insights would answer for your team</h2>
<div class="scenario">
<div class="scenario-num">1</div>
<div>
<h3>Peter asks: "Why is win rate down in Enterprise NA this quarter?"</h3>
<p><em>Today:</em> A multi-day data pull by the analytics team. Answer arrives days later.<br/><em>With Atlas Executive Insights:</em> Type the question. Answer in seconds, grounded in live data.</p>
<div class="result">Atlas Executive Insights: "Enterprise NA win rate dropped from 34% → 27% over 6 weeks. Pattern matches deals lost in the 45–90 day range (AOS $85K+). Close rate on deals with more than 2 stakeholders fell 8 pts — suggest reviewing multi-thread engagement strategy for large Enterprise deals."</div>
</div>
</div>
<div class="scenario">
<div class="scenario-num">2</div>
<div>
<h3>Derek is prepping the Monday business review: MQL count dropped 18% WoW — does it matter for next quarter?</h3>
<p><em>Today:</em> Email Marketing, wait for context, piece together manually.<br/><em>With Atlas Executive Insights:</em> The impact is already quantified when you open the app.</p>
<div class="result">Atlas Executive Insights: "MQL count fell 412 → 338 (18.6% WoW). Based on GoTo's historical conversion rates, a 10% MQL drop typically reduces next-quarter created pipeline by ~$2.1M. At this pace, Q3 created pipeline target is at risk unless inbound volume recovers by Week 10."</div>
</div>
</div>
<div class="scenario">
<div class="scenario-num">3</div>
<div>
<h3>David needs the Q2 attainment call for the monthly business review</h3>
<p><em>Today:</em> SFO builds a spreadsheet — 1 day turnaround, snapshot not live, revised multiple times.<br/><em>With Atlas Executive Insights:</em> Live pacing view with probability, trend, and narrative in one click.</p>
<div class="result">Atlas Executive Insights: "Pacing model shows 87% attainment likely based on current pipeline. Risk flags: win rate declining at -0.4 pts/week, coverage at 2.1× below the 2.5× threshold historically needed. If both stabilise at last period's levels, probability rises to 94%. Immediate focus: 3 at-risk Enterprise deals totalling $4.2M need executive engagement this week."</div>
</div>
</div>
</div>
</div>

<!-- 8: Architecture -->
<div class="slide" data-idx="7">
<div class="slide-inner">
<div class="tag">Architecture</div>
<h2>How it works — built on what you already have</h2>
<div class="arch">
<div class="arch-node"><div class="icon">🗄️</div><h3>Metis</h3><p>Federated Sales<br/>data layer<br/>Single source of truth</p></div>
<div class="arch-arrow">→</div>
<div class="arch-node"><div class="icon">⚡</div><h3>API Layer</h3><p>Python backend<br/>KPI endpoints<br/>2-min cache</p></div>
<div class="arch-arrow">→</div>
<div class="arch-node"><div class="icon">🔢</div><h3>Rule Engine</h3><p>Pacing calc<br/>Coverage model<br/>Win rate trend</p></div>
<div class="arch-arrow">→</div>
<div class="arch-node"><div class="icon">🤖</div><h3>AI Layer</h3><p>Narrative<br/>Chat answers<br/>Recommendations</p></div>
<div class="arch-arrow">→</div>
<div class="arch-node" style="border-color:rgba(79,156,249,.4)"><div class="icon">👤</div><h3>You</h3><p>GoTo SSO<br/>Your data only<br/>Role-based access</p></div>
</div>
<div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
<span class="chip">Uses GoTo’s existing Metis data infrastructure</span>
<span class="chip green">Each user sees only their approved data</span>
<span class="chip purple">AI narrates math, never replaces it</span>
</div>
<div class="grid2" style="margin-top:18px">
<div class="card"><h3>Source Data (Metis Federated Layer)</h3><div class="chip-list" style="margin-top:8px"><span class="chip">Federated Pipeline Data</span><span class="chip">Created Pipeline</span><span class="chip">Targets</span><span class="chip">MQL &amp; Lead Data</span><span class="chip">Won Opps</span></div></div>
<div class="card"><h3>Key KPIs tracked</h3><div class="chip-list" style="margin-top:8px"><span class="chip green">Won Pipeline</span><span class="chip green">Win Rate</span><span class="chip green">Coverage</span><span class="chip green">Pipeline Att.</span><span class="chip green">MQL Count</span><span class="chip green">ADS · AOS · Close Rate</span><span class="chip green">Created Pipeline</span><span class="chip green">+ more</span></div></div>
</div>
</div>
</div>

<!-- 9: Phase Roadmap -->
<div class="slide" data-idx="8">
<div class="slide-inner">
<div class="tag">Roadmap</div>
<h2>Four phases from intelligence to decision engine</h2>
<div class="grid2" style="margin-top:18px">
<div class="phase p1">
<div class="ph-label">🟢 Phase 1 — Intelligence Layer</div>
<h3>Know what's happening</h3>
<ul>
<li>Live KPIs from GoTo’s Metis federated data layer</li>
<li>AI narrative per KPI explaining the "so what"</li>
<li>Conversational chat grounded in live numbers</li>
<li>Filter by Geo / Channel / Product</li>
<li>Role-based data access — each user sees their approved data</li>
<li>Deployed on GoTo’s internal app platform</li>
</ul>
</div>
<div class="phase p2">
<div class="ph-label">🔵 Phase 2 — Prediction Layer</div>
<h3>Know where you're going</h3>
<ul>
<li>Quarter-end projection (linear pacing model)</li>
<li>Coverage × win rate → attainment probability score</li>
<li>Historical QoQ comparison (same point in quarter)</li>
<li>Personalised views for each stakeholder</li>
<li>Win rate trend model with early warning</li>
<li>Forecast confidence interval display</li>
</ul>
</div>
<div class="phase p3">
<div class="ph-label">🟣 Phase 3 — Proactive Alerts</div>
<h3>Get told before it's a problem</h3>
<ul>
<li>Threshold alerts: "Coverage crossed below 2.5×"</li>
<li>MQL drop → pipeline impact forecast (3-week lag model)</li>
<li>Win rate decline detection (weekly trend check)</li>
<li>Rep-level rollup (pending governance sign-off)</li>
<li>Slack / email alert integration for critical signals</li>
<li>Anomaly detection across all tracked KPIs</li>
</ul>
</div>
<div class="phase p4">
<div class="ph-label">🟡 Phase 4 — Decision Engine</div>
<h3>Know exactly what to do</h3>
<ul>
<li>Scenario modeling: "What if win rate improves 2pts?"</li>
<li>Deal prioritisation: rank open opps by close probability</li>
<li>Cross-signal: MQL quality × pipeline conversion rate</li>
<li>Marketing ↔ Sales causal attribution (MQL → Won $)</li>
<li>Mobile-first executive view</li>
<li>Feedback loop: rate AI recommendations to improve them</li>
</ul>
</div>
</div>
</div>
</div>

<!-- 10: Concerns -->
<div class="slide" data-idx="9">
<div class="slide-inner">
<div class="tag">Concerns &amp; Mitigations</div>
<h2>Hard questions — honest answers</h2>
<div class="concern">
<div class="risk"><div class="lbl">⚠️ Data Governance</div><p>Revenue data and rep-level metrics are sensitive. Who controls who sees what?</p></div>
<div class="fix"><div class="lbl">✅ Mitigation</div><p>Every user authenticates with their own GoTo identity. Data access permissions apply automatically based on their existing role — no shared service account, no new permission grants needed. We define the access tiers once; the platform enforces them.</p></div>
</div>
<div class="concern">
<div class="risk"><div class="lbl">⚠️ AI Accuracy</div><p>What if the AI says the wrong thing? An exec acts on a bad recommendation?</p></div>
<div class="fix"><div class="lbl">✅ Mitigation</div><p>AI <em>never</em> calculates — it narrates. Every number shown comes from SQL. The rule engine runs first and overrides the AI if they conflict. Source numbers are always visible alongside the narrative.</p></div>
</div>
<div class="concern">
<div class="risk"><div class="lbl">⚠️ Model Drift</div><p>The pacing and coverage models assume historical patterns hold. What if Q2 is structurally different?</p></div>
<div class="fix"><div class="lbl">✅ Mitigation</div><p>Models show confidence intervals, not point estimates. The AI narrative explicitly flags when current patterns deviate significantly from the historical baseline used in the model.</p></div>
</div>
<div class="concern">
<div class="risk"><div class="lbl">⚠️ Cost &amp; Maintenance</div><p>Another tool to maintain. LLM API costs. Who owns this?</p></div>
<div class="fix"><div class="lbl">✅ Mitigation</div><p>Same Databricks warehouse already running. AI calls are per-click, not always-on. Rule-based fallback means most requests never hit the LLM. One engineer can maintain this — the codebase is 800 lines.</p></div>
</div>
</div>
</div>

<!-- 11: Role-Based Views -->
<div class="slide" data-idx="10">
<div class="slide-inner">
<div class="tag">Who This Is For</div>
<h2>Built specifically for the SFO Business Planning team</h2>
<p style="margin-bottom:16px;font-size:.9rem;color:var(--muted)">These are the people who would use Atlas Executive Insights day-to-day — and the question it replaces manual work for each of them.</p>
<table class="role-table">
<thead><tr><th>Person</th><th>Focus Area</th><th>Key Metrics</th><th>Question Atlas Executive Insights Answers</th></tr></thead>
<tbody>
<tr><td><strong>Peter Mahoney</strong></td><td>SFO Leadership</td><td>Win Rate, Coverage, Pipeline Att.</td><td>"What’s driving attainment risk right now, and where?"</td></tr>
<tr><td><strong>Derek Keller</strong></td><td>SFO Business Planning</td><td>Pipeline, Won $, ADS by segment</td><td>"Where are we pacing vs plan, and which cut shows the gap?"</td></tr>
<tr><td><strong>David Williams</strong></td><td>SFO Business Planning</td><td>All tracked metrics + trends</td><td>"Help me build the narrative for the business review."</td></tr>
<tr><td><strong>Damon Covey</strong></td><td>SFO Business Planning</td><td>Coverage, Created Pipeline, MQL</td><td>"Is next quarter’s pipeline at risk based on today’s signals?"</td></tr>
<tr><td><strong>Joseph George</strong></td><td>SFO Business Planning</td><td>Win Rate, Close Rate, Opps</td><td>"What’s changing in deal conversion this period?"</td></tr>
<tr><td><strong>Emily Puopolo</strong></td><td>SFO Business Planning</td><td>MQL, Created Pipeline, Attainment</td><td>"Is the MQL drop a this-quarter or next-quarter problem?"</td></tr>
<tr><td><strong>Jorge</strong></td><td>SFO Business Planning</td><td>Attainment %, AOS, Pipeline Att.</td><td>"How are we trending vs the same point last year?"</td></tr>
</tbody>
</table>
<p style="margin-top:14px;font-size:.82rem;color:var(--muted)">
<strong style="color:var(--blue)">Design principle:</strong> Each person logs in with their GoTo identity. The app surfaces the data they’re already approved to see — no new permission grants, no shared credentials, no re-work of existing access controls.
</p>
</div>
</div>

<!-- 12: What I Need -->
<div class="slide" data-idx="11">
<div class="slide-inner">
<div class="tag">Five Asks</div>
<h2>What I need from this group to move forward</h2>
<ul class="ask-list">
<li><span class="ask-num">1</span><span style="font-size:.92rem;line-height:1.5"><strong>Governance sign-off:</strong> Which Metis tables and fields are approved for AI queries? Can the model surface won $ amounts directly, or only derived metrics like attainment %? This shapes what gets built next.</span></li>
<li><span class="ask-num">2</span><span style="font-size:.92rem;line-height:1.5"><strong>Working session with the team:</strong> 30 minutes each to walk through Phase 1 and tell me what’s missing or wrong. Specifically: Peter, Derek, David, and one other from this group.</span></li>
<li><span class="ask-num">3</span><span style="font-size:.92rem;line-height:1.5"><strong>Data access tiers:</strong> Define who should see what — do all SFO Business Planning members see all geos and channels, or is there a sub-scoping needed? Without this defined, everyone sees everything.</span></li>
<li><span class="ask-num">4</span><span style="font-size:.92rem;line-height:1.5"><strong>Historical baselines:</strong> For the coverage and win rate models to work accurately, I need validated historical attainment data — what coverage and win rate levels actually correlated with quota hits in past periods.</span></li>
<li><span class="ask-num">5</span><span style="font-size:.92rem;line-height:1.5"><strong>Priority call on what to build next:</strong> Should the focus be forecasting + personalised views (Phase 2) or proactive alerting (Phase 3)? Your answer determines where engineering time goes.</span></li>
</ul>
</div>
</div>

<!-- 13: Live Demo -->
<div class="slide" data-idx="12">
<div class="slide-inner" style="text-align:center">
<div class="tag">Live Demo</div>
<h2>See what Phase 1 will look like</h2>
<div style="background:var(--surface);border:2px dashed rgba(79,156,249,.4);border-radius:16px;padding:32px;margin-top:18px">
<p style="font-size:.95rem;color:var(--muted);margin-bottom:18px">Atlas Executive Insights is currently in development. When deployed, you log in with your GoTo SSO and it reads your data in real time from the same Metis federated layer that powers our current dashboards — no new data pipelines needed.</p>
<div style="display:flex;gap:20px;justify-content:center;flex-wrap:wrap;margin-top:18px">
<div style="text-align:left;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:18px 22px;max-width:280px">
<h3 style="color:var(--blue);margin-bottom:12px;font-size:.9rem">Try this in the demo</h3>
<ol style="list-style:none;display:flex;flex-direction:column;gap:9px">
<li style="font-size:.85rem;display:flex;gap:8px;align-items:flex-start"><span style="background:rgba(79,156,249,.2);color:var(--blue);border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:700;flex-shrink:0">1</span>Log in with your GoTo SSO</li>
<li style="font-size:.85rem;display:flex;gap:8px;align-items:flex-start"><span style="background:rgba(79,156,249,.2);color:var(--blue);border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:700;flex-shrink:0">2</span>See your live KPIs load from real GoTo data</li>
<li style="font-size:.85rem;display:flex;gap:8px;align-items:flex-start"><span style="background:rgba(79,156,249,.2);color:var(--blue);border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:700;flex-shrink:0">3</span>Click Win Rate → read AI narrative</li>
<li style="font-size:.85rem;display:flex;gap:8px;align-items:flex-start"><span style="background:rgba(79,156,249,.2);color:var(--blue);border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:700;flex-shrink:0">4</span>Filter to Enterprise → watch it update</li>
<li style="font-size:.85rem;display:flex;gap:8px;align-items:flex-start"><span style="background:rgba(79,156,249,.2);color:var(--blue);border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:700;flex-shrink:0">5</span>Chat: "why is win rate down?"</li>
</ol>
</div>
<div style="text-align:left;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:18px 22px;max-width:280px">
<h3 style="color:var(--purple);margin-bottom:12px;font-size:.9rem">What Phase 2 will add</h3>
<ul style="list-style:none;display:flex;flex-direction:column;gap:8px">
<li style="font-size:.85rem;color:var(--muted);display:flex;gap:8px"><span style="color:var(--purple)">→</span>Quarter-end attainment projection</li>
<li style="font-size:.85rem;color:var(--muted);display:flex;gap:8px"><span style="color:var(--purple)">→</span>Coverage probability score (live)</li>
<li style="font-size:.85rem;color:var(--muted);display:flex;gap:8px"><span style="color:var(--purple)">→</span>Win rate trend with ETA to target</li>
<li style="font-size:.85rem;color:var(--muted);display:flex;gap:8px"><span style="color:var(--purple)">→</span>Role-based profile (you only see your data)</li>
<li style="font-size:.85rem;color:var(--muted);display:flex;gap:8px"><span style="color:var(--purple)">→</span>QoQ same-point-in-quarter comparison</li>
</ul>
</div>
</div>
</div>
</div>
</div>

<!-- 14: Thank You -->
<div class="slide" data-idx="13">
<div class="slide-inner" style="text-align:center">
<div class="tag">Thank You</div>
<h1>Atlas <span class="grad">Executive Insights</span></h1>
<p style="font-size:1rem;max-width:500px;margin:14px auto 0;color:var(--muted)">Phase 1 is live. The path to a real prediction and decision intelligence layer is defined. Your feedback and governance decisions are the next unlock.</p>
<div style="display:flex;align-items:center;justify-content:center;gap:16px;margin:24px 0;flex-wrap:wrap">
<span style="display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:28px;padding:8px 16px;font-size:.82rem;font-weight:600">� Built on GoTo's Live Data</span>
<span style="display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:28px;padding:8px 16px;font-size:.82rem;font-weight:600">🤖 AI-Powered Insights</span>
<span style="display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:28px;padding:8px 16px;font-size:.82rem;font-weight:600">🔒 Your Data · Your Access</span>
</div>
<button class="btn-submit" style="padding:13px 36px;font-size:.95rem;cursor:pointer;border-radius:11px;width:auto" onclick="openModal()">📝 Leave Your Feedback</button>
<p style="margin-top:18px;font-size:.82rem;color:var(--muted)">Find me in <strong style="color:var(--blue)">#gaim-atlas</strong> on Slack or reach out directly</p>
</div>
</div>

</div><!-- /deck -->

<div id="nav">
<button class="nav-btn" id="btn-prev" onclick="prevSlide()">◀ Prev</button>
<div style="display:flex;align-items:center;gap:12px">
<div class="dots" id="dots"></div>
<span class="slide-counter" id="counter">1 / 14</span>
</div>
<button class="nav-btn" id="btn-next" onclick="nextSlide()">Next ▶</button>
</div>

<div id="reaction-bar">
<button class="rxn-btn" onclick="react('👍')">👍</button>
<button class="rxn-btn" onclick="react('❓')">❓</button>
<button class="rxn-btn" onclick="react('💡')">💡</button>
<button class="rxn-btn" onclick="react('⚠️')">⚠️</button>
<button class="nav-btn" style="margin-left:6px" onclick="openModal()">📝 Feedback</button>
</div>

<div id="modal-overlay" onclick="closeModalOnOverlay(event)">
<div id="modal">
<div id="modal-form">
<h2>Share Your Feedback</h2>
<p class="sub">Your input directly shapes what gets built next. Takes 2 minutes.</p>
<div class="form-group"><label>Your Name (optional)</label><input type="text" id="f-name" placeholder="e.g. Peter Mahoney"/></div>
<div class="form-group"><label>Your Team / Role</label><select id="f-role"><option value="">Select your role</option><option>SFO Business Planning</option><option>SFO Leadership</option><option>Sales Analytics</option><option>Engineering / Analytics</option><option>Other</option></select></div>
<div class="form-group"><label>Overall impression (1–5)</label><div class="star-row" id="stars"><span class="star" onclick="setStar(1)">⭐</span><span class="star" onclick="setStar(2)">⭐</span><span class="star" onclick="setStar(3)">⭐</span><span class="star" onclick="setStar(4)">⭐</span><span class="star" onclick="setStar(5)">⭐</span></div></div>
<div class="form-group"><label>Most valuable to you</label><select id="f-valuable"><option value="">Select one</option><option>AI narrative explaining each metric</option><option>Quarter-end attainment projection</option><option>Coverage → probability score</option><option>Win rate trend detection</option><option>Personalised view per person</option><option>Conversational chat about your data</option><option>Proactive alerts before problems escalate</option></select></div>
<div class="form-group"><label>What should we build next?</label><select id="f-concern"><option value="">Select one</option><option>Phase 2: Forecasting + personalised views</option><option>Phase 3: Proactive alerts + threshold monitoring</option><option>Phase 4: Scenario modeling + deal prioritisation</option><option>Improve Phase 1 first — something is missing or wrong</option></select></div>
<div class="form-group"><label>Would you use this in your workflow?</label><select id="f-use"><option value="">Select one</option><option>Yes — replace my manual prep work</option><option>Yes — alongside current dashboards for the AI layer</option><option>Maybe — need to see forecasting first</option><option>No — not relevant to my role</option></select></div>
<div class="form-group"><label>Any other feedback or ideas</label><textarea id="f-comments" rows="3" placeholder="What would make this a must-have for your weekly business review prep?"></textarea></div>
<div class="btn-row"><button class="btn-cancel" onclick="closeModal()">Cancel</button><button class="btn-submit" onclick="submitFeedback()">Submit →</button></div>
</div>
<div id="modal-success" style="display:none">
<div class="success-msg"><div class="check">🎉</div><h3>Thank you!</h3><p>Saved. Your input shapes what Phase 2 looks like.</p><button class="btn-submit" style="margin-top:18px;width:100%" onclick="closeModal()">Close</button></div>
</div>
</div>
</div>

<script>
const TOTAL=14;let current=0,starVal=0;const reactions={};
const slides=document.querySelectorAll('.slide');
const dotsEl=document.getElementById('dots');
for(let i=0;i<TOTAL;i++){const b=document.createElement('button');b.className='dot-btn'+(i===0?' active':'');b.title=`Slide ${i+1}`;b.addEventListener('click',()=>goTo(i));dotsEl.appendChild(b)}
goTo(0);
function goTo(n){slides[current].classList.remove('active');current=Math.max(0,Math.min(TOTAL-1,n));slides[current].classList.add('active');document.querySelectorAll('.dot-btn').forEach((d,i)=>d.classList.toggle('active',i===current));document.getElementById('counter').textContent=`${current+1} / ${TOTAL}`;document.getElementById('progress').style.width=`${((current+1)/TOTAL)*100}%`;document.getElementById('btn-prev').disabled=current===0;document.getElementById('btn-next').disabled=current===TOTAL-1}
function nextSlide(){goTo(current+1)}function prevSlide(){goTo(current-1)}
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT')return;if(e.key==='ArrowRight'||e.key===' '){e.preventDefault();nextSlide()}if(e.key==='ArrowLeft'){e.preventDefault();prevSlide()}if(e.key==='Escape')closeModal()});
function react(emoji){if(!reactions[current])reactions[current]=[];if(!reactions[current].includes(emoji))reactions[current].push(emoji);document.querySelectorAll('.rxn-btn').forEach(b=>{if(b.textContent.trim()===emoji){b.classList.add('active');setTimeout(()=>b.classList.remove('active'),600)}})}
function setStar(n){starVal=n;document.querySelectorAll('.star').forEach((s,i)=>s.classList.toggle('on',i<n))}
function openModal(){document.getElementById('modal-overlay').classList.add('open');document.getElementById('modal-form').style.display='block';document.getElementById('modal-success').style.display='none'}
function closeModal(){document.getElementById('modal-overlay').classList.remove('open')}
function closeModalOnOverlay(e){if(e.target===document.getElementById('modal-overlay'))closeModal()}
async function submitFeedback(){const data={name:document.getElementById('f-name').value.trim(),role:document.getElementById('f-role').value,overall_rating:starVal,most_valuable:document.getElementById('f-valuable').value,main_concern:document.getElementById('f-concern').value,would_use:document.getElementById('f-use').value,comments:document.getElementById('f-comments').value.trim(),reactions};try{const res=await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await res.json();if(j.success){document.getElementById('modal-form').style.display='none';document.getElementById('modal-success').style.display='block'}else{alert('Could not save: '+(j.error||'unknown'))}}catch{alert('Network error')}}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
