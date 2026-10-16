# Prompt2Work — AI-Powered Software Automation (Hackathon MVP)

Natural language -> AI plan (Gemini) -> user approval -> real execution -> verified output.

## Workflows
1. **CAD bracket** — plate with holes. Outputs: STL (real 3D, volume-verified), DXF (2D drawing), SolidWorks VBA macro.
2. **Excel/CSV analysis** — clean data, totals, group summaries, charts. Output: .xlsx (re-opened and verified).

## Run locally
```bash
pip install -r requirements.txt
mkdir -p .streamlit && cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fir key edit karo
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Project ko GitHub repo me push karo (`.streamlit/secrets.toml` push NAHI karna, `.gitignore` me hai).
2. share.streamlit.io -> New app -> repo select -> Main file: `app.py`.
3. App **Settings -> Secrets** me paste karo:
```toml
GEMINI_API_KEY = "your_key"
GEMINI_MODEL = "gemini-3.8-flash"
```
4. Deploy.

## Structure
```
app.py              Streamlit UI (prompt -> plan -> approve -> execute -> download)
core/llm.py         Gemini planner (JSON plan)
core/excel_tool.py  validation + pandas/openpyxl execution + verification
core/cad_tool.py    validation + STL/DXF/VBA generation + volume verification
assets/style.css    Theme: gradients, fonts, layout
.streamlit/config.toml  Streamlit theme colours
```

## Honest limits (demo me ye bolna)
- SolidWorks macro generate hota hai, lekin Streamlit Cloud (Linux) par SolidWorks run nahi ho sakta. Live SolidWorks demo ke liye app Windows laptop par chalao.
- AI sirf structured plan banata hai; execution validated Python code karta hai (AI-generated arbitrary code run nahi hota).
