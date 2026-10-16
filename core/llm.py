"""Gemini based prompt understanding + task planning."""
import json
import os

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]

SYSTEM_PROMPT = """You are the planning engine of Prompt2Work, a tool that turns natural-language
requests into structured, executable action plans. You NEVER execute anything yourself.
You output ONLY one JSON object, no markdown, no commentary.

Supported workflows (choose exactly one):

1) "cad_bracket": a flat rectangular plate/bracket with round through-holes.
   parameters = {
     "length_mm": number|null, "width_mm": number|null, "thickness_mm": number|null,
     "hole_count": integer (0 if none), "hole_diameter_mm": number|null,
     "hole_pattern": "corners" | "line" | "center",
     "edge_margin_mm": number|null   // distance from plate edge to hole CENTRE; null if user did not say
   }
   - "corners" is for 4 holes, "line" is n holes evenly spaced along the length, "center" is 1 hole.
   - If the user says "four holes" use pattern "corners".

2) "excel_analysis": analyse an uploaded spreadsheet. You are given the real column names.
   parameters = {
     "clean": {"drop_duplicates": bool, "drop_empty_rows": bool, "strip_text": bool},
     "totals": [ {"column": str, "agg": "sum"|"mean"|"count"|"min"|"max"|"median"} ],
     "group_summaries": [ {"group_by": str, "column": str, "agg": "sum"|"mean"|"count"|"min"|"max"|"median"} ],
     "charts": [ {"summary_index": integer (0-based index into group_summaries), "type": "bar"|"line"|"pie", "title": str} ]
   }
   - Use ONLY column names that exist in the provided columns list, spelled exactly.

3) "unsupported": anything else. Explain briefly in "summary".

Output format:
{
  "workflow": "cad_bracket" | "excel_analysis" | "unsupported",
  "summary": "one or two sentences describing what will be done",
  "missing_info": ["question 1", ...],   // essential info that is missing. NEVER guess dimensions, ask instead.
  "steps": ["human readable step 1", ...],
  "warnings": ["..."],
  "parameters": { ... }
}
If a spreadsheet is needed but no file/columns are provided, put a question in missing_info.
Write summary, steps, warnings and questions in the same language the user used (English/Urdu/Hindi in Roman script is fine).
"""


def get_api_key(st_secrets=None, override: str = ""):
    if override:
        return override
    try:
        if st_secrets is not None and "GEMINI_API_KEY" in st_secrets:
            return st_secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "")


def plan_task(prompt: str, api_key: str, model: str = DEFAULT_MODEL, file_context: str = "") -> dict:
    if not api_key:
        raise ValueError("Gemini API key not found. Set GEMINI_API_KEY in Secrets.")

    client = genai.Client(api_key=api_key)
    user_content = f"USER REQUEST:\n{prompt}\n"
    if file_context:
        user_content += f"\nUPLOADED SPREADSHEET INFO:\n{file_context}\n"
    else:
        user_content += "\nNo spreadsheet uploaded.\n"

    def call(model_name):
        return client.models.generate_content(
            model=model_name,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )

    # Try the chosen model first; if Google says it's gone (404), try fallbacks automatically.
    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_err = None
    for name in candidates:
        for _ in range(2):
            try:
                resp = call(name)
            except Exception as e:
                last_err = e
                if "404" in str(e) or "NOT_FOUND" in str(e):
                    break  # try next model
                raise
            text = (resp.text or "").strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                plan = json.loads(text)
            except json.JSONDecodeError as e:
                last_err = e
                continue
            plan.setdefault("missing_info", [])
            plan.setdefault("steps", [])
            plan.setdefault("warnings", [])
            plan.setdefault("parameters", {})
            return plan
    raise ValueError(f"Could not create a plan. Last error: {last_err}")
