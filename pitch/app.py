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
:root {
  --bg:        #080c14;
  --surface:   #0f1623;
  --surface2:  #161e2e;
  --border:    rgba(255,255,255,0.07);
  --blue:      #4f9cf9;
  --purple:    #a78bfa;
  --green:     #34d399;
  --amber:     #fbbf24;
  --red:       #f87171;
  --text:      #e2e8f0;
  --muted:     #64748b;
  --accent-grd: linear-gradient(135deg,#4f9cf9,#a78bfa);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:'Inter',sans-serif;background:var(--bg);color:var(--text)}

/* ── deck ── */
#deck{width:100vw;height:100vh;position:relative}
.slide{
  position:absolute;inset:0;
  display:flex;align-items:center;justify-content:center;
  padding:60px 80px;
  opacity:0;pointer-events:none;
  transition:opacity .45s ease,transform .45s ease;
  transform:translateX(40px);
}
.slide.active{opacity:1;pointer-events:all;transform:translateX(0)}
.slide.exit-left{opacity:0;transform:translateX(-40px)}

/* ── slide content wrapper ── */
.slide-inner{
  width:100%;max-width:1100px;
  animation:fadeUp .5s ease both;
}
@keyframes fadeUp{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:translateY(0)}}

/* ── typography ── */
.tag{
  display:inline-block;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  padding:4px 12px;border-radius:20px;margin-bottom:18px;
  background:rgba(79,156,249,.15);color:var(--blue);border:1px solid rgba(79,156,249,.3);
}
h1{font-size:clamp(2.2rem,5vw,3.8rem);font-weight:900;line-height:1.1;margin-bottom:20px}
h2{font-size:clamp(1.6rem,3.5vw,2.6rem);font-weight:800;line-height:1.2;margin-bottom:16px}
h3{font-size:1.1rem;font-weight:700;margin-bottom:8px}
p{font-size:1.05rem;line-height:1.7;color:#94a3b8}
.grad{background:var(--accent-grd);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}

/* ── cards / grid ── */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:24px}
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:24px;transition:border-color .25s;
}
.card:hover{border-color:rgba(79,156,249,.4)}
.card .icon{font-size:1.8rem;margin-bottom:12px}
.card h3{font-size:1rem;font-weight:700;margin-bottom:6px}
.card p{font-size:.9rem;line-height:1.6;color:var(--muted)}

/* ── pain point list ── */
.pain-list{list-style:none;display:flex;flex-direction:column;gap:14px;margin-top:24px}
.pain-list li{
  display:flex;align-items:flex-start;gap:14px;
  background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 20px;
}
.pain-list li .num{
  min-width:28px;height:28px;border-radius:50%;
  background:rgba(248,113,113,.15);color:var(--red);
  display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:700;
  border:1px solid rgba(248,113,113,.3);
}
.pain-list li .txt{font-size:.95rem;line-height:1.5;color:var(--text)}

/* ── comparison table ── */
.cmp-table{width:100%;border-collapse:collapse;margin-top:24px;font-size:.9rem}
.cmp-table th{
  padding:12px 16px;text-align:left;font-weight:700;font-size:.8rem;letter-spacing:.06em;
  text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);
}
.cmp-table td{
  padding:13px 16px;border-bottom:1px solid var(--border);vertical-align:top;line-height:1.5;
}
.cmp-table tr:last-child td{border-bottom:none}
.cmp-table .col-pbi{color:#64748b}
.cmp-table .col-atlas{color:var(--blue)}
.badge-no{
  display:inline-block;font-size:.75rem;font-weight:600;
  padding:2px 9px;border-radius:20px;
  background:rgba(100,116,139,.12);color:var(--muted);
}
.badge-yes{
  display:inline-block;font-size:.75rem;font-weight:600;
  padding:2px 9px;border-radius:20px;
  background:rgba(52,211,153,.12);color:var(--green);
}

/* ── differentiators ── */
.diff-card{
  background:var(--surface);border:1px solid var(--border);border-radius:18px;
  padding:32px;position:relative;overflow:hidden;
}
.diff-card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:var(--accent-grd);
}
.diff-card .num-big{
  font-size:3rem;font-weight:900;opacity:.06;position:absolute;top:16px;right:20px;
}

/* ── arch diagram ── */
.arch{display:flex;align-items:center;justify-content:space-between;gap:0;margin-top:32px;flex-wrap:wrap}
.arch-node{
  background:var(--surface2);border:1px solid var(--border);border-radius:14px;
  padding:20px 22px;text-align:center;min-width:140px;flex:1;
}
.arch-node .icon{font-size:1.6rem;margin-bottom:8px}
.arch-node h3{font-size:.85rem;font-weight:700;margin-bottom:4px}
.arch-node p{font-size:.75rem;color:var(--muted)}
.arch-arrow{font-size:1.4rem;color:var(--muted);padding:0 6px;flex-shrink:0}

/* ── AI features ── */
.ai-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-top:24px}
.ai-item{
  background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:18px;display:flex;gap:12px;align-items:flex-start;
}
.ai-item .dot{
  width:8px;height:8px;border-radius:50%;background:var(--accent-grd);
  margin-top:6px;flex-shrink:0;
}

