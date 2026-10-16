import json

import plotly.graph_objects as go
import streamlit as st

from core import cad_tool, excel_tool
from core.llm import get_api_key, plan_task

st.set_page_config(page_title="Prompt2Work", page_icon="⚙️", layout="wide")

st.title("⚙️ Prompt2Work")
st.caption("Describe the task in plain language. AI plans it, you approve it, and it executes on real software integrations.")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Settings")
    try:
        model = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
    except Exception:
        model = "gemini-2.5-flash"
    model = st.text_input("Gemini model", value=model)
    api_key = get_api_key(st.secrets)
    if api_key:
        st.success("Gemini API key mil gayi ✅")
    else:
        api_key = st.text_input("Gemini API key (secrets me na ho to yahan daalo)", type="password")
    st.divider()
    st.markdown(
        "**Supported workflows**\n- 🔩 CAD: rectangular bracket with holes (STL + DXF + SolidWorks macro)\n"
        "- 📊 Excel/CSV: clean, totals, group summaries, charts"
    )
    st.markdown("**Examples**")
    st.code("Create a rectangular mounting bracket 100 mm long, 60 mm wide, 8 mm thick, with four 8 mm holes.", language=None)
    st.code("Remove duplicates, give total sales by region and make a bar chart.", language=None)

# ---------------- Input ----------------
for k in ("plan", "validated", "errors", "assumptions", "result", "df"):
    st.session_state.setdefault(k, None)

col_a, col_b = st.columns([3, 2])
with col_a:
    prompt = st.text_area("What do you want to do?", height=140,
                          placeholder="e.g. Create a bracket 100x60x8 mm with four 8 mm mounting holes")
with col_b:
    upload = st.file_uploader("Optional: spreadsheet (.xlsx / .csv)", type=["xlsx", "xls", "csv"])

if st.button("1️⃣ Generate plan", type="primary", disabled=not prompt.strip()):
    st.session_state.update(plan=None, validated=None, errors=None, assumptions=None, result=None)
    try:
        file_ctx, df = "", None
        if upload is not None:
            df = excel_tool.load_dataframe(upload)
            file_ctx = excel_tool.describe(df)
        st.session_state.df = df
        with st.spinner("AI plan bana raha hai..."):
            plan = plan_task(prompt, api_key, model, file_ctx)
        st.session_state.plan = plan

        errors, validated, assumptions = [], None, []
        wf = plan.get("workflow")
        if not plan["missing_info"]:
            if wf == "cad_bracket":
                errors, validated, assumptions = cad_tool.validate(plan["parameters"])
            elif wf == "excel_analysis":
                if df is None:
                    errors = ["Excel/CSV file upload karo."]
                else:
                    errors, validated = excel_tool.validate(df, plan["parameters"])
        st.session_state.update(validated=validated, errors=errors, assumptions=assumptions)
    except Exception as e:
        st.error(f"Plan banane me error: {e}")

# ---------------- Plan review ----------------
plan = st.session_state.plan
if plan:
    st.subheader("Plan")
    st.info(plan.get("summary", ""))

    if plan["workflow"] == "unsupported":
        st.warning("Ye request abhi supported nahi hai. Supported: CAD bracket aur Excel/CSV analysis.")
    if plan["missing_info"]:
        st.warning("Kuch zaroori info missing hai. Prompt me add karke dobara plan banao:")
        for q in plan["missing_info"]:
            st.markdown(f"- {q}")
    for e in st.session_state.errors or []:
        st.error(e)
    for a in (st.session_state.assumptions or []) + plan["warnings"]:
        st.warning(a)

    if plan["steps"]:
        st.markdown("**Steps**")
        for i, s in enumerate(plan["steps"], 1):
            st.markdown(f"{i}. {s}")
    with st.expander("Extracted parameters (JSON)"):
        st.json(plan["parameters"])

    ready = (st.session_state.validated is not None and not st.session_state.errors
             and not plan["missing_info"] and plan["workflow"] != "unsupported")
    if ready:
        approve = st.checkbox("✅ Main plan approve karta/karti hoon")
        if st.button("2️⃣ Execute", type="primary", disabled=not approve):
            try:
                with st.spinner("Execute ho raha hai..."):
                    if plan["workflow"] == "cad_bracket":
                        st.session_state.result = ("cad", cad_tool.execute(st.session_state.validated))
                    else:
                        xb, log, prev = excel_tool.execute(st.session_state.df, st.session_state.validated)
                        st.session_state.result = ("excel", {"xlsx": xb, "log": log, "previews": prev})
            except Exception as e:
                st.session_state.result = None
                st.error(f"Execution fail hua: {e}")

# ---------------- Result ----------------
res = st.session_state.result
if res:
    kind, r = res
    st.subheader("Result")
    tab1, tab2, tab3 = st.tabs(["Preview", "Execution log", "Downloads"])

    with tab1:
        if kind == "cad":
            m = r["mesh"]
            fig = go.Figure(go.Mesh3d(
                x=m.vertices[:, 0], y=m.vertices[:, 1], z=m.vertices[:, 2],
                i=m.faces[:, 0], j=m.faces[:, 1], k=m.faces[:, 2],
                color="#4f8bf9", flatshading=True, opacity=1.0))
            fig.update_layout(scene=dict(aspectmode="data"), margin=dict(l=0, r=0, t=0, b=0), height=480)
            st.plotly_chart(fig, use_container_width=True)
        else:
            for name, df in r["previews"].items():
                st.markdown(f"**{name}**")
                st.dataframe(df, use_container_width=True)

    with tab2:
        for line in r["log"]:
            st.write(("✅ " if line.startswith(("OK", "VERIFIED")) else "• ") + line)

    with tab3:
        if kind == "cad":
            st.download_button("⬇️ 3D model (STL)", r["stl"], "bracket.stl", "model/stl")
            st.download_button("⬇️ 2D drawing (DXF)", r["dxf"], "bracket.dxf", "application/dxf")
            st.download_button("⬇️ SolidWorks macro (.bas)", r["vba"].encode(), "bracket_solidworks.bas", "text/plain")
            st.caption("Note: STL/DXF yahan actually generate aur verify hue hain. SolidWorks macro SolidWorks (Windows) me manually run karni hogi - ye yahan execute nahi hoti.")
        else:
            st.download_button("⬇️ Output workbook (.xlsx)", r["xlsx"], "prompt2work_output.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
