"""CAD workflow.
- Real 3D model (STL) built with trimesh + manifold boolean, verified by volume check
- 2D DXF drawing via ezdxf (opens in AutoCAD / SolidWorks / FreeCAD)
- SolidWorks VBA macro generated (needs SolidWorks on Windows to run, NOT executed here)
"""
import io
import math

import ezdxf
import numpy as np
import trimesh


def validate(params: dict):
    """Returns (errors, normalized_params, assumptions)."""
    errors, assumptions = [], []
    p = {}
    for key, label in [("length_mm", "length"), ("width_mm", "width"), ("thickness_mm", "thickness")]:
        v = params.get(key)
        if not isinstance(v, (int, float)) or v <= 0:
            errors.append(f"{label} missing ya invalid hai.")
        else:
            p[key] = float(v)

    n = params.get("hole_count", 0)
    p["hole_count"] = int(n) if isinstance(n, (int, float)) and n >= 0 else 0
    p["hole_pattern"] = params.get("hole_pattern") or ("corners" if p["hole_count"] == 4 else "line")

    if p["hole_count"] > 0:
        d = params.get("hole_diameter_mm")
        if not isinstance(d, (int, float)) or d <= 0:
            errors.append("hole diameter missing ya invalid hai.")
        else:
            p["hole_diameter_mm"] = float(d)
            m = params.get("edge_margin_mm")
            if not isinstance(m, (int, float)) or m <= 0:
                m = max(2 * d, 10.0)
                assumptions.append(f"Edge margin nahi diya gaya, default {m:g} mm use hua.")
            p["edge_margin_mm"] = float(m)
        if p["hole_pattern"] == "corners" and p["hole_count"] != 4:
            errors.append("'corners' pattern ke liye hole count 4 hona chahiye.")
        if p["hole_pattern"] == "center" and p["hole_count"] != 1:
            errors.append("'center' pattern ke liye hole count 1 hona chahiye.")
    else:
        p["hole_diameter_mm"], p["edge_margin_mm"] = 0.0, 0.0

    if not errors and p["hole_count"] > 0:
        r, m = p["hole_diameter_mm"] / 2, p["edge_margin_mm"]
        L, W = p["length_mm"], p["width_mm"]
        if m <= r:
            errors.append("Edge margin hole radius se bara hona chahiye (hole plate se bahar nikal raha hai).")
        if p["hole_pattern"] == "corners" and (m >= L / 2 or m >= W / 2):
            errors.append("Edge margin plate ke size ke hisaab se bohat bara hai.")
        if p["hole_pattern"] == "center" and (r >= L / 2 or r >= W / 2):
            errors.append("Hole plate se bara hai.")
        if p["hole_pattern"] == "line":
            if m >= L / 2 or r >= W / 2:
                errors.append("Hole line plate me fit nahi hoti.")
            elif p["hole_count"] > 1:
                pitch = (L - 2 * m) / (p["hole_count"] - 1)
                if pitch <= p["hole_diameter_mm"]:
                    errors.append("Holes aapas me overlap kar rahe hain.")
    return errors, p, assumptions


def hole_positions(p):
    L, W, m, n = p["length_mm"], p["width_mm"], p["edge_margin_mm"], p["hole_count"]
    if n == 0:
        return []
    if p["hole_pattern"] == "corners":
        return [(sx * (L / 2 - m), sy * (W / 2 - m)) for sx in (-1, 1) for sy in (-1, 1)]
    if p["hole_pattern"] == "center":
        return [(0.0, 0.0)]
    if n == 1:
        return [(0.0, 0.0)]
    xs = np.linspace(-(L / 2 - m), L / 2 - m, n)
    return [(float(x), 0.0) for x in xs]


def build_stl(p, holes):
    box = trimesh.creation.box(extents=(p["length_mm"], p["width_mm"], p["thickness_mm"]))
    if not holes:
        return box
    r, T = p["hole_diameter_mm"] / 2, p["thickness_mm"]
    cyls = []
    for x, y in holes:
        c = trimesh.creation.cylinder(radius=r, height=T * 2, sections=64)
        c.apply_translation((x, y, 0))
        cyls.append(c)
    return trimesh.boolean.difference([box] + cyls, engine="manifold")


def build_dxf(p, holes) -> bytes:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    L, W = p["length_mm"], p["width_mm"]
    msp.add_lwpolyline([(-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2)], close=True)
    for x, y in holes:
        msp.add_circle((x, y), p["hole_diameter_mm"] / 2)
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode("utf-8")


def build_vba(p, holes) -> str:
    mm = lambda v: f"{v / 1000:.6f}"  # SolidWorks API uses metres
    lines = [
        "' Prompt2Work - auto generated SolidWorks macro",
        "' SolidWorks me Tools > Macro > New, ye code paste karo aur Run karo.",
        "Dim swApp As Object",
        "Sub main()",
        "    Set swApp = Application.SldWorks",
        "    Dim part As Object",
        "    Set part = swApp.NewDocument(swApp.GetUserPreferenceStringValue(8), 0, 0, 0)",
        '    part.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0',
        "    part.SketchManager.InsertSketch True",
        f"    part.SketchManager.CreateCenterRectangle 0, 0, 0, {mm(p['length_mm'] / 2)}, {mm(p['width_mm'] / 2)}, 0",
    ]
    for x, y in holes:
        lines.append(f"    part.SketchManager.CreateCircleByRadius {mm(x)}, {mm(y)}, 0, {mm(p['hole_diameter_mm'] / 2)}")
    lines += [
        "    part.SketchManager.InsertSketch True",
        f"    part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, {mm(p['thickness_mm'])}, 0, False, False, False, False, 0, 0, False, False, False, False, True, True, True, 0, 0, False",
        '    part.ShowNamedView2 "*Isometric", 7',
        "    part.ViewZoomtofit2",
        "End Sub",
    ]
    return "\r\n".join(lines)


def execute(p: dict):
    """Returns dict(stl, dxf, vba, mesh, log)."""
    log = []
    holes = hole_positions(p)
    mesh = build_stl(p, holes)
    log.append(f"OK: 3D model bana ({len(mesh.faces)} faces, {len(holes)} holes).")

    expected = p["length_mm"] * p["width_mm"] * p["thickness_mm"]
    if holes:
        expected -= len(holes) * math.pi * (p["hole_diameter_mm"] / 2) ** 2 * p["thickness_mm"]
    err = abs(mesh.volume - expected) / expected
    if not mesh.is_watertight or err > 0.01:
        raise RuntimeError(f"Verification fail: watertight={mesh.is_watertight}, volume error={err:.2%}")
    log.append(f"VERIFIED: model watertight hai, volume {mesh.volume:,.0f} mm3 (expected se {err:.3%} farq).")

    stl_bytes = trimesh.exchange.export.export_mesh(mesh, file_type="stl")
    dxf = build_dxf(p, holes)
    log.append("OK: DXF 2D drawing bani.")
    vba = build_vba(p, holes)
    log.append("OK: SolidWorks VBA macro generate hui (SolidWorks me run karna baqi hai - yahan execute nahi hui).")
    return {"stl": stl_bytes, "dxf": dxf, "vba": vba, "mesh": mesh, "holes": holes, "log": log}