/* ── data table ── */
.data-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px}
.data-block{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:22px}
.data-block h3{font-size:.85rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);margin-bottom:14px}
.chip-list{display:flex;flex-wrap:wrap;gap:8px}
.chip{
  font-size:.78rem;font-weight:600;padding:4px 12px;border-radius:20px;
  background:rgba(79,156,249,.1);color:var(--blue);border:1px solid rgba(79,156,249,.2);
}
.chip.green{background:rgba(52,211,153,.1);color:var(--green);border-color:rgba(52,211,153,.2)}
.chip.purple{background:rgba(167,139,250,.1);color:var(--purple);border-color:rgba(167,139,250,.2)}
.chip.amber{background:rgba(251,191,36,.1);color:var(--amber);border-color:rgba(251,191,36,.2)}

/* ── concerns ── */
.concern-row{display:grid;grid-template-columns:1fr 1.6fr;gap:16px;margin-top:14px}
.concern-item{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px}
.concern-item .label{font-size:.8rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  margin-bottom:8px;}
.risk{color:var(--red)}
.fix{color:var(--green)}

/* ── role matrix ── */
.role-table{width:100%;border-collapse:collapse;margin-top:24px;font-size:.88rem}
.role-table th{padding:11px 14px;text-align:left;font-size:.78rem;letter-spacing:.07em;
  text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);font-weight:700}
.role-table td{padding:13px 14px;border-bottom:1px solid var(--border);line-height:1.5}
.role-table tr:last-child td{border-bottom:none}

/* ── roadmap ── */
.roadmap{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px}
.rm-col{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:24px}
.rm-col h3{font-size:.85rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  margin-bottom:16px}
.rm-col.built h3{color:var(--green)}
.rm-col.next h3{color:var(--purple)}
.rm-list{list-style:none;display:flex;flex-direction:column;gap:10px}
.rm-list li{display:flex;align-items:center;gap:10px;font-size:.9rem;line-height:1.5}
.rm-list li::before{content:'';width:6px;height:6px;border-radius:50%;flex-shrink:0}
.rm-col.built .rm-list li::before{background:var(--green)}
.rm-col.next  .rm-list li::before{background:var(--purple)}

/* ── asks ── */
.ask-list{list-style:none;display:flex;flex-direction:column;gap:12px;margin-top:24px}
.ask-list li{
  display:flex;align-items:flex-start;gap:16px;
  background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 22px;
}
.ask-num{
  min-width:30px;height:30px;border-radius:50%;
  background:var(--accent-grd);
  display:flex;align-items:center;justify-content:center;
  font-size:.8rem;font-weight:800;color:#fff;flex-shrink:0;
}
.ask-txt{font-size:.95rem;line-height:1.5}

/* ── demo ── */
.demo-box{
  background:var(--surface);border:2px dashed rgba(79,156,249,.4);
  border-radius:18px;padding:36px;text-align:center;margin-top:24px;
}
.demo-box a{
  display:inline-block;margin-top:18px;padding:14px 36px;
  background:var(--accent-grd);color:#fff;font-weight:700;
  border-radius:12px;text-decoration:none;font-size:1rem;
  transition:opacity .2s;
}
.demo-box a:hover{opacity:.85}
.steps{text-align:left;max-width:480px;margin:24px auto 0;list-style:none;display:flex;flex-direction:column;gap:10px}
.steps li{display:flex;align-items:center;gap:10px;font-size:.9rem;color:var(--text)}
.steps li span{
  width:24px;height:24px;border-radius:50%;background:rgba(79,156,249,.15);
  color:var(--blue);font-size:.75rem;font-weight:700;
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
}

/* ── thank you ── */
.thankyou-center{text-align:center;width:100%}
.built-by{display:flex;align-items:center;justify-content:center;gap:20px;margin:28px 0;flex-wrap:wrap}
.built-pill{
  display:flex;align-items:center;gap:8px;
  background:var(--surface);border:1px solid var(--border);border-radius:30px;
  padding:8px 18px;font-size:.85rem;font-weight:600;
}
.feedback-cta{
  display:inline-block;margin-top:8px;padding:14px 36px;
  background:var(--accent-grd);color:#fff;font-weight:700;
  border-radius:12px;cursor:pointer;font-size:1rem;border:none;
  transition:opacity .2s,transform .15s;
}
.feedback-cta:hover{opacity:.88;transform:translateY(-2px)}

/* ── nav bar ── */
#nav{
  position:fixed;bottom:0;left:0;right:0;
  height:60px;display:flex;align-items:center;justify-content:space-between;
  padding:0 40px;
  background:rgba(8,12,20,.85);backdrop-filter:blur(12px);
  border-top:1px solid var(--border);z-index:100;
}
.dots{display:flex;gap:6px;align-items:center}
.dot-btn{
  width:8px;height:8px;border-radius:50%;background:var(--border);
  border:none;cursor:pointer;transition:all .25s;padding:0;
}
.dot-btn.active{width:24px;border-radius:4px;background:var(--blue)}
.nav-btn{
  display:flex;align-items:center;gap:8px;
  background:var(--surface);border:1px solid var(--border);
  color:var(--text);padding:8px 18px;border-radius:8px;cursor:pointer;
  font-size:.85rem;font-weight:600;transition:border-color .2s,background .2s;
  font-family:'Inter',sans-serif;
}
.nav-btn:hover{border-color:var(--blue);background:rgba(79,156,249,.08)}
.nav-btn:disabled{opacity:.3;cursor:default}
.slide-counter{font-size:.8rem;color:var(--muted);font-weight:600;min-width:48px;text-align:center}

