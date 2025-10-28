// ===============================================================
//  Wavepack Analyzer v1.3 Frontend Script
// ===============================================================
//  Handles: inputs, API requests, drawing, charts, unit toggle,
//  and report export.
// ===============================================================

let useSI = false;
let currentResult = null;

// -----------------------------
// Tab switching
// -----------------------------
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.id === 'tab-inputs' ? 'inputs' : 'outputs').classList.add('active');
  });
});

// -----------------------------
// Unit toggle
// -----------------------------
const unitToggle = document.getElementById('unitToggle');
unitToggle.addEventListener('change', () => {
  useSI = unitToggle.checked;
  updateUnitsDisplay();
});

function updateUnitsDisplay() {
  const velLabel = document.querySelector('label[for="vel_target_fts"]') || document.querySelector('label:has(#vel_target_fts)');
  const dpLabel = document.querySelector('label[for="dp_limit_psi"]') || document.querySelector('label:has(#dp_limit_psi)');
  if (useSI) {
    velLabel.childNodes[0].textContent = "Velocity Target (m/s) ";
    dpLabel.childNodes[0].textContent = "ΔP Limit (kPa) ";
  } else {
    velLabel.childNodes[0].textContent = "Velocity Target (ft/s) ";
    dpLabel.childNodes[0].textContent = "ΔP Limit (psi) ";
  }
}

// -----------------------------
// Run analysis
// -----------------------------
document.getElementById('analyzeBtn').addEventListener('click', runAnalysis);

async function runAnalysis() {
  const params = {
    a_in: parseFloat(document.getElementById('a_in').value),
    b_in: parseFloat(document.getElementById('b_in').value),
    t_in: parseFloat(document.getElementById('t_in').value),
    L_in: parseFloat(document.getElementById('L_in').value),
    shape: document.getElementById('shape').value,
    config: "default",
    material: document.getElementById('material').value,
    fluid: document.getElementById('fluid').value,
    vel_target_fts: parseFloat(document.getElementById('vel_target_fts').value),
    dp_limit_psi: parseFloat(document.getElementById('dp_limit_psi').value),
    T_min_F: parseFloat(document.getElementById('T_min_F').value),
    T_max_F: parseFloat(document.getElementById('T_max_F').value)
  };

  const res = await fetch('/analyze', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(params)
  });
  const result = await res.json();
  currentResult = result;
  updateVisual(result);
  updateInfo(result);
  updateCharts(result);
  document.getElementById('tab-outputs').click();
}

// -----------------------------
// Update info panel
// -----------------------------
function updateInfo(result) {
  document.getElementById('c_array').textContent = `${result.array_dims[0]}×${result.array_dims[1]}`;
  document.getElementById('c_dims').textContent = `${result.a_in.toFixed(2)}×${result.b_in.toFixed(2)} in × ${result.L_ft.toFixed(2)} ft`;
  document.getElementById('c_v').textContent = result.velocity_fts.toFixed(2);
  document.getElementById('c_dp').textContent = result.deltaP_psi.toFixed(3);
  document.getElementById('c_w').textContent = result.total_weight_lbm.toFixed(1);
  document.getElementById('c_fc').textContent = result.fc_GHz.toFixed(3);
}

// -----------------------------
// Drawing
// -----------------------------
function updateVisual(result) {
  const svg = document.getElementById("schematic");
  const group = document.getElementById("tubeArray");
  group.innerHTML = "";
  const nx = result.array_dims[0];
  const ny = result.array_dims[1];
  const a = result.a_in;
  const b = result.b_in;
  const t = result.t_in;
  const shape = document.getElementById('shape').value;

  const maxRender = 50;
  const drawNx = Math.min(nx, maxRender);
  const drawNy = Math.min(ny, maxRender);
  const scale = 12;
  const offsetX = 250;
  const offsetY = 180;

  // material color gradient
  const defs = svg.querySelector("defs") || svg.insertBefore(document.createElementNS("http://www.w3.org/2000/svg","defs"), svg.firstChild);
  defs.innerHTML = `<linearGradient id="tubeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#ccc"/><stop offset="100%" stop-color="#333"/></linearGradient>`;

  const isCircular = shape.includes("Circular");
  for (let i = 0; i < drawNx; i++) {
    for (let j = 0; j < drawNy; j++) {
      const isoX = offsetX + (i - nx/2) * (a + 2*t) * scale - (j * 0.5 * scale);
      const isoY = offsetY + (j - ny/2) * (b + 2*t) * scale + (j * 0.25 * scale);

      if (isCircular) {
        const D = a * scale;
        const cx = isoX + D/2;
        const cy = isoY + D/2;
        const circ = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circ.setAttribute("cx", cx);
        circ.setAttribute("cy", cy);
        circ.setAttribute("r", D/2);
        circ.setAttribute("fill", "#0b1220");
        circ.setAttribute("stroke", "url(#tubeGrad)");
        circ.setAttribute("stroke-width", 2);
        group.appendChild(circ);
      } else {
        const outer = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        outer.setAttribute("x", isoX);
        outer.setAttribute("y", isoY);
        outer.setAttribute("width", a*scale + 2*t*scale);
        outer.setAttribute("height", b*scale + 2*t*scale);
        outer.setAttribute("fill", "url(#tubeGrad)");
        outer.setAttribute("stroke", "#111");
        group.appendChild(outer);

        const inner = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        inner.setAttribute("x", isoX + t*scale);
        inner.setAttribute("y", isoY + t*scale);
        inner.setAttribute("width", a*scale);
        inner.setAttribute("height", b*scale);
        inner.setAttribute("fill", "#0b1220");
        group.appendChild(inner);
      }
    }
  }
}

