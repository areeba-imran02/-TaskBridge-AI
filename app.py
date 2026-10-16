import html
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from core import cad_tool, excel_tool
from core.llm import DEFAULT_MODEL, get_api_key, plan_task

st.set_page_config(page_title="Prompt2Work", page_icon="⚙️", layout="wide")
st.markdown(f"<style>{(Path(__file__).parent / 'assets' / 'style.css').read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True)

esc = html.escape
WORKFLOW_NAMES = {"cad_bracket": "CAD bracket", "excel_analysis": "Spreadsheet analysis", "unsupported": "Not supported"}
EXAMPLES = [
    ("Mounting bracket", "Create a rectangular mounting bracket 100 mm long, 60 mm wide, 8 mm thick, with four 8 mm mounting holes."),
    ("Sales summary", "Remove duplicates, calculate total sales by region and create a bar chart."),
]

for k in ("plan", "validated", "errors", "assumptions", "result", "df"):
    st.session_state.setdefault(k, None)
st.session_state.setdefault("prompt_text", "")


def set_prompt(text):
    st.session_state.prompt_text = text


def stepper_html(stage):
    labels = ["Describe", "Review plan", "Approve and run", "Download"]
    parts = []
    for i, label in enumerate(labels, 1):
        cls = "done" if i < stage else "active" if i == stage else ""
        mark = "✓" if i < stage else str(i)
        parts.append(f'<div class="step {cls}"><span class="dot">{mark}</span><span class="lbl">{label}</span></div>')
        if i < len(labels):
            parts.append('<div class="step-line"></div>')
    return f'<div class="stepper">{"".join(parts)}</div>'


def tiles_html(plan):
    p, wf, items = plan.get("parameters") or {}, plan.get("workflow"), []
    if wf == "cad_bracket":
        mm = lambda v: f"{v:g} mm" if isinstance(v, (int, float)) else "missing"
        n, d = p.get("hole_count"), p.get("hole_diameter_mm")
        holes = f"{n} × Ø{d:g} mm" if n and isinstance(d, (int, float)) else (str(n) if n == 0 else "missing")
        items = [("Length", mm(p.get("length_mm"))), ("Width", mm(p.get("width_mm"))),
                 ("Thickness", mm(p.get("thickness_mm"))), ("Holes", holes)]
    elif wf == "excel_analysis":
        clean = p.get("clean") or {}
        items = [("Cleaning steps", sum(bool(v) for v in clean.values())), ("Totals", len(p.get("totals") or [])),
                 ("Group summaries", len(p.get("group_summaries") or [])), ("Charts", len(p.get("charts") or []))]
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="k">{esc(str(k))}</div><div class="v">{esc(str(v))}</div></div>' for k, v in items) + "</div>"


def log_html(lines):
    out = []
    for line in lines:
        if line.startswith("VERIFIED: "):
            out.append(f'<div><span class="tag v">verified</span>{esc(line[10:])}</div>')
        elif line.startswith("OK: "):
            out.append(f'<div><span class="tag">done</span>{esc(line[4:])}</div>')
        else:
            out.append(f"<div>{esc(line)}</div>")
    return f'<div class="logbox">{"".join(out)}</div>'


# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown('<div class="brand">Prompt2Work<small>Plain language in, real files out</small></div>', unsafe_allow_html=True)
    try:
        default_model = st.secrets.get("GEMINI_MODEL", DEFAULT_MODEL)
    except Exception:
        default_model = DEFAULT_MODEL
    api_key = get_api_key(st.secrets)
    if api_key:
        st.markdown('<div class="pill"><i></i>Gemini key connected</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="pill off"><i></i>Gemini key missing</div>', unsafe_allow_html=True)
        api_key = st.text_input("Paste your Gemini API key", type="password")
    with st.expander("Advanced"):
        model = st.text_input("Gemini model", value=default_model)

    st.markdown('<div class="side-h">What it can do</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="wf"><b>CAD bracket</b><span>Plate with holes. You get an STL, a DXF drawing and a SolidWorks macro.</span></div>'
        '<div class="wf"><b>Spreadsheet analysis</b><span>Clean data, calculate totals, summarise by group and add charts.</span></div>',
        unsafe_allow_html=True)

# ---------------- Hero + stepper ----------------
st.markdown(
    '<div class="hero"><div class="hero-inner">'
    '<div class="hero-title">Prompt2Work</div>'
    '<div class="hero-sub">Describe a task in plain language. AI drafts the plan, you approve it, '
    'and real software integrations produce the file.</div>'
    '<div class="chips"><span>Gemini planner</span><span>You approve every run</span><span>Output is verified</span></div>'
    '</div></div>', unsafe_allow_html=True)
stepper_slot = st.empty()

# ---------------- Input ----------------
with st.container(key="input_card"):
    st.markdown('<div class="card-title">What should it do?</div>'
                '<div class="card-sub">Include sizes or column names when you can. If something essential is missing, the AI will ask.</div>',
                unsafe_allow_html=True)
    left, right = st.columns([3, 2], gap="large")
    with left:
        prompt = st.text_area("Task", key="prompt_text", height=150, label_visibility="collapsed",
                              placeholder="Example: Create a bracket 100 x 60 x 8 mm with four 8 mm holes")
        ex_cols = st.columns(len(EXAMPLES) + 1)
        for i, (label, text) in enumerate(EXAMPLES):
            ex_cols[i].button(label, key=f"ex{i}", on_click=set_prompt, args=(text,))
    with right:
        upload = st.file_uploader("Spreadsheet (optional)", type=["xlsx", "xls", "csv"])
    generate = st.button("Generate plan", type="primary", disabled=not prompt.strip())

if generate:
    st.session_state.update(plan=None, validated=None, errors=None, assumptions=None, result=None)
    try:
        file_ctx, df = "", None
        if upload is not None:
            df = excel_tool.load_dataframe(upload)
            file_ctx = excel_tool.describe(df)
        st.session_state.df = df
        with st.spinner("Drafting the plan..."):
            plan = plan_task(prompt, api_key, model, file_ctx)
        st.session_state.plan = plan

        errors, validated, assumptions = [], None, []
        wf = plan.get("workflow")
        if not plan["missing_info"]:
            if wf == "cad_bracket":
                errors, validated, assumptions = cad_tool.validate(plan["parameters"])
            elif wf == "excel_analysis":
                if df is None:
                    errors = ["Upload a spreadsheet (.xlsx or .csv) for this task."]
                else:
                    errors, validated = excel_tool.validate(df, plan["parameters"])
        st.session_state.update(validated=validated, errors=errors, assumptions=assumptions)
    except Exception as e:
        st.error(f"Could not create the plan: {e}")

# ---------------- Plan ----------------
plan = st.session_state.plan
ready = False
if plan:
    wf = plan.get("workflow")
    badge_cls = "badge bad" if wf == "unsupported" else "badge"
    with st.container(key="plan_card"):
        st.markdown(f'<div class="card-title">Review the plan<span class="{badge_cls}">{esc(WORKFLOW_NAMES.get(wf, str(wf)))}</span></div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="callout">{esc(plan.get("summary", ""))}</div>', unsafe_allow_html=True)
        if wf == "unsupported":
            st.warning("This request isn't supported yet. Try a CAD bracket or a spreadsheet analysis.")
        if plan["missing_info"]:
            st.warning("Some essential details are missing. Add them to your description and generate the plan again:")
            for q in plan["missing_info"]:
                st.markdown(f"- {q}")
        for e in st.session_state.errors or []:
            st.error(e)
        for a in (st.session_state.assumptions or []) + plan["warnings"]:
            st.warning(a)

        if wf != "unsupported":
            st.markdown(tiles_html(plan), unsafe_allow_html=True)
        if plan["steps"]:
            st.markdown('<ol class="steps">' + "".join(f"<li>{esc(str(s))}</li>" for s in plan["steps"]) + "</ol>",
                        unsafe_allow_html=True)
        with st.expander("Extracted parameters (JSON)"):
            st.json(plan["parameters"])

        ready = (st.session_state.validated is not None and not st.session_state.errors
                 and not plan["missing_info"] and wf != "unsupported")
        if ready:
            approve = st.checkbox("I approve this plan")
            if st.button("Run plan", type="primary", disabled=not approve):
                try:
                    with st.spinner("Running..."):
                        if wf == "cad_bracket":
                            st.session_state.result = ("cad", cad_tool.execute(st.session_state.validated))
                        else:
                            xb, log, prev = excel_tool.execute(st.session_state.df, st.session_state.validated)
                            st.session_state.result = ("excel", {"xlsx": xb, "log": log, "previews": prev})
                except Exception as e:
                    st.session_state.result = None
                    st.error(f"The run failed: {e}")

# ---------------- Result ----------------
res = st.session_state.result
if res:
    kind, r = res
    with st.container(key="result_card"):
        st.markdown('<div class="banner-ok"><span class="tick">✓</span>Done. The output was generated and checked.</div>',
                    unsafe_allow_html=True)
        tab1, tab2, tab3 = st.tabs(["Preview", "Execution log", "Downloads"])

        with tab1:
            if kind == "cad":
                m = r["mesh"]
                fig = go.Figure(go.Mesh3d(
                    x=m.vertices[:, 0], y=m.vertices[:, 1], z=m.vertices[:, 2],
                    i=m.faces[:, 0], j=m.faces[:, 1], k=m.faces[:, 2],
                    color="#5B3DF5", flatshading=True,
                    lighting=dict(ambient=0.5, diffuse=0.85, specular=0.35, roughness=0.5),
                    lightposition=dict(x=200, y=-300, z=400)))
                hidden = dict(visible=False)
                fig.update_layout(scene=dict(aspectmode="data", xaxis=hidden, yaxis=hidden, zaxis=hidden,
                                             camera=dict(eye=dict(x=1.3, y=-1.5, z=1.1))),
                                  margin=dict(l=0, r=0, t=0, b=0), height=460, paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig)
            else:
                names = list(r["previews"])
                for t, name in zip(st.tabs(names), names):
                    with t:
                        st.dataframe(r["previews"][name])

        with tab2:
            st.markdown(log_html(r["log"]), unsafe_allow_html=True)

        with tab3:
            if kind == "cad":
                c1, c2, c3 = st.columns(3)
                c1.download_button("Download STL (3D model)", r["stl"], "bracket.stl", "model/stl")
                c2.download_button("Download DXF (2D drawing)", r["dxf"], "bracket.dxf", "application/dxf")
                c3.download_button("Download SolidWorks macro", r["vba"].encode(), "bracket_solidworks.bas", "text/plain")
                st.caption("The STL and DXF were generated and checked here. The SolidWorks macro is not run by this app; "
                           "open SolidWorks on Windows and run it there.")
            else:
                st.download_button("Download workbook (.xlsx)", r["xlsx"], "prompt2work_output.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------------- Stepper state ----------------
stage = 4 if res else 3 if ready else 2 if plan else 1
stepper_slot.markdown(stepper_html(stage), unsafe_allow_html=True)