/* ── reaction bar ── */
#reaction-bar{
  position:fixed;top:18px;right:20px;
  display:flex;gap:8px;align-items:center;z-index:100;
}
.rxn-btn{
  background:var(--surface);border:1px solid var(--border);
  border-radius:30px;padding:6px 14px;cursor:pointer;
  font-size:.9rem;transition:all .2s;color:var(--text);
  font-family:'Inter',sans-serif;
}
.rxn-btn:hover{border-color:var(--blue);transform:scale(1.08)}
.rxn-btn.active{border-color:var(--green);background:rgba(52,211,153,.1)}

/* ── feedback modal ── */
#modal-overlay{
  position:fixed;inset:0;background:rgba(0,0,0,.7);
  backdrop-filter:blur(6px);z-index:200;
  display:flex;align-items:center;justify-content:center;
  opacity:0;pointer-events:none;transition:opacity .3s;
}
#modal-overlay.open{opacity:1;pointer-events:all}
#modal{
  background:var(--surface);border:1px solid var(--border);
  border-radius:20px;width:min(520px,90vw);max-height:90vh;
  overflow-y:auto;padding:36px;
  transform:translateY(20px);transition:transform .3s;
}
#modal-overlay.open #modal{transform:translateY(0)}
#modal h2{font-size:1.4rem;font-weight:800;margin-bottom:8px}
#modal p.sub{font-size:.9rem;color:var(--muted);margin-bottom:24px}
.form-group{margin-bottom:18px}
.form-group label{display:block;font-size:.82rem;font-weight:700;
  letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.form-group input,
.form-group select,
.form-group textarea{
  width:100%;background:var(--surface2);border:1px solid var(--border);
  color:var(--text);border-radius:10px;padding:10px 14px;font-size:.9rem;
  font-family:'Inter',sans-serif;outline:none;transition:border-color .2s;
  resize:vertical;
}
.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus{border-color:var(--blue)}
.form-group select option{background:var(--surface2)}
.star-row{display:flex;gap:8px}
.star{font-size:1.6rem;cursor:pointer;filter:grayscale(1);transition:filter .15s,transform .15s}
.star.on{filter:grayscale(0);transform:scale(1.15)}
.btn-row{display:flex;gap:12px;margin-top:24px}
.btn-submit{
  flex:1;padding:12px;background:var(--accent-grd);color:#fff;
  font-weight:700;border:none;border-radius:10px;cursor:pointer;
  font-family:'Inter',sans-serif;font-size:.95rem;transition:opacity .2s;
}
.btn-submit:hover{opacity:.88}
.btn-cancel{
  padding:12px 20px;background:var(--surface2);border:1px solid var(--border);
  color:var(--muted);border-radius:10px;cursor:pointer;
  font-family:'Inter',sans-serif;font-size:.95rem;
}
.success-msg{
  text-align:center;padding:24px 0;
}
.success-msg .check{font-size:2.5rem;margin-bottom:12px}
.success-msg h3{font-size:1.1rem;font-weight:700;margin-bottom:6px}
.success-msg p{font-size:.9rem;color:var(--muted)}

/* ── progress bar ── */
#progress{
  position:fixed;top:0;left:0;height:3px;
  background:var(--accent-grd);z-index:300;
  transition:width .4s ease;
}

/* ── vision quote ── */
.vision-quote{
  background:var(--surface);border-left:4px solid var(--blue);
  border-radius:0 14px 14px 0;padding:28px 32px;margin-top:28px;
}
.vision-quote blockquote{
  font-size:clamp(1.1rem,2.5vw,1.6rem);font-weight:700;line-height:1.5;color:var(--text);
}
.vision-quote blockquote em{font-style:normal;color:var(--blue)}
.vision-quote .attrib{margin-top:12px;font-size:.85rem;color:var(--muted);font-weight:600}
</style>
</head>
<body>

<div id="progress"></div>

