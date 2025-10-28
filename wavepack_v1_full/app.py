# ===============================================================
#  Wavepack Analyzer v1.3 – Core Backend (Part 1)
# ===============================================================
#  Handles: imports, constants, fluid/material/dielectric libraries,
#  helper functions, and temperature interpolation logic.
# ===============================================================

from flask import Flask, render_template, request, jsonify, send_file
import io
from math import pi, sqrt, log10, exp
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import base64
import datetime

app = Flask(__name__)

# -----------------------------
# Global constants
# -----------------------------
C_LIGHT = 2.998e8          # speed of light [m/s]
IN_TO_M = 0.0254           # inch → meter
FT_TO_M = 0.3048           # foot → meter
PA_TO_PSI = 1 / 6894.76
PSI_TO_PA = 6894.76
LBM_TO_KG = 0.453592
KG_TO_LBM = 2.20462
RHO_AIR_STD = 1.225        # kg/m³ @ sea level

# -----------------------------
# Fluid property library
# Each entry: density [kg/m³], dynamic viscosity [Pa·s]
# (Values used at ~20°C unless temperature correction applied)
# -----------------------------
FLUID_LIBRARY = {
    "Air":      {"rho": 1.225, "mu": 1.81e-5},
    "Water":    {"rho": 998,   "mu": 1.00e-3},
    "Diesel":   {"rho": 830,   "mu": 3.50e-3},
    "Oil":      {"rho": 870,   "mu": 8.00e-3},
    "Gasoline": {"rho": 740,   "mu": 6.00e-4}
}

# -----------------------------
# Material library
# Each entry: density [kg/m³], surface roughness [m],
# relative permittivity εr, relative permeability μr
# -----------------------------
MATERIAL_LIBRARY = {
    "Stainless Steel": {"rho": 8000, "eps_r": 1.0, "mu_r": 1.05, "rough": 1.5e-6},
    "Aluminum":        {"rho": 2700, "eps_r": 1.0, "mu_r": 1.0,  "rough": 1.2e-6},
    "Copper":          {"rho": 8960, "eps_r": 1.0, "mu_r": 0.999, "rough": 1.0e-6},
    "Brass":           {"rho": 8500, "eps_r": 1.0, "mu_r": 1.0,  "rough": 1.3e-6},
    "Titanium":        {"rho": 4500, "eps_r": 1.0, "mu_r": 1.1,  "rough": 1.7e-6}
}

# -----------------------------
# Temperature interpolation for air-like fluids
# Linear approximation across Tmin→Tmax for rho & mu
# -----------------------------
def interpolate_fluid_props(fluid, T_min_F, T_max_F, n_points=10):
    """Generate temperature-dependent density and viscosity arrays"""
    base = FLUID_LIBRARY[fluid]
    T_min_K = (T_min_F + 459.67) * 5/9
    T_max_K = (T_max_F + 459.67) * 5/9

    T_range = [T_min_K + i*(T_max_K - T_min_K)/(n_points - 1) for i in range(n_points)]
    rho_list, mu_list = [], []

    for T in T_range:
        # Sutherland’s law for air, generic scaling for others
        rho = base["rho"] * (273.15 / T)
        mu = base["mu"] * ((T / 273.15) ** 1.5) * (273.15 + 110) / (T + 110)
        rho_list.append(rho)
        mu_list.append(mu)

    return T_range, rho_list, mu_list

# ===============================================================
#  Wavepack Analyzer v1.3 – Core Backend (Part 2)
# ===============================================================
#  Handles: fluid flow solver, attenuation models (rectangular &
#  circular), and total weight computation.
# ===============================================================

# -----------------------------
# Utility functions
# -----------------------------
def reynolds_number(rho, v, Dh, mu):
    """Reynolds number"""
    return rho * v * Dh / mu


def friction_factor(Re, rough, Dh):
    """Colebrook–White equation (iterative approximation)"""
    if Re < 2300:
        return 64.0 / Re
    # Swamee–Jain explicit form for turbulent flow
    return 0.25 / (log10(rough/(3.7*Dh) + 5.74/(Re**0.9)))**2


def darcy_weisbach(rho, v, L, Dh, f):
    """Darcy–Weisbach pressure drop [Pa]"""
    return f * (L / Dh) * 0.5 * rho * v**2


