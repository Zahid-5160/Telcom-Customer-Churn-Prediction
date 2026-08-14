/**
 * Retain dashboard front-end. Plain ES modules, no framework and no build step -
 * the browser loads this file directly.
 */

import { PALETTE, columnChart, barChart, stackedChart, donutChart, lineChart, gauge } from './charts.js';

const $ = (id) => document.getElementById(id);
const api = (path, options) => fetch(path, options).then(async (response) => {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
});

/* ------------------------------------------------------------------ */
/* rupee formatting                                                    */
/* ------------------------------------------------------------------ */

/**
 * Indian digit grouping: 12,50,000 rather than 1,250,000. Everyone reading this
 * dashboard groups numbers in lakh and crore, so the Western grouping would make
 * every salary momentarily unreadable.
 */
const rupees = (value) => `₹${Math.round(Number(value) || 0).toLocaleString('en-IN')}`;

/** Compact rupees for stat tiles, using lakh and crore. */
function rupeesShort(value) {
  const n = Math.round(Number(value) || 0);
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(n % 1e7 === 0 ? 0 : 2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(n % 1e5 === 0 ? 0 : 1)} L`;
  return rupees(n);
}

const pct = (v) => `${(v * 100).toFixed(0)}%`;
const pct1 = (v) => `${(v * 100).toFixed(1)}%`;

const state = { insights: null, model: null, schema: null, batch: null };

/* ------------------------------------------------------------------ */
/* chrome                                                              */
/* ------------------------------------------------------------------ */

let toastTimer;
function toast(message, isError = false) {
  const node = $('toast');
  node.textContent = message;
  node.classList.toggle('is-error', isError);
  node.classList.add('is-visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('is-visible'), 3800);
}

function table(host, columns, rows) {
  const head = columns.map((c) => `<th>${c.label}</th>`).join('');
  const body = rows.map((row) => `<tr>${columns.map((c) => `<td>${c.get(row)}</td>`).join('')}</tr>`).join('');
  // Wide tables scroll inside their own container, never the page.
  host.innerHTML = `<div class="scroll-x"><table class="data-table">
    <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function legend(host, items) {
  host.innerHTML = items.map((i) => `
    <span class="legend-item">
      <span class="legend-swatch" style="background:${i.color}"></span>${i.label}
    </span>`).join('');
}

/* ------------------------------------------------------------------ */
/* workforce dashboard                                                 */
/* ------------------------------------------------------------------ */

function renderKpis(kpis) {
  const tiles = [
    { label: 'Employees analysed', value: kpis.employees, delta: 'the full sample' },
    { label: 'People lost', value: kpis.left, delta: `${pct1(kpis.attrition_rate)} of the sample`, accent: true },
    {
      label: 'Cost to replace them',
      value: rupeesShort(kpis.replacement_cost),
      delta: `at ${kpis.replacement_cost_months} months' salary each`,
    },
    {
      label: 'Average service before leaving',
      value: `${kpis.avg_tenure_left} yrs`,
      delta: `those staying average ${kpis.avg_tenure_stayed} yrs`,
    },
  ];
  $('kpiRow').innerHTML = tiles.map((t) => `
    <div class="stat${t.accent ? ' accent' : ''}">
      <div class="label">${t.label}</div>
      <div class="value">${t.value}</div>
      <div class="delta">${t.delta}</div>
    </div>`).join('');
}

function renderDashboard(data) {
  const { kpis, breakdowns } = data;

  $('heroRate').textContent = pct1(kpis.attrition_rate);
  $('heroFoot').textContent =
    `${kpis.left} of ${kpis.employees} people left, costing about ${rupeesShort(kpis.replacement_cost)} to replace.`;

  renderKpis(kpis);

  donutChart($('chartDonut'), {
    segments: [
      { label: 'Stayed', value: kpis.stayed, color: PALETTE.series1 },
      { label: 'Left', value: kpis.left, color: PALETTE.series2 },
    ],
    centerValue: kpis.employees,
    centerLabel: 'employees',
  });
  legend($('donutLegend'), [
    { label: `Stayed — ${kpis.stayed}`, color: PALETTE.series1 },
    { label: `Left — ${kpis.left}`, color: PALETTE.series2 },
  ]);

  // Single-series leaving-rate charts: one colour, no legend box needed.
  const rateChart = (hostId, tableId, block, keepOrder = true) => {
    const rows = block.data;
    const points = (keepOrder ? rows : [...rows].sort((a, b) => b.attrition_rate - a.attrition_rate))
      .map((r) => ({
        label: r.category,
        value: r.attrition_rate,
        note: `${r.left} of ${r.total} people · avg ${rupees(r.avg_salary)}/month`,
      }));
    columnChart($(hostId), { data: points, label: 'Left', valueFormat: pct });
    if (tableId) {
      table($(tableId), [
        { label: 'Group', get: (r) => r.category },
        { label: 'Employees', get: (r) => r.total },
        { label: 'Left', get: (r) => r.left },
        { label: 'Leaving rate', get: (r) => pct1(r.attrition_rate) },
        { label: 'Avg salary', get: (r) => `${rupees(r.avg_salary)}/mo` },
      ], rows);
    }
  };

  rateChart('chartOvertime', 'tableOvertime', breakdowns.OverTime);
  rateChart('chartLevel', 'tableLevel', breakdowns.JobLevel);
  rateChart('chartTenure', 'tableTenure', breakdowns.TenureBand);
  rateChart('chartGender', null, breakdowns.Gender, false);

  const hist = data.tenure_histogram.map((h) => ({
    label: h.label, stayed: h.stayed, left: h.left,
  }));
  stackedChart($('chartTenureHist'), {
    data: hist,
    series: [
      { key: 'stayed', label: 'Stayed', color: PALETTE.series1 },
      { key: 'left', label: 'Left', color: PALETTE.series2 },
    ],
  });
  legend($('histLegend'), [
    { label: 'Stayed', color: PALETTE.series1 },
    { label: 'Left', color: PALETTE.series2 },
  ]);
  table($('tableHist'), [
    { label: 'Years of service', get: (r) => r.label },
    { label: 'Employees', get: (r) => r.total },
    { label: 'Stayed', get: (r) => r.stayed },
    { label: 'Left', get: (r) => r.left },
    { label: 'Leaving rate', get: (r) => pct1(r.attrition_rate) },
  ], data.tenure_histogram);

  barChart($('chartSegments'), {
    data: data.risk_segments.map((s) => ({
      label: s.segment,
      value: s.attrition_rate,
      note: `${s.employees} people · ${s.lift}x the average rate`,
    })),
    label: 'Leaving rate',
    valueFormat: pct,
    labelWidth: 200,
  });
  table($('tableSegments'), [
    { label: 'Group', get: (r) => r.segment },
    { label: 'Employees', get: (r) => r.employees },
    { label: 'Leaving rate', get: (r) => pct1(r.attrition_rate) },
    { label: 'vs average', get: (r) => `${r.lift}x` },
  ], data.risk_segments);

  $('headlines').innerHTML = data.headlines.map((h) => `
    <div class="headline"><h4>${h.title}</h4><p>${h.detail}</p></div>`).join('');
}

/* ------------------------------------------------------------------ */
/* assessment form                                                     */
/* ------------------------------------------------------------------ */

const FIELD_LABELS = {
  Department: 'Department', JobRole: 'Role', JobLevel: 'Job level',
  BusinessTravel: 'Business travel', OverTime: 'Works overtime',
  MaritalStatus: 'Marital status', StockOptionLevel: 'Equity grant',
  JobSatisfaction: 'Job satisfaction', EnvironmentSatisfaction: 'Work environment',
  WorkLifeBalance: 'Work-life balance', JobInvolvement: 'Involvement',
  PerformanceRating: 'Performance rating',
  Age: 'Age', MonthlyIncome: 'Monthly salary (₹)', DistanceFromHome: 'Commute (km)',
  PercentSalaryHike: 'Last pay rise (%)', TrainingTimesLastYear: 'Training sessions last year',
  NumCompaniesWorked: 'Previous employers', TotalWorkingYears: 'Total experience (years)',
  YearsAtCompany: 'Years with us', YearsInCurrentRole: 'Years in current role',
  YearsSinceLastPromotion: 'Years since promotion',
  CareerShare: 'Share of career spent here', PromotionGap: 'Promotion gap',
  PayPerLevel: 'Pay for their grade', TenureBand: 'Time here',
};

const GROUPS = {
  groupRole: ['Department', 'JobRole', 'JobLevel', 'BusinessTravel', 'OverTime', 'PerformanceRating'],
  groupPay: [],
  groupExperience: ['JobSatisfaction', 'EnvironmentSatisfaction', 'WorkLifeBalance',
    'JobInvolvement', 'StockOptionLevel'],
  groupBackground: ['MaritalStatus'],
};

const NUMERIC_GROUPS = {
  groupPay: [
    ['MonthlyIncome', 0, 10000000, 500],
    ['PercentSalaryHike', 0, 100, 1],
    ['YearsSinceLastPromotion', 0, 60, 1],
  ],
  groupBackground: [
    ['Age', 18, 75, 1],
    ['DistanceFromHome', 0, 200, 1],
    ['TotalWorkingYears', 0, 60, 1],
    ['NumCompaniesWorked', 0, 20, 1],
    ['YearsAtCompany', 0, 60, 1],
    ['YearsInCurrentRole', 0, 60, 1],
    ['TrainingTimesLastYear', 0, 20, 1],
  ],
};

const DEFAULTS = {
  Department: 'Research and Development', JobRole: 'Research Scientist', JobLevel: 'Entry',
  BusinessTravel: 'Rare', OverTime: 'Yes', MaritalStatus: 'Single',
  StockOptionLevel: 'None', JobSatisfaction: 'Low', EnvironmentSatisfaction: 'Medium',
  WorkLifeBalance: 'High', JobInvolvement: 'High', PerformanceRating: 'Meets expectations',
  Age: 29, MonthlyIncome: 55000, DistanceFromHome: 10, PercentSalaryHike: 12,
  TrainingTimesLastYear: 2, NumCompaniesWorked: 1, TotalWorkingYears: 5,
  YearsAtCompany: 2, YearsInCurrentRole: 2, YearsSinceLastPromotion: 2,
};

function buildForm(schema) {
  for (const [hostId, fields] of Object.entries(GROUPS)) {
    const selects = fields.map((field) => `
      <div class="field">
        <label for="f_${field}">${FIELD_LABELS[field]}</label>
        <select id="f_${field}" name="${field}">
          ${(schema.categorical[field] || []).map((o) => `<option value="${o}">${o}</option>`).join('')}
        </select>
      </div>`).join('');

    const numbers = (NUMERIC_GROUPS[hostId] || []).map(([field, min, max, step]) => `
      <div class="field">
        <label for="f_${field}">${FIELD_LABELS[field]}</label>
        <input type="number" id="f_${field}" name="${field}" min="${min}" max="${max}" step="${step}">
      </div>`).join('');

    $(hostId).innerHTML = selects + numbers;
  }

  fillForm(DEFAULTS);
}

function fillForm(values) {
  Object.entries(values).forEach(([key, value]) => {
    const node = $(`f_${key}`);
    if (node) node.value = value;
  });
}

function readForm() {
  const record = {};
  document.querySelectorAll('#predictForm select, #predictForm input').forEach((node) => {
    record[node.name] = node.type === 'number' ? Number(node.value || 0) : node.value;
  });
  return record;
}

function renderPrediction(result) {
  $('resultEmpty').hidden = true;
  $('resultBody').hidden = false;

  gauge($('gauge'), { value: result.probability, band: result.risk_band, caption: 'chance of leaving' });

  const pill = $('riskPill');
  pill.className = `risk-pill risk-${result.risk_band}`;
  pill.textContent = `${result.risk_band} risk`;
  $('riskAdvice').textContent = result.advice;

  $('costAtRisk').innerHTML = result.will_leave
    ? `<strong>Flagged for a retention conversation.</strong> At ${pct1(result.probability)} risk,
       the expected cost of replacing this person works out at about
       <strong>${rupeesShort(result.cost_at_risk)}</strong>.`
    : `<strong>No action needed today.</strong> This person scores below the
       ${pct(result.threshold)} line the model uses to flag somebody.`;

  const drivers = $('driversList');
  if (result.drivers?.length) {
    $('driversCard').hidden = false;
    const worst = Math.max(...result.drivers.map((d) => Math.abs(d.impact))) || 1;
    drivers.innerHTML = result.drivers.map((d) => {
      const up = d.impact > 0;
      const width = Math.max(6, (Math.abs(d.impact) / worst) * 100);
      const shown = d.field === 'MonthlyIncome' ? rupees(d.value) : d.value;
      const against = d.field === 'MonthlyIncome' ? rupees(d.compared_to) : d.compared_to;
      return `
        <div class="driver-row">
          <div class="driver-bar">
            <i style="width:${width}%; background:${up ? PALETTE.serious : PALETTE.series1}"></i>
          </div>
          <div class="driver-meta">
            <strong>${d.label}: ${shown}</strong>
            <span>${up ? 'raises' : 'lowers'} the risk against a typical employee (${against})</span>
          </div>
          <div class="driver-impact ${up ? 'up' : 'down'}">${up ? '+' : ''}${(d.impact * 100).toFixed(1)} pts</div>
        </div>`;
    }).join('');
  } else {
    $('driversCard').hidden = true;
  }

  const actions = $('actionsList');
  if (result.actions?.length) {
    $('actionsCard').hidden = false;
    actions.innerHTML = result.actions.map((a, i) => {
      const to = a.kind === 'pay' ? `${rupees(a.to)}/month (${a.display})` : a.to;
      const from = a.field === 'MonthlyIncome' ? rupees(a.from) : a.from;
      return `
        <div class="action-row">
          <div class="badge">${i + 1}</div>
          <div class="driver-meta">
            <strong>${a.recommendation}</strong>
            <span>${a.label}: ${from} → ${to} · risk falls to ${pct1(a.new_probability)}</span>
          </div>
          <div class="driver-impact down">−${(a.reduction * 100).toFixed(1)} pts</div>
        </div>`;
    }).join('');
  } else {
    $('actionsCard').hidden = true;
  }
}

/* ------------------------------------------------------------------ */
/* whole-team scoring                                                  */
/* ------------------------------------------------------------------ */

function renderBatch(data) {
  state.batch = data;
  $('btnDownloadResults').hidden = false;
  $('batchSummary').innerHTML = `
    <div class="grid grid-4">
      <div class="stat"><div class="label">People assessed</div><div class="value">${data.count}</div></div>
      <div class="stat accent"><div class="label">Flagged at risk</div><div class="value">${data.flagged}</div>
        <div class="delta">${pct1(data.flagged_share)} of the list</div></div>
      <div class="stat"><div class="label">Replacement cost exposed</div>
        <div class="value">${rupeesShort(data.cost_at_risk)}</div>
        <div class="delta">risk-weighted across everyone</div></div>
      <div class="stat"><div class="label">Alert line</div><div class="value">${pct(data.threshold)}</div>
        <div class="delta">scores above this are flagged</div></div>
    </div>`;

  table($('batchResults'), [
    { label: 'Employee', get: (r) => r.EmployeeID },
    { label: 'Role', get: (r) => r.JobRole ?? '—' },
    { label: 'Years', get: (r) => r.YearsAtCompany ?? '—' },
    { label: 'Salary', get: (r) => (r.MonthlyIncome != null ? `${rupees(r.MonthlyIncome)}/mo` : '—') },
    { label: 'Risk', get: (r) => `${r.percent}%` },
    { label: 'Band', get: (r) => `<span class="risk-pill risk-${r.risk_band}">${r.risk_band}</span>` },
  ], data.results);
}

function downloadBatch() {
  if (!state.batch) return;
  const header = 'EmployeeID,JobRole,Department,YearsAtCompany,MonthlyIncome,probability,percent,risk_band,will_leave';
  const lines = state.batch.results.map((r) => [
    r.EmployeeID, `"${r.JobRole ?? ''}"`, `"${r.Department ?? ''}"`, r.YearsAtCompany,
    r.MonthlyIncome, r.probability, r.percent, r.risk_band, r.will_leave,
  ].join(','));
  const blob = new Blob([`${header}\n${lines.join('\n')}`], { type: 'text/csv' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'retention-risk.csv';
  link.click();
  URL.revokeObjectURL(link.href);
}

async function uploadCsv(file) {
  if (!file) return;
  const body = new FormData();
  body.append('file', file);
  try {
    renderBatch(await api('/api/predict/csv', { method: 'POST', body }));
    toast(`Assessed ${state.batch.count} employees.`);
    loadHistory();
  } catch (error) {
    toast(error.message, true);
  }
}

/* ------------------------------------------------------------------ */
/* model card                                                          */
/* ------------------------------------------------------------------ */

function renderModel(model) {
  const s = model.scores;
  $('modelCaveat').innerHTML = `
    <strong>${model.selected_model}</strong> won on ${model.evaluation.strategy}.
    ${model.evaluation.explanation}<br><br>
    <strong>Read these numbers as a demonstration, not a benchmark.</strong>
    ${model.evaluation.caveat}`;

  const tiles = [
    { label: 'Ranking quality (ROC-AUC)', value: s.roc_auc.toFixed(3), delta: '1.0 is perfect, 0.5 is guessing', accent: true },
    { label: 'Leavers correctly caught', value: pct(s.recall), delta: 'of everyone who actually left' },
    { label: 'Alerts that were right', value: pct(s.precision), delta: 'of the people it flagged' },
    { label: 'Overall accuracy', value: pct(s.accuracy), delta: 'correct calls of any kind' },
  ];
  $('modelScores').innerHTML = tiles.map((t) => `
    <div class="stat${t.accent ? ' accent' : ''}">
      <div class="label">${t.label}</div><div class="value">${t.value}</div><div class="delta">${t.delta}</div>
    </div>`).join('');

  lineChart($('chartRoc'), {
    points: model.roc_curve,
    xLabel: 'Stayers wrongly flagged',
    yLabel: 'Leavers correctly caught',
  });

  const m = model.confusion_matrix;
  $('matrix').innerHTML = `
    <div class="corner"></div><div class="head">Predicted to stay</div><div class="head">Predicted to leave</div>
    <div class="head" style="display:grid;place-items:center;">Actually<br>stayed</div>
    <div class="cell hit"><strong>${m.true_negative}</strong><span>correctly left alone</span></div>
    <div class="cell miss"><strong>${m.false_positive}</strong><span>false alarm</span></div>
    <div class="head" style="display:grid;place-items:center;">Actually<br>left</div>
    <div class="cell miss"><strong>${m.false_negative}</strong><span>missed leaver</span></div>
    <div class="cell hit"><strong>${m.true_positive}</strong><span>correctly caught</span></div>`;

  $('matrixNote').innerHTML = `
    The two red boxes are the mistakes. A <strong>false alarm</strong> costs one unnecessary
    conversation; a <strong>missed leaver</strong> costs a whole person and their replacement.
    That is why the alert line sits at ${pct(model.decision_threshold)} rather than the textbook
    50% — catching leavers matters more here than avoiding an awkward chat.`;

  barChart($('chartImportance'), {
    data: model.feature_importance.map((f) => ({
      label: FIELD_LABELS[f.feature] || f.feature,
      value: f.importance,
      note: 'Accuracy lost when this detail is scrambled',
    })),
    label: 'Accuracy lost when scrambled',
    valueFormat: (v) => v.toFixed(3),
    labelWidth: 175,
  });
  table($('tableImportance'), [
    { label: 'Detail', get: (r) => FIELD_LABELS[r.feature] || r.feature },
    { label: 'Importance', get: (r) => r.importance.toFixed(4) },
    { label: 'Variation', get: (r) => `± ${r.std.toFixed(4)}` },
  ], model.feature_importance);

  $('leaderboard').innerHTML = model.leaderboard
    .slice().sort((a, b) => b.roc_auc - a.roc_auc)
    .map((row) => `
      <div class="driver-row">
        <div class="driver-meta">
          <strong>${row.label} ${row.key === model.selected_key ? '<span class="badge-soft win">selected</span>' : ''}</strong>
          <span>${row.rationale}</span>
        </div>
        <div class="driver-impact">${row.roc_auc.toFixed(3)}</div>
      </div>`).join('');

  $('footerMeta').textContent =
    `${model.selected_model} · trained ${model.generated_at} · ${model.rows_total} employees`;
}

/* ------------------------------------------------------------------ */
/* history                                                             */
/* ------------------------------------------------------------------ */

async function loadHistory() {
  try {
    const data = await api('/api/history?limit=25');
    const s = data.summary;
    $('historySummary').innerHTML = `
      <div class="stat"><div class="label">Assessments made</div><div class="value">${s.total}</div></div>
      <div class="stat accent"><div class="label">Flagged at risk</div><div class="value">${s.flagged}</div></div>
      <div class="stat"><div class="label">Average risk</div><div class="value">${pct1(s.avg_probability)}</div></div>
      <div class="stat"><div class="label">Salary exposed</div>
        <div class="value">${rupeesShort(s.salary_at_risk)}</div>
        <div class="delta">per month, risk-weighted</div></div>`;

    if (!data.items.length) {
      $('historyTable').innerHTML = '<p class="result-empty">Nothing assessed yet.</p>';
      return;
    }
    table($('historyTable'), [
      { label: 'When', get: (r) => new Date(r.created_at).toLocaleString('en-IN') },
      { label: 'Employee', get: (r) => r.employee_ref || '—' },
      { label: 'Source', get: (r) => r.source },
      { label: 'Role', get: (r) => r.job_role || '—' },
      { label: 'Years', get: (r) => r.years_here },
      { label: 'Salary', get: (r) => `${rupees(r.salary)}/mo` },
      { label: 'Risk', get: (r) => pct1(r.probability) },
      { label: 'Band', get: (r) => `<span class="risk-pill risk-${r.risk_band}">${r.risk_band}</span>` },
    ], data.items);
  } catch (error) {
    $('historyTable').innerHTML = `<p class="result-empty">${error.message}</p>`;
  }
}

/* ------------------------------------------------------------------ */
/* wiring                                                              */
/* ------------------------------------------------------------------ */

/** Strip the fields the form does not own before loading a real employee. */
function employeeToForm(employee) {
  const record = { ...employee };
  ['Attrition', 'EmployeeID', 'Gender', 'CareerShare', 'PromotionGap', 'PayPerLevel', 'TenureBand']
    .forEach((key) => delete record[key]);
  return record;
}

function wireEvents() {
  document.addEventListener('click', (event) => {
    const toggle = event.target.closest('.table-toggle');
    if (!toggle) return;
    const target = $(toggle.dataset.table);
    target.hidden = !target.hidden;
    toggle.textContent = target.hidden ? 'Show data table' : 'Hide data table';
  });

  $('predictForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('btnPredict');
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> Assessing…';
    try {
      renderPrediction(await api('/api/predict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(readForm()),
      }));
      loadHistory();
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = 'Assess retention risk';
    }
  });

  $('employeePicker').addEventListener('change', (event) => {
    if (!event.target.value) { fillForm(DEFAULTS); return; }
    const person = state.insights.employees.find((e) => e.EmployeeID === event.target.value);
    if (person) {
      fillForm(employeeToForm(person));
      toast(`Loaded ${person.EmployeeID} — this person actually ${person.Attrition === 'Yes' ? 'left' : 'stayed'}.`);
    }
  });

  $('btnRandom').addEventListener('click', () => {
    const list = state.insights.employees;
    const pick = list[Math.floor(Math.random() * list.length)];
    $('employeePicker').value = pick.EmployeeID;
    $('employeePicker').dispatchEvent(new Event('change'));
  });

  $('btnReset').addEventListener('click', () => {
    $('employeePicker').value = '';
    fillForm(DEFAULTS);
    $('resultBody').hidden = true;
    $('resultEmpty').hidden = false;
    $('driversCard').hidden = true;
    $('actionsCard').hidden = true;
  });

  const dropzone = $('dropzone');
  const fileInput = $('fileInput');
  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });
  fileInput.addEventListener('change', () => uploadCsv(fileInput.files[0]));
  ['dragenter', 'dragover'].forEach((type) => dropzone.addEventListener(type, (e) => {
    e.preventDefault(); dropzone.classList.add('is-over');
  }));
  ['dragleave', 'drop'].forEach((type) => dropzone.addEventListener(type, (e) => {
    e.preventDefault(); dropzone.classList.remove('is-over');
  }));
  dropzone.addEventListener('drop', (e) => uploadCsv(e.dataTransfer.files[0]));

  $('btnScoreSample').addEventListener('click', async () => {
    try {
      const employees = state.insights.employees.map(employeeToForm);
      const data = await api('/api/predict/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ employees }),
      });
      // Re-attach the real IDs so the table names actual people.
      data.results.forEach((row) => {
        row.EmployeeID = state.insights.employees[row.row - 1]?.EmployeeID || row.EmployeeID;
      });
      renderBatch(data);
      toast(`Assessed all ${data.count} bundled employees.`);
      loadHistory();
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('btnDownloadResults').addEventListener('click', downloadBatch);

  $('btnClearHistory').addEventListener('click', async () => {
    try {
      const { deleted } = await api('/api/history', { method: 'DELETE' });
      toast(`Cleared ${deleted} saved assessments.`);
      loadHistory();
    } catch (error) {
      toast(error.message, true);
    }
  });

  // Highlight the section currently in view.
  const links = [...document.querySelectorAll('.nav-links a')];
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      links.forEach((link) => link.classList.toggle('is-active', link.getAttribute('href') === `#${entry.target.id}`));
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  document.querySelectorAll('section[id]').forEach((section) => observer.observe(section));
}

/* ------------------------------------------------------------------ */
/* boot                                                                */
/* ------------------------------------------------------------------ */

async function boot() {
  wireEvents();

  try {
    const health = await api('/api/health');
    $('statusDot').textContent = health.model_trained ? `API online · v${health.version}` : 'model not trained';
    $('statusDot').classList.toggle('is-down', !health.model_trained);
  } catch {
    $('statusDot').textContent = 'API offline';
    $('statusDot').classList.add('is-down');
    toast('Could not reach the API. Is the server running?', true);
    return;
  }

  const [insights, model, schema] = await Promise.allSettled([
    api('/api/insights'), api('/api/model'), api('/api/schema'),
  ]);

  if (insights.status === 'fulfilled') {
    state.insights = insights.value;
    renderDashboard(insights.value);
    $('employeePicker').innerHTML = '<option value="">Blank form</option>' +
      insights.value.employees.map((e) =>
        `<option value="${e.EmployeeID}">${e.EmployeeID} — ${e.JobRole}, ${e.YearsAtCompany}y (${e.Attrition === 'Yes' ? 'left' : 'stayed'})</option>`,
      ).join('');
  } else {
    toast(insights.reason.message, true);
  }

  if (schema.status === 'fulfilled') {
    state.schema = schema.value;
    buildForm(schema.value);
  }

  if (model.status === 'fulfilled') {
    state.model = model.value;
    renderModel(model.value);
  } else {
    toast(model.reason.message, true);
  }

  loadHistory();
}

boot();