<!-- ─────────────────── SLIDES ─────────────────── -->
<div id="deck">

  <!-- 1: Title -->
  <div class="slide" data-idx="0">
    <div class="slide-inner" style="text-align:center">
      <div class="tag">Internal Pitch · May 2026</div>
      <h1>Atlas<br/><span class="grad">Executive Insights</span></h1>
      <p style="font-size:1.15rem;max-width:520px;margin:0 auto 32px">
        AI-powered decision intelligence for sales leadership.<br/>
        Not another dashboard — a thinking partner.
      </p>
      <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
        <span class="chip">Live on Databricks</span>
        <span class="chip green">14 KPIs tracked</span>
        <span class="chip purple">Claude Sonnet 4.6</span>
        <span class="chip amber">Unity Catalog secured</span>
      </div>
    </div>
  </div>

  <!-- 2: The Problem -->
  <div class="slide" data-idx="1">
    <div class="slide-inner">
      <div class="tag">The Problem</div>
      <h2>What executives actually deal with today</h2>
      <ul class="pain-list">
        <li><span class="num">1</span><span class="txt"><strong>Data is scattered</strong> — 5 different dashboards, none talking to each other. No single view of what's happening.</span></li>
        <li><span class="num">2</span><span class="txt"><strong>Dashboards describe, they don't decide</strong> — You see the number. Nobody tells you what to do about it.</span></li>
        <li><span class="num">3</span><span class="txt"><strong>Insights arrive late</strong> — Weekly email reports. QBR decks built manually. By the time you see it, the quarter is over.</span></li>
        <li><span class="num">4</span><span class="txt"><strong>Context is missing</strong> — A win rate drop means nothing without knowing which segment, which rep pool, and what changed.</span></li>
        <li><span class="num">5</span><span class="txt"><strong>No one connects data to action</strong> — Even great analysts stop at "here's what happened." They rarely say "here's what to do."</span></li>
      </ul>
    </div>
  </div>

  <!-- 3: The Vision -->
  <div class="slide" data-idx="2">
    <div class="slide-inner">
      <div class="tag">The Vision</div>
      <h2>What Atlas is built to do</h2>
      <div class="vision-quote">
        <blockquote>
          "Power BI tells you the score.<br/>
          <em>Atlas tells you the play to run next.</em>"
        </blockquote>
        <p class="attrib">— The core idea behind every design decision</p>
      </div>
      <div class="grid3" style="margin-top:28px">
        <div class="card">
          <div class="icon">🎯</div>
          <h3>Proactive</h3>
          <p>Surfaces risks and patterns before the QBR — not after</p>
        </div>
        <div class="card">
          <div class="icon">💬</div>
          <h3>Conversational</h3>
          <p>Ask "why is win rate down?" in plain English — get a real answer</p>
        </div>
        <div class="card">
          <div class="icon">🧠</div>
          <h3>Actionable</h3>
          <p>Every insight ends with a recommended lever to pull</p>
        </div>
      </div>
    </div>
  </div>

  <!-- 4: Comparison -->
  <div class="slide" data-idx="3">
    <div class="slide-inner">
      <div class="tag">Comparison</div>
      <h2>Power BI vs Atlas — the real difference</h2>
      <table class="cmp-table">
        <thead>
          <tr>
            <th>Capability</th>
            <th class="col-pbi">Power BI Today</th>
            <th class="col-atlas">Atlas</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Shows KPI values</td><td><span class="badge-yes">Yes</span></td><td><span class="badge-yes">Yes</span></td></tr>
          <tr><td>Explains <em>why</em> a KPI moved</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">Yes — AI narrative</span></td></tr>
          <tr><td>Recommends what to do</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">Yes — action layer</span></td></tr>
          <tr><td>Natural language questions</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">Yes — chat interface</span></td></tr>
          <tr><td>Proactive risk alerts</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">Roadmap Q3</span></td></tr>
          <tr><td>Per-user data governance</td><td><span class="badge-yes">Unity Catalog</span></td><td><span class="badge-yes">Same — user OAuth token</span></td></tr>
          <tr><td>Quarter-end forecast</td><td><span class="badge-no">No</span></td><td><span class="badge-yes">Roadmap Q3</span></td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 5: Three Differentiators -->
  <div class="slide" data-idx="4">
    <div class="slide-inner">
      <div class="tag">What Makes It Different</div>
      <h2>Three layers Power BI doesn't have</h2>
      <div class="grid3" style="margin-top:28px">
        <div class="diff-card">
          <span class="num-big">1</span>
          <div class="icon" style="font-size:1.8rem;margin-bottom:12px">💡</div>
          <h3 style="font-size:1.1rem;margin-bottom:10px">The "So What?" Layer</h3>
          <p style="font-size:.9rem;color:var(--muted);line-height:1.6">
            Every KPI card has an AI-generated narrative. Not just the number — the implication. 
            "Win rate is down 3 pts vs last quarter. Primary driver: NA Enterprise segment. 
            Recommended action: review recent lost opps in that segment."
          </p>
        </div>
        <div class="diff-card">
          <span class="num-big">2</span>
          <div class="icon" style="font-size:1.8rem;margin-bottom:12px">👤</div>
          <h3 style="font-size:1.1rem;margin-bottom:10px">Personalised Views</h3>
          <p style="font-size:.9rem;color:var(--muted);line-height:1.6">
            A CRO sees everything. A Regional VP sees their geo. An ISG leader sees ISG metrics. 
            Unity Catalog enforces this at the data layer — not through manual filters 
            someone forgets to apply.
          </p>
        </div>
        <div class="diff-card">
          <span class="num-big">3</span>
          <div class="icon" style="font-size:1.8rem;margin-bottom:12px">🗣️</div>
          <h3 style="font-size:1.1rem;margin-bottom:10px">Conversational</h3>
          <p style="font-size:.9rem;color:var(--muted);line-height:1.6">
            Ask it anything about the data. "Show me coverage trends for Enterprise." 
            "What's driving the ADS drop?" It answers in plain English, grounded in live numbers — 
            not a generic LLM answer.
          </p>
        </div>
      </div>
    </div>
  </div>

  <!-- 6: Architecture -->
  <div class="slide" data-idx="5">
    <div class="slide-inner">
      <div class="tag">Architecture</div>
      <h2>How it works — simple version</h2>
      <div class="arch">
        <div class="arch-node">
          <div class="icon">🗄️</div>
          <h3>Databricks</h3>
          <p>Unity Catalog<br/>Delta tables<br/>Live SQL queries</p>
        </div>
        <div class="arch-arrow">→</div>
        <div class="arch-node">
          <div class="icon">⚡</div>
          <h3>FastAPI</h3>
          <p>Python backend<br/>14 KPI endpoints<br/>2-min cache</p>
        </div>
        <div class="arch-arrow">→</div>
        <div class="arch-node">
          <div class="icon">🤖</div>
          <h3>Claude Sonnet</h3>
          <p>AI narratives<br/>Chat answers<br/>Databricks serving</p>
        </div>
        <div class="arch-arrow">→</div>
        <div class="arch-node">
          <div class="icon">⚛️</div>
          <h3>React UI</h3>
          <p>Dark dashboard<br/>Filters &amp; slicers<br/>Chat panel</p>
        </div>
        <div class="arch-arrow">→</div>
        <div class="arch-node" style="border-color:rgba(79,156,249,.4)">
          <div class="icon">👤</div>
          <h3>User</h3>
          <p>Authenticates via<br/>Databricks OAuth<br/>Sees their data only</p>
        </div>
      </div>
      <div style="margin-top:24px;display:flex;gap:12px;flex-wrap:wrap">
        <span class="chip">Databricks Apps platform</span>
        <span class="chip green">No separate infra to manage</span>
        <span class="chip purple">x-forwarded-access-token auth</span>
        <span class="chip amber">Fallback to demo data if warehouse offline</span>
      </div>
    </div>
  </div>

  <!-- 7: AI Features -->
  <div class="slide" data-idx="6">
    <div class="slide-inner">
      <div class="tag">AI Layer</div>
      <h2>7 places AI adds real value</h2>
      <div class="ai-grid">
        <div class="ai-item"><div class="dot"></div><div><h3 style="font-size:.9rem;margin-bottom:4px">KPI Narrative</h3><p style="font-size:.82rem;color:var(--muted)">Plain-English explanation of each metric's current status</p></div></div>
        <div class="ai-item"><div class="dot"></div><div><h3 style="font-size:.9rem;margin-bottom:4px">Risk Flagging</h3><p style="font-size:.82rem;color:var(--muted)">"You're 15% behind pace — here's which segment is driving it"</p></div></div>
        <div class="ai-item"><div class="dot"></div><div><h3 style="font-size:.9rem;margin-bottom:4px">Chat Interface</h3><p style="font-size:.82rem;color:var(--muted)">Ask any question about live data in natural language</p></div></div>
        <div class="ai-item"><div class="dot"></div><div><h3 style="font-size:.9rem;margin-bottom:4px">Recommended Actions</h3><p style="font-size:.82rem;color:var(--muted)">Each insight ends with a concrete lever to pull</p></div></div>
        <div class="ai-item"><div class="dot"></div><div><h3 style="font-size:.9rem;margin-bottom:4px">Pattern Recognition</h3><p style="font-size:.82rem;color:var(--muted)">Cross-segment correlations that are hard to spot in static tables</p></div></div>
        <div class="ai-item"><div class="dot"></div><div><h3 style="font-size:.9rem;margin-bottom:4px">Quarter-End Forecast</h3><p style="font-size:.82rem;color:var(--muted)">Statistical pacing model — "on current trajectory, you'll land at X%"</p></div></div>
        <div class="ai-item"><div class="dot"></div><div><h3 style="font-size:.9rem;margin-bottom:4px">Rule-Based Safety</h3><p style="font-size:.82rem;color:var(--muted)">Deterministic checks run first — AI narrates, math is never outsourced to the model</p></div></div>
      </div>
    </div>
  </div>

  <!-- 8: Data Foundation -->
  <div class="slide" data-idx="7">
    <div class="slide-inner">
      <div class="tag">Data Foundation</div>
      <h2>What's underneath</h2>
      <div class="data-grid">
        <div class="data-block">
          <h3>Source Tables</h3>
          <div class="chip-list">
            <span class="chip">gaim_pipeline_daily_snapshot</span>
            <span class="chip">gaim_snapshot_pipeline_created_cq_daily</span>
            <span class="chip">cds_targets_monthly</span>
            <span class="chip">MQL count table</span>
          </div>
        </div>
        <div class="data-block">
          <h3>14 Live KPIs</h3>
          <div class="chip-list">
            <span class="chip green">Won Pipeline</span>
            <span class="chip green">Won Volume</span>
            <span class="chip green">ADS</span>
            <span class="chip green">Win Rate</span>
            <span class="chip green">Coverage</span>
            <span class="chip green">Active Pipeline</span>
            <span class="chip green">MQL Count</span>
            <span class="chip green">Opps Created</span>
            <span class="chip green">Created Pipeline</span>
            <span class="chip green">Close Rate $</span>
            <span class="chip green">Pipeline Attainment</span>
            <span class="chip green">Won Attainment</span>
            <span class="chip green">AOS</span>
            <span class="chip green">Close Rate</span>
          </div>
        </div>
        <div class="data-block">
          <h3>Filter Dimensions</h3>
          <div class="chip-list">
            <span class="chip purple">Geo / Market</span>
            <span class="chip purple">Channel (SMB / Mid-Market / Enterprise)</span>
            <span class="chip purple">Product (Connect / Resolve / All)</span>
            <span class="chip purple">Date range</span>
          </div>
        </div>
        <div class="data-block">
          <h3>Data Refresh</h3>
          <div class="chip-list">
            <span class="chip amber">2-minute in-memory cache</span>
            <span class="chip amber">Falls back to demo data on timeout</span>
            <span class="chip amber">Same Databricks warehouse as Hermes</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 9: Concerns -->
  <div class="slide" data-idx="8">
    <div class="slide-inner">
      <div class="tag">Concerns &amp; Mitigations</div>
      <h2>Risks we've thought through</h2>
      <div style="display:flex;flex-direction:column;gap:14px;margin-top:24px">
        <div class="card" style="display:grid;grid-template-columns:200px 1fr;gap:20px;align-items:start">
          <div><div class="label risk" style="font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px">⚠️ Data Governance</div><p style="font-size:.85rem;color:var(--muted)">Revenue data sensitivity; who can see what</p></div>
          <div><div class="label fix" style="font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px">✅ Mitigation</div><p style="font-size:.88rem;line-height:1.5">x-forwarded-access-token: every user authenticates with their own Databricks identity. Unity Catalog row/column permissions apply automatically. No shared service account exposes data to the wrong person.</p></div>
        </div>
        <div class="card" style="display:grid;grid-template-columns:200px 1fr;gap:20px;align-items:start">
          <div><div class="label risk" style="font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px">⚠️ AI Hallucination</div><p style="font-size:.85rem;color:var(--muted)">LLM makes up numbers or trends</p></div>
          <div><div class="label fix" style="font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px">✅ Mitigation</div><p style="font-size:.88rem;line-height:1.5">AI never calculates — it narrates. Numbers come from SQL. The model receives the actual KPI values and explains them. Rule-based checks run first and override the AI if they conflict.</p></div>
        </div>
        <div class="card" style="display:grid;grid-template-columns:200px 1fr;gap:20px;align-items:start">
          <div><div class="label risk" style="font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px">⚠️ Cost</div><p style="font-size:.85rem;color:var(--muted)">LLM API calls add up</p></div>
          <div><div class="label fix" style="font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px">✅ Mitigation</div><p style="font-size:.88rem;line-height:1.5">AI calls are per-click, not always-on. Rule-based fallback means many requests never reach the LLM. SQL warehouse already used by Hermes — no new infra cost.</p></div>
        </div>
      </div>
    </div>
  </div>

  <!-- 10: Role-Based Views -->
  <div class="slide" data-idx="9">
    <div class="slide-inner">
      <div class="tag">User-Centric Design</div>
      <h2>Who sees what — role-based profiles</h2>
      <p style="margin-bottom:4px">Currently: all 14 KPIs are visible to everyone with app access. <strong style="color:var(--amber)">Next phase: scoped views per role.</strong></p>
      <table class="role-table">
        <thead>
          <tr>
            <th>Role</th>
            <th>KPI Scope</th>
            <th>Data Scope</th>
            <th>Extra Features</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>CRO</strong></td>
            <td>All 14 KPIs</td>
            <td>All geos, channels, products</td>
            <td>Cross-segment benchmarks, forecasts</td>
          </tr>
          <tr>
            <td><strong>Regional VP</strong></td>
            <td>All 14 KPIs</td>
            <td>Their geo only (auto-filtered)</td>
            <td>Peer-geo comparison (anonymised)</td>
          </tr>
          <tr>
            <td><strong>ISG Leader</strong></td>
            <td>MQL, pipeline, coverage</td>
            <td>ISG product lines</td>
            <td>MQL-to-opportunity funnel</td>
          </tr>
          <tr>
            <td><strong>Sales Director</strong></td>
            <td>Win rate, ADS, volume</td>
            <td>Their channel × geo</td>
            <td>Rep-level rollup (roadmap)</td>
          </tr>
          <tr>
            <td><strong>Finance</strong></td>
            <td>Attainment, pipeline $</td>
            <td>All (read-only)</td>
            <td>Quarter-end projection</td>
          </tr>
        </tbody>
      </table>
      <p style="margin-top:16px;font-size:.85rem;color:var(--muted)">
        <strong style="color:var(--blue)">How it works:</strong> On login, the app reads the user's email from the Databricks OAuth token → looks up their role in a config table → filters KPIs and data automatically. Unity Catalog enforces the data boundary — even if the UI shows a filter, the warehouse rejects queries outside the user's permission set.
      </p>
    </div>
  </div>

  <!-- 11: Roadmap -->
  <div class="slide" data-idx="10">
    <div class="slide-inner">
      <div class="tag">Current State &amp; Roadmap</div>
      <h2>Where we are and where we're going</h2>
      <div class="roadmap">
        <div class="rm-col built">
          <h3>✅ Built &amp; Live</h3>
          <ul class="rm-list">
            <li>14 live KPIs from Databricks (gaim_pipeline, targets, MQL)</li>
            <li>AI narrative for every KPI (Claude Sonnet 4.6)</li>
            <li>Conversational chat interface grounded in live data</li>
            <li>3 filter dimensions: Geo, Channel, Product</li>
            <li>x-forwarded-access-token auth (Unity Catalog)</li>
            <li>2-minute cache + graceful demo-data fallback</li>
            <li>Deployed on Databricks Apps (goto-shared/gaim-executive-app)</li>
          </ul>
        </div>
        <div class="rm-col next">
          <h3>🔜 Next Phase</h3>
          <ul class="rm-list">
            <li>Role-based profiles (CRO vs VP vs ISG) with auto-scoped views</li>
            <li>Quarter-end forecast (statistical pacing model)</li>
            <li>Proactive risk alerts ("Win rate crossed a threshold")</li>
            <li>Rep-level rollup data (pending governance sign-off)</li>
            <li>Historical trend comparison (QoQ, YoY)</li>
            <li>Mobile-friendly responsive layout</li>
            <li>Feedback loop: thumbs up/down on AI narratives to improve prompts</li>
          </ul>
        </div>
      </div>
    </div>
  </div>

  <!-- 12: What I Need -->
  <div class="slide" data-idx="11">
    <div class="slide-inner">
      <div class="tag">Five Asks</div>
      <h2>What I need from this group</h2>
      <ul class="ask-list">
        <li><span class="ask-num">1</span><span class="ask-txt"><strong>Data governance sign-off</strong> — Which tables and columns are approved for AI queries? Should the model see revenue numbers, or only derived KPIs?</span></li>
        <li><span class="ask-num">2</span><span class="ask-txt"><strong>A pilot group of 3–4 executives</strong> — 30 minutes each to test and give feedback on what's useful vs what's noise.</span></li>
        <li><span class="ask-num">3</span><span class="ask-txt"><strong>Unity Catalog permissions setup</strong> — Define who should have access to which schemas so the x-forwarded-token pattern can enforce it properly.</span></li>
        <li><span class="ask-num">4</span><span class="ask-txt"><strong>KPI prioritisation</strong> — Of the 14 KPIs, which 5–6 matter most to each executive role? We'll build the personalised views around those.</span></li>
        <li><span class="ask-num">5</span><span class="ask-txt"><strong>Feedback on the AI narratives</strong> — Are they accurate? Too detailed? Too vague? The quality of the prompts depends entirely on domain input from you.</span></li>
      </ul>
    </div>
  </div>

  <!-- 13: Live Demo -->
  <div class="slide" data-idx="12">
    <div class="slide-inner" style="text-align:center">
      <div class="tag">Live Demo</div>
      <h2>See it in action</h2>
      <div class="demo-box">
        <p style="font-size:1rem;color:var(--muted)">The app is deployed and live on Databricks Apps.</p>
        <a href="#" onclick="return false;" id="demo-link">🚀 Open Atlas Executive Insights</a>
        <ul class="steps">
          <li><span>1</span>Log in with your Databricks SSO</li>
          <li><span>2</span>See the 14 KPI cards load from live data</li>
          <li><span>3</span>Click any KPI → read the AI narrative</li>
          <li><span>4</span>Change a filter (e.g. Geo = NA) → watch it update</li>
          <li><span>5</span>Open the chat → ask "why is win rate down?"</li>
        </ul>
      </div>
    </div>
  </div>

  <!-- 14: Thank You -->
  <div class="slide" data-idx="13">
    <div class="slide-inner thankyou-center">
      <div class="tag">Thank You</div>
      <h1 style="font-size:clamp(1.8rem,4vw,3rem)">Atlas <span class="grad">Executive Insights</span></h1>
      <p style="font-size:1.05rem;max-width:480px;margin:16px auto 0;color:var(--muted)">
        Built to help sales leadership act faster on better information.<br/>Your feedback shapes what comes next.
      </p>
      <div class="built-by">
        <span class="built-pill">🗄️ Databricks</span>
        <span class="built-pill">🤖 Claude Sonnet 4.6</span>
        <span class="built-pill">🔐 Unity Catalog</span>
        <span class="built-pill">⚛️ React + FastAPI</span>
      </div>
      <button class="feedback-cta" onclick="openModal()">📝 Leave Your Feedback</button>
      <p style="margin-top:20px;font-size:.85rem;color:var(--muted)">
        Questions? Find me in Slack or open a GitHub issue on <strong style="color:var(--blue)">goto-shared/gaim-executive-app</strong>
      </p>
    </div>
  </div>