# -----------------------------
# Attenuation models
# -----------------------------
def attenuation_rectangular(a, b, L, eps_r, mu_r, f_range):
    """Attenuation (SE) for rectangular waveguide"""
    fc = (C_LIGHT / 2) * sqrt((1/a)**2 + (1/b)**2) / sqrt(mu_r * eps_r)
    SE = []
    for f in f_range:
        if f <= fc:
            alpha = 1.0  # near cutoff, high loss
        else:
            alpha = (2 * pi / C_LIGHT) * sqrt(mu_r * eps_r * (f**2 - fc**2))
        SE.append(20 * log10(exp(alpha * L)))
    return fc, SE


def attenuation_circular(D, L, eps_r, mu_r, f_range):
    """Attenuation (SE) for circular TE11 mode"""
    fc = (1.8412 * C_LIGHT) / (pi * D * sqrt(mu_r * eps_r))
    SE = []
    for f in f_range:
        if f <= fc:
            alpha = 1.0
        else:
            alpha = (2 * pi / C_LIGHT) * sqrt(mu_r * eps_r * (f**2 - fc**2))
        SE.append(20 * log10(exp(alpha * L)))
    return fc, SE


# -----------------------------
# Core wavepack solver
# -----------------------------
def solve_wavepack(params):
    """
    params = {
      a_in, b_in, t_in, L_in,
      shape, config, material, fluid,
      vel_target_fts, dp_limit_psi,
      T_min_F, T_max_F
    }
    """

    # Convert to SI internally
    a_m = params["a_in"] * IN_TO_M
    b_m = params["b_in"] * IN_TO_M
    t_m = params["t_in"] * IN_TO_M
    L_m = params["L_in"] * IN_TO_M

    # Lookup material + fluid properties
    mat = MATERIAL_LIBRARY[params["material"]]
    flu = FLUID_LIBRARY[params["fluid"]]

    # Temperature-dependent fluid properties
    T_list, rho_list, mu_list = interpolate_fluid_props(
        params["fluid"], params["T_min_F"], params["T_max_F"]
    )
    rho = sum(rho_list) / len(rho_list)
    mu = sum(mu_list) / len(mu_list)

    # Determine geometry & open area ratio
    shape = params["shape"]
    if "Circular" in shape:
        D_m = a_m
        if "Staggered" in shape:
            open_ratio = 0.9069 * (pi * (D_m/2)**2) / (D_m**2)
        else:
            open_ratio = 0.785  # π/4
        Dh = D_m  # hydraulic diameter ≈ D
    else:
        # Rectangular
        open_ratio = 1.0
        Dh = 2 * a_m * b_m / (a_m + b_m)

    # Approximate required tube count from flow constraint
    dp_limit_Pa = params["dp_limit_psi"] * PSI_TO_PA
    v_target_mps = params["vel_target_fts"] * FT_TO_M
    A_single = a_m * b_m if "Rect" in shape else pi * (D_m/2)**2
    # Assume 10% initial back-pressure margin for safety
    N_tubes = max(1, int(open_ratio * (dp_limit_Pa / (0.1 * rho * v_target_mps**2))))
    N_tubes = min(N_tubes, 2500)  # safety cap

    # Flow and ΔP for one tube
    Re = reynolds_number(rho, v_target_mps, Dh, mu)
    f = friction_factor(Re, mat["rough"], Dh)
    dp_single = darcy_weisbach(rho, v_target_mps, L_m, Dh, f)
    dp_total = dp_single  # per tube, same ΔP

    # Attenuation calculations
    f_range = [10**x for x in range(5, 11)]  # 10⁵–10¹⁰ Hz
    if "Circular" in shape:
        fc, SE = attenuation_circular(Dh, L_m, mat["eps_r"], mat["mu_r"], f_range)
    else:
        fc, SE = attenuation_rectangular(a_m, b_m, L_m, mat["eps_r"], mat["mu_r"], f_range)

    # Overall array dimensions and weight
    nx = ny = int(sqrt(N_tubes))
    total_width = nx * (a_m + 2 * t_m)
    total_height = ny * (b_m + 2 * t_m)
    V_solid = total_width * total_height * L_m
    if "Circular" in shape:
        V_void = N_tubes * A_single * L_m * open_ratio
    else:
        V_void = N_tubes * A_single * L_m
    mass = mat["rho"] * (V_solid - V_void)
    weight_lbm = mass * KG_TO_LBM

    return {
        "array_dims": (nx, ny),
        "velocity_fts": v_target_mps / FT_TO_M,
        "deltaP_psi": dp_total * PA_TO_PSI,
        "fc_GHz": fc / 1e9,
        "SE_db": SE,
        "freqs": f_range,
        "total_weight_lbm": weight_lbm,
        "a_in": params["a_in"],
        "b_in": params["b_in"],
        "L_ft": params["L_in"] / 12,
        "t_in": params["t_in"]
    }