// -----------------------------
// Charts
// -----------------------------
let chartPT = null;
let chartAF = null;

function updateCharts(result) {
  const ctxPT = document.getElementById("chartPT").getContext("2d");
  const ctxAF = document.getElementById("chartAF").getContext("2d");

  const Tmin = parseFloat(document.getElementById('T_min_F').value);
  const Tmax = parseFloat(document.getElementById('T_max_F').value);
  const temps = [];
  const pVals = [];
  const vVals = [];

  for (let T = Tmin; T <= Tmax; T += 10) {
    const rho = 0.075 * (460 / (T + 460));
    const v = result.velocity_fts * (0.075 / rho);
    const dp = result.deltaP_psi * (rho / 0.075);
    temps.push(T);
    vVals.push(v);
    pVals.push(dp);
  }

  if (chartPT) chartPT.destroy();
  chartPT = new Chart(ctxPT, {
    type: "line",
    data: {
      labels: temps,
      datasets: [
        {label: "Velocity (ft/s)", data: vVals, yAxisID: "V", borderColor: "#39d0ff"},
        {label: "ΔP (psi)", data: pVals, yAxisID: "P", borderColor: "#ff9b39"}
      ]
    },
    options: {
      responsive: true,
      scales: {
        x: {title: {display: true, text: "Temperature (°F)"}, grid: {color: "#223"}},
        V: {position: "left", title: {display: true, text: "Velocity (ft/s)"}, grid: {color: "#223"}},
        P: {position: "right", title: {display: true, text: "ΔP (psi)"}, grid: {drawOnChartArea: false}}
      },
      plugins: {legend: {labels: {color: "#ccc"}}}
    }
  });

  const freqs = result.freqs.map(f => f/1e6);
  const SE = result.SE_db;
  if (chartAF) chartAF.destroy();
  chartAF = new Chart(ctxAF, {
    type: "line",
    data: {
      labels: freqs,
      datasets: [{label: "Shielding Effectiveness (dB)", data: SE, borderColor: "#39ff88"}]
    },
    options: {
      responsive: true,
      scales: {
        x: {
          type: "logarithmic",
          title: {display: true, text: "Frequency (MHz)"},
          grid: {color: "#223"},
          ticks: {callback: val => val.toLocaleString()}
        },
        y: {title: {display: true, text: "Attenuation (dB)"}, grid: {color: "#223"}}
      },
      plugins: {legend: {labels: {color: "#ccc"}}}
    }
  });
}

// -----------------------------
// Generate report
// -----------------------------
document.getElementById('reportBtn').addEventListener('click', generateReport);

async function generateReport() {
  if (!currentResult) return;

  const schematic = document.getElementById("schematic");
  const chartPTImg = document.getElementById("chartPT").toDataURL("image/png");
  const chartAFImg = document.getElementById("chartAF").toDataURL("image/png");

  const svgData = new XMLSerializer().serializeToString(schematic);
  const svgBase64 = "data:image/svg+xml;base64," + btoa(svgData);

  const payload = {
    inputs: {
      shape: document.getElementById("shape").value,
      material: document.getElementById("material").value,
      fluid: document.getElementById("fluid").value,
      dp_limit_psi: parseFloat(document.getElementById("dp_limit_psi").value),
      vel_target_fts: parseFloat(document.getElementById("vel_target_fts").value),
      T_min_F: parseFloat(document.getElementById("T_min_F").value),
      T_max_F: parseFloat(document.getElementById("T_max_F").value)
    },
    results: currentResult,
    schematic: svgBase64,
    chartPT: chartPTImg,
    chartAF: chartAFImg
  };

  const res = await fetch('/report', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = "wavepack_report.pdf";
  a.click();
  window.URL.revokeObjectURL(url);
}