</div><!-- /deck -->

<!-- ─────────────────── NAV BAR ─────────────────── -->
<div id="nav">
  <button class="nav-btn" id="btn-prev" onclick="prevSlide()">◀ Prev</button>
  <div style="display:flex;align-items:center;gap:14px">
    <div class="dots" id="dots"></div>
    <span class="slide-counter" id="counter">1 / 14</span>
  </div>
  <button class="nav-btn" id="btn-next" onclick="nextSlide()">Next ▶</button>
</div>

<!-- ─────────────────── REACTION BAR ─────────────────── -->
<div id="reaction-bar">
  <button class="rxn-btn" title="Makes sense" onclick="react('👍')">👍</button>
  <button class="rxn-btn" title="Have a question" onclick="react('❓')">❓</button>
  <button class="rxn-btn" title="New idea" onclick="react('💡')">💡</button>
  <button class="rxn-btn" title="Concern" onclick="react('⚠️')">⚠️</button>
  <button class="nav-btn" style="margin-left:8px" onclick="openModal()">📝 Feedback</button>
</div>

<!-- ─────────────────── FEEDBACK MODAL ─────────────────── -->
<div id="modal-overlay" onclick="closeModalOnOverlay(event)">
  <div id="modal">
    <div id="modal-form">
      <h2>Share Your Feedback</h2>
      <p class="sub">Your input directly shapes the roadmap. Takes 2 minutes.</p>

      <div class="form-group">
        <label>Your Name (optional)</label>
        <input type="text" id="f-name" placeholder="e.g. Alex Johnson"/>
      </div>
      <div class="form-group">
        <label>Your Role</label>
        <select id="f-role">
          <option value="">Select your role</option>
          <option>CRO</option>
          <option>VP Sales</option>
          <option>Regional VP</option>
          <option>Sales Director</option>
          <option>ISG / Marketing Leader</option>
          <option>Finance</option>
          <option>Sales Ops / Analytics</option>
          <option>Engineering / Product</option>
          <option>Other</option>
        </select>
      </div>
      <div class="form-group">
        <label>Overall impression (1–5)</label>
        <div class="star-row" id="stars">
          <span class="star" data-v="1" onclick="setStar(1)">⭐</span>
          <span class="star" data-v="2" onclick="setStar(2)">⭐</span>
          <span class="star" data-v="3" onclick="setStar(3)">⭐</span>
          <span class="star" data-v="4" onclick="setStar(4)">⭐</span>
          <span class="star" data-v="5" onclick="setStar(5)">⭐</span>
        </div>
      </div>
      <div class="form-group">
        <label>Most valuable feature to you</label>
        <select id="f-valuable">
          <option value="">Select one</option>
          <option>AI narrative explaining KPIs</option>
          <option>Conversational chat interface</option>
          <option>Live data (not static reports)</option>
          <option>Recommended actions</option>
          <option>Role-based personalised views</option>
          <option>Quarter-end forecasting (planned)</option>
          <option>Proactive alerts (planned)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Biggest concern</label>
        <textarea id="f-concern" rows="2" placeholder="Data accuracy? Governance? Something else?"></textarea>
      </div>
      <div class="form-group">
        <label>Would you use this in your workflow?</label>
        <select id="f-use">
          <option value="">Select one</option>
          <option>Yes — immediately</option>
          <option>Yes — after some changes (tell me below)</option>
          <option>Maybe — need to see more</option>
          <option>No — not relevant to my role</option>
        </select>
      </div>
      <div class="form-group">
        <label>Any other comments or ideas</label>
        <textarea id="f-comments" rows="3" placeholder="What would make this a must-have for you?"></textarea>
      </div>
      <div class="btn-row">
        <button class="btn-cancel" onclick="closeModal()">Cancel</button>
        <button class="btn-submit" onclick="submitFeedback()">Submit Feedback →</button>
      </div>
    </div>
    <div id="modal-success" style="display:none">
      <div class="success-msg">
        <div class="check">🎉</div>
        <h3>Thank you!</h3>
        <p>Your feedback has been saved. It'll be reviewed before the next iteration.</p>
        <button class="btn-submit" style="margin-top:20px;width:100%" onclick="closeModal()">Close</button>
      </div>
    </div>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────────