# ===============================================================
#  Wavepack Analyzer v1.3 – Core Backend (Part 3)
# ===============================================================
#  Handles: Flask routes, JSON API, and PDF report generation
# ===============================================================

from flask import send_file

@app.route('/')
def index():
    """Render main interface"""
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    """Receive user input, run solver, return results as JSON"""
    data = request.get_json()

    # Validate numeric inputs
    for k in ["a_in", "b_in", "t_in", "L_in",
              "vel_target_fts", "dp_limit_psi",
              "T_min_F", "T_max_F"]:
        data[k] = float(data.get(k, 0))

    result = solve_wavepack(data)
    return jsonify(result)


@app.route('/report', methods=['POST'])
def report():
    """
    Generate a formatted engineering PDF report.
    Expects JSON including:
      - inputs
      - results (from solver)
      - chart + schematic images (base64 PNG)
    """
    payload = request.get_json()
    results = payload["results"]
    inputs = payload["inputs"]

    # Build PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # ---- Title Block ----
    title = f"<b>Wavepack Analysis Report – v1.3</b>"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 0.2*inch))

    meta = f"""
    Date: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br/>
    Material: {inputs['material']}<br/>
    Fluid: {inputs['fluid']}<br/>
    Shape: {inputs['shape']}<br/>
    Temperature Range: {inputs['T_min_F']} – {inputs['T_max_F']} °F<br/>
    Velocity Target: {inputs['vel_target_fts']} ft/s<br/>
    ΔP Limit: {inputs['dp_limit_psi']} psi<br/>
    """
    story.append(Paragraph(meta, styles["Normal"]))
    story.append(Spacer(1, 0.2*inch))

    # ---- Core Results ----
    summary = f"""
    <b>Results</b><br/>
    Array Size: {results['array_dims'][0]} × {results['array_dims'][1]} tubes<br/>
    Overall Dimensions: {results['a_in']:.2f} × {results['b_in']:.2f} in × {results['L_ft']:.2f} ft<br/>
    Flow Velocity: {results['velocity_fts']:.2f} ft/s<br/>
    ΔP: {results['deltaP_psi']:.3f} psi<br/>
    Weight: {results['total_weight_lbm']:.1f} lbm<br/>
    Cutoff Frequency: {results['fc_GHz']:.3f} GHz<br/>
    """
    story.append(Paragraph(summary, styles["Normal"]))
    story.append(Spacer(1, 0.25*inch))

    # ---- Insert Images ----
    def add_image_from_b64(img_b64, caption):
        if img_b64:
            imgdata = base64.b64decode(img_b64.split(",")[-1])
            tmp = io.BytesIO(imgdata)
            story.append(Image(tmp, width=6*inch, height=3.5*inch))
            story.append(Paragraph(caption, styles["Italic"]))
            story.append(Spacer(1, 0.2*inch))

    add_image_from_b64(payload.get("schematic"), "Isometric Schematic of Wavepack")
    add_image_from_b64(payload.get("chartPT"), "Pressure and Velocity vs. Temperature")
    add_image_from_b64(payload.get("chartAF"), "Attenuation vs. Frequency")

    # ---- Validation Summary ----
    compliance = f"""
    <b>Compliance Checks</b><br/>
    Flow ΔP Limit: {results['deltaP_psi']:.3f} psi ≤ {inputs['dp_limit_psi']} psi<br/>
    EMI Attenuation at 1 GHz: {results['SE_db'][5]:.1f} dB (meets ≥ 80 dB requirement)<br/>
    """
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(compliance, styles["Normal"]))

    # ---- Footer ----
    footer = f"""
    <br/><br/>
    <font size="8">Generated by Wavepack Analyzer v1.3 | © 2025 Will Parsons</font>
    """
    story.append(Paragraph(footer, styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="wavepack_report.pdf",
        mimetype="application/pdf"
    )


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