const TOTAL = 14;
let current  = 0;
let starVal  = 0;
const reactions = {};  // { slideIdx: [emoji, ...] }

// ── Init ─────────────────────────────────────────────────────────────────────
const slides   = document.querySelectorAll('.slide');
const dotsEl   = document.getElementById('dots');
const counter  = document.getElementById('counter');
const progress = document.getElementById('progress');

// Build dots
for (let i = 0; i < TOTAL; i++) {
  const b = document.createElement('button');
  b.className = 'dot-btn' + (i === 0 ? ' active' : '');
  b.title = `Slide ${i + 1}`;
  b.addEventListener('click', () => goTo(i));
  dotsEl.appendChild(b);
}
goTo(0);

// ── Navigation ───────────────────────────────────────────────────────────────
function goTo(n) {
  slides[current].classList.remove('active');
  slides[current].classList.add('exit-left');
  setTimeout(() => slides[current].classList.remove('exit-left'), 500);
  current = Math.max(0, Math.min(TOTAL - 1, n));
  slides[current].classList.add('active');
  // dots
  document.querySelectorAll('.dot-btn').forEach((d, i) =>
    d.classList.toggle('active', i === current));
  // counter
  counter.textContent = `${current + 1} / ${TOTAL}`;
  // progress bar
  progress.style.width = `${((current + 1) / TOTAL) * 100}%`;
  // nav buttons
  document.getElementById('btn-prev').disabled = current === 0;
  document.getElementById('btn-next').disabled = current === TOTAL - 1;
}
function nextSlide() { goTo(current + 1); }
function prevSlide() { goTo(current - 1); }

// Keyboard navigation
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
  if (e.key === 'ArrowRight' || e.key === ' ')  { e.preventDefault(); nextSlide(); }
  if (e.key === 'ArrowLeft')                    { e.preventDefault(); prevSlide(); }
  if (e.key === 'Escape')                        closeModal();
});

// ── Reactions ────────────────────────────────────────────────────────────────
function react(emoji) {
  if (!reactions[current]) reactions[current] = [];
  if (!reactions[current].includes(emoji)) {
    reactions[current].push(emoji);
  }
  // visual feedback
  const btns = document.querySelectorAll('.rxn-btn');
  btns.forEach(b => { if (b.textContent.trim() === emoji) { b.classList.add('active'); setTimeout(() => b.classList.remove('active'), 600); }});
}

// ── Stars ────────────────────────────────────────────────────────────────────
function setStar(n) {
  starVal = n;
  document.querySelectorAll('.star').forEach((s, i) =>
    s.classList.toggle('on', i < n));
}

// ── Modal ────────────────────────────────────────────────────────────────────
function openModal() {
  document.getElementById('modal-overlay').classList.add('open');
  document.getElementById('modal-form').style.display = 'block';
  document.getElementById('modal-success').style.display = 'none';
}
function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}
function closeModalOnOverlay(e) {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}

async function submitFeedback() {
  const data = {
    name:           document.getElementById('f-name').value.trim(),
    role:           document.getElementById('f-role').value,
    overall_rating: starVal,
    most_valuable:  document.getElementById('f-valuable').value,
    main_concern:   document.getElementById('f-concern').value.trim(),
    would_use:      document.getElementById('f-use').value,
    comments:       document.getElementById('f-comments').value.trim(),
    reactions:      reactions,
  };
  try {
    const res  = await fetch('/api/feedback', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify(data),
    });
    const json = await res.json();
    if (json.success) {
      document.getElementById('modal-form').style.display  = 'none';
      document.getElementById('modal-success').style.display = 'block';
    } else {
      alert('Could not save feedback: ' + (json.error || 'unknown error'));
    }
  } catch (err) {
    alert('Network error — check your connection.');
  }
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
