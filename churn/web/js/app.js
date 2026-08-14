/**
 * Dashboard front-end. Plain ES modules, no framework and no build step - the
 * browser loads this file directly.
 */

import { PALETTE, columnChart, barChart, stackedChart, donutChart, lineChart, gauge } from './charts.js';

const $ = (id) => document.getElementById(id);
const api = (path, options) => fetch(path, options).then(async (response) => {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
});

const money = (v) => `$${Math.round(v).toLocaleString()}`;
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
  toastTimer = setTimeout(() => node.classList.remove('is-visible'), 3600);
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
/* dashboard                                                           */
/* ------------------------------------------------------------------ */

function renderKpis(kpis) {
  const tiles = [
    { label: 'Customers analysed', value: kpis.customers.toLocaleString(), delta: 'the full sample' },
    { label: 'Customers lost', value: kpis.churned.toLocaleString(), delta: `${pct1(kpis.churn_rate)} of the base`, accent: true },
    { label: 'Monthly revenue lost', value: money(kpis.monthly_revenue_at_risk), delta: `${money(kpis.annual_revenue_at_risk)} a year` },
    { label: 'Average time before leaving', value: `${kpis.avg_tenure_churned} mo`, delta: `stayers average ${kpis.avg_tenure_retained} mo` },
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

  $('heroChurn').textContent = pct1(kpis.churn_rate);
  $('heroFoot').textContent =
    `${kpis.churned} of ${kpis.customers} customers left, taking ${money(kpis.monthly_revenue_at_risk)} a month with them.`;

  renderKpis(kpis);

  // Part-to-whole, two segments.
  donutChart($('chartDonut'), {
    segments: [
      { label: 'Stayed', value: kpis.retained, color: PALETTE.series1 },
      { label: 'Left', value: kpis.churned, color: PALETTE.series2 },
    ],
    centerValue: kpis.customers.toLocaleString(),
    centerLabel: 'customers',
  });
  legend($('donutLegend'), [
    { label: `Stayed — ${kpis.retained}`, color: PALETTE.series1 },
    { label: `Left — ${kpis.churned}`, color: PALETTE.series2 },
  ]);

  // Single-series churn-rate charts: one colour, no legend box.
  const rateChart = (hostId, tableId, rows, order) => {
    const data = (order ? rows : [...rows].sort((a, b) => b.churn_rate - a.churn_rate))
      .map((r) => ({
        label: r.category,
        value: r.churn_rate,
        note: `${r.churned} of ${r.total} customers`,
      }));
    columnChart($(hostId), { data, label: 'Left', valueFormat: pct });
    table($(tableId), [
      { label: 'Group', get: (r) => r.category },
      { label: 'Customers', get: (r) => r.total },
      { label: 'Left', get: (r) => r.churned },
      { label: 'Leaving rate', get: (r) => pct1(r.churn_rate) },
      { label: 'Avg monthly bill', get: (r) => `$${r.avg_monthly.toFixed(2)}` },
    ], rows);
  };

  rateChart('chartContract', 'tableContract', breakdowns.Contract.data, true);
  rateChart('chartTenure', 'tableTenure', breakdowns.TenureBand.data, true);
  rateChart('chartPayment', 'tablePayment', breakdowns.PaymentMethod.data, false);

  // Two-series stacked head count - legend required.
  const hist = data.tenure_histogram.map((h) => ({
    label: h.label, retained: h.retained, churned: h.churned,
  }));
  stackedChart($('chartTenureHist'), {
    data: hist,
    series: [
      { key: 'retained', label: 'Stayed', color: PALETTE.series1 },
      { key: 'churned', label: 'Left', color: PALETTE.series2 },
    ],
  });
  legend($('histLegend'), [
    { label: 'Stayed', color: PALETTE.series1 },
    { label: 'Left', color: PALETTE.series2 },
  ]);
  table($('tableHist'), [
    { label: 'Months with us', get: (r) => r.label },
    { label: 'Customers', get: (r) => r.total },
    { label: 'Stayed', get: (r) => r.retained },
    { label: 'Left', get: (r) => r.churned },
    { label: 'Leaving rate', get: (r) => pct1(r.churn_rate) },
  ], data.tenure_histogram);

  // Riskiest segments - horizontal bars, one series.
  barChart($('chartSegments'), {
    data: data.risk_segments.map((s) => ({
      label: s.segment,
      value: s.churn_rate,
      note: `${s.customers} customers · ${s.lift}x the average rate`,
    })),
    label: 'Leaving rate',
    valueFormat: pct,
    labelWidth: 200,
  });
  table($('tableSegments'), [
    { label: 'Group', get: (r) => r.segment },
    { label: 'Customers', get: (r) => r.customers },
    { label: 'Leaving rate', get: (r) => pct1(r.churn_rate) },
    { label: 'vs average', get: (r) => `${r.lift}x` },
  ], data.risk_segments);

  $('headlines').innerHTML = data.headlines.map((h) => `
    <div class="headline"><h4>${h.title}</h4><p>${h.detail}</p></div>`).join('');
}

/* ------------------------------------------------------------------ */
/* prediction form                                                     */
/* ------------------------------------------------------------------ */

const FIELD_LABELS = {
  gender: 'Gender', SeniorCitizen: 'Senior citizen', Partner: 'Has a partner',
  Dependents: 'Has dependents', PhoneService: 'Phone service', MultipleLines: 'Multiple lines',
  InternetService: 'Internet service', OnlineSecurity: 'Online security', OnlineBackup: 'Online backup',
  DeviceProtection: 'Device protection', TechSupport: 'Tech support', StreamingTV: 'Streaming TV',
  StreamingMovies: 'Streaming movies', Contract: 'Contract type', PaperlessBilling: 'Paperless billing',
  PaymentMethod: 'Payment method',
  // numeric and engineered columns, so the model card never shows a raw name
  tenure: 'Months as a customer', MonthlyCharges: 'Monthly bill', TotalCharges: 'Lifetime spend',
  NumServices: 'Number of services', AvgMonthlySpend: 'Average monthly spend',
  ChargeRatio: 'Recent price change', TenureBand: 'Time as a customer',
};

const GROUPS = {
  groupAccount: ['gender', 'SeniorCitizen', 'Partner', 'Dependents', 'Contract'],
  groupServices: ['PhoneService', 'MultipleLines', 'InternetService', 'OnlineSecurity',
    'OnlineBackup', 'DeviceProtection', 'TechSupport', 'StreamingTV', 'StreamingMovies'],
  groupBilling: ['PaperlessBilling', 'PaymentMethod'],
};

const DEFAULTS = {
  gender: 'Female', SeniorCitizen: 'No', Partner: 'No', Dependents: 'No', tenure: 12,
  PhoneService: 'Yes', MultipleLines: 'No', InternetService: 'Fiber optic', OnlineSecurity: 'No',
  OnlineBackup: 'No', DeviceProtection: 'No', TechSupport: 'No', StreamingTV: 'No',
  StreamingMovies: 'No', Contract: 'Month-to-month', PaperlessBilling: 'Yes',
  PaymentMethod: 'Electronic check', MonthlyCharges: 70, TotalCharges: 840,
};

function buildForm(schema) {
  for (const [hostId, fields] of Object.entries(GROUPS)) {
    $(hostId).innerHTML = fields.map((field) => `
      <div class="field">
        <label for="f_${field}">${FIELD_LABELS[field]}</label>
        <select id="f_${field}" name="${field}">
          ${schema.categorical[field].map((o) => `<option value="${o}">${o}</option>`).join('')}
        </select>
      </div>`).join('');
  }

  // Numeric inputs sit with the account group so tenure reads next to contract.
  $('groupAccount').insertAdjacentHTML('beforeend', `
    <div class="field">
      <label for="f_tenure">Months as a customer</label>
      <input type="number" id="f_tenure" name="tenure" min="0" max="100" step="1">
    </div>`);
  $('groupBilling').insertAdjacentHTML('beforeend', `
    <div class="field">
      <label for="f_MonthlyCharges">Monthly bill ($)</label>
      <input type="number" id="f_MonthlyCharges" name="MonthlyCharges" min="0" max="1000" step="0.05">
    </div>
    <div class="field">
      <label for="f_TotalCharges">Total spent so far ($)</label>
      <input type="number" id="f_TotalCharges" name="TotalCharges" min="0" step="0.05">
      <span class="hint">Left blank it is estimated as months x monthly bill.</span>
    </div>`);

  // Keep lifetime spend in step with the other two unless it was edited by hand.
  const sync = () => {
    const total = $('f_TotalCharges');
    if (total.dataset.touched === '1') return;
    total.value = (Number($('f_tenure').value || 0) * Number($('f_MonthlyCharges').value || 0)).toFixed(2);
  };
  $('f_tenure').addEventListener('input', sync);
  $('f_MonthlyCharges').addEventListener('input', sync);
  $('f_TotalCharges').addEventListener('input', function markTouched() { this.dataset.touched = '1'; });

  fillForm(DEFAULTS);
}

function fillForm(values) {
  Object.entries(values).forEach(([key, value]) => {
    const node = $(`f_${key}`);
    if (node) node.value = value;
  });
  const total = $('f_TotalCharges');
  if (total) total.dataset.touched = '0';
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

  gauge($('gauge'), { value: result.probability, band: result.risk_band });

  const pill = $('riskPill');
  pill.className = `risk-pill risk-${result.risk_band}`;
  pill.textContent = `${result.risk_band} risk`;
  $('riskAdvice').textContent = result.advice;

  $('valueAtRisk').innerHTML = result.will_churn
    ? `<strong>Flagged for retention.</strong> At ${pct1(result.probability)} risk on a
       $${Number(readForm().MonthlyCharges).toFixed(2)} monthly bill, roughly
       <strong>${money(result.value_at_risk)}</strong> of yearly revenue is exposed.`
    : `<strong>No action needed today.</strong> This customer scores below the
       ${pct(result.threshold)} alert line the model uses to flag an account.`;

  const drivers = $('driversList');
  if (result.drivers?.length) {
    $('driversCard').hidden = false;
    const worst = Math.max(...result.drivers.map((d) => Math.abs(d.impact))) || 1;
    drivers.innerHTML = result.drivers.map((d) => {
      const up = d.impact > 0;
      const width = Math.max(6, (Math.abs(d.impact) / worst) * 100);
      return `
        <div class="driver-row">
          <div class="driver-bar">
            <i style="width:${width}%; background:${up ? PALETTE.serious : PALETTE.series1}"></i>
          </div>
          <div class="driver-meta">
            <strong>${d.label}: ${d.value}</strong>
            <span>${up ? 'raises' : 'lowers'} the risk against a typical customer (${d.compared_to})</span>
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
    actions.innerHTML = result.actions.map((a, i) => `
      <div class="action-row">
        <div class="badge">${i + 1}</div>
        <div class="driver-meta">
          <strong>${a.recommendation}</strong>
          <span>${a.label}: ${a.from} → ${a.to} · risk falls to ${pct1(a.new_probability)}</span>
        </div>
        <div class="driver-impact down">−${(a.reduction * 100).toFixed(1)} pts</div>
      </div>`).join('');
  } else {
    $('actionsCard').hidden = true;
  }
}

/* ------------------------------------------------------------------ */
/* batch scoring                                                       */
/* ------------------------------------------------------------------ */

function renderBatch(data) {
  state.batch = data;
  $('btnDownloadResults').hidden = false;
  $('batchSummary').innerHTML = `
    <div class="grid grid-4">
      <div class="stat"><div class="label">Rows scored</div><div class="value">${data.count}</div></div>
      <div class="stat accent"><div class="label">Flagged at risk</div><div class="value">${data.flagged}</div>
        <div class="delta">${pct1(data.flagged_share)} of the list</div></div>
      <div class="stat"><div class="label">Yearly revenue exposed</div><div class="value">${money(data.annual_value_at_risk)}</div></div>
      <div class="stat"><div class="label">Alert line</div><div class="value">${pct(data.threshold)}</div>
        <div class="delta">scores above this are flagged</div></div>
    </div>`;

  table($('batchResults'), [
    { label: 'Customer', get: (r) => r.customerID },
    { label: 'Months', get: (r) => r.tenure ?? '—' },
    { label: 'Contract', get: (r) => r.Contract ?? '—' },
    { label: 'Monthly bill', get: (r) => (r.MonthlyCharges != null ? `$${Number(r.MonthlyCharges).toFixed(2)}` : '—') },
    { label: 'Risk', get: (r) => `${r.percent}%` },
    { label: 'Band', get: (r) => `<span class="risk-pill risk-${r.risk_band}">${r.risk_band}</span>` },
  ], data.results);
}

function downloadBatch() {
  if (!state.batch) return;
  const header = 'customerID,tenure,Contract,MonthlyCharges,probability,percent,risk_band,will_churn';
  const lines = state.batch.results.map((r) => [
    r.customerID, r.tenure, `"${r.Contract ?? ''}"`, r.MonthlyCharges,
    r.probability, r.percent, r.risk_band, r.will_churn,
  ].join(','));
  const blob = new Blob([`${header}\n${lines.join('\n')}`], { type: 'text/csv' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'churn-scores.csv';
  link.click();
  URL.revokeObjectURL(link.href);
}

async function uploadCsv(file) {
  if (!file) return;
  const body = new FormData();
  body.append('file', file);
  try {
    renderBatch(await api('/api/predict/csv', { method: 'POST', body }));
    toast(`Scored ${state.batch.count} customers.`);
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
    ${model.evaluation.explanation} <br><br>
    <strong>Read these numbers as a demonstration, not a benchmark.</strong>
    ${model.evaluation.caveat}`;

  const tiles = [
    { label: 'Ranking quality (ROC-AUC)', value: s.roc_auc.toFixed(3), delta: '1.0 is perfect, 0.5 is guessing', accent: true },
    { label: 'Leavers correctly caught', value: pct(s.recall), delta: 'of everyone who actually left' },
    { label: 'Alerts that were right', value: pct(s.precision), delta: 'of the customers it flagged' },
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
    The two red boxes are the mistakes. A <strong>false alarm</strong> costs a needless
    retention call; a <strong>missed leaver</strong> costs the whole customer. That is why
    the alert line sits at ${pct(model.decision_threshold)} rather than the textbook 50% —
    catching leavers matters more here than avoiding a wasted phone call.`;

  barChart($('chartImportance'), {
    data: model.feature_importance.map((f) => ({
      label: FIELD_LABELS[f.feature] || f.feature,
      value: f.importance,
      note: 'Accuracy lost when this detail is scrambled',
    })),
    label: 'Accuracy lost when scrambled',
    valueFormat: (v) => v.toFixed(3),
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

  $('footerMeta').textContent = `${model.selected_model} · trained ${model.generated_at} · ${model.rows_total} customers`;
}

/* ------------------------------------------------------------------ */
/* history                                                             */
/* ------------------------------------------------------------------ */

async function loadHistory() {
  try {
    const data = await api('/api/history?limit=25');
    const s = data.summary;
    $('historySummary').innerHTML = `
      <div class="stat"><div class="label">Predictions made</div><div class="value">${s.total}</div></div>
      <div class="stat accent"><div class="label">Flagged at risk</div><div class="value">${s.flagged}</div></div>
      <div class="stat"><div class="label">Average risk</div><div class="value">${pct1(s.avg_probability)}</div></div>
      <div class="stat"><div class="label">Monthly revenue exposed</div><div class="value">${money(s.monthly_at_risk)}</div></div>`;

    if (!data.items.length) {
      $('historyTable').innerHTML = '<p class="result-empty">Nothing scored yet.</p>';
      return;
    }
    table($('historyTable'), [
      { label: 'When', get: (r) => new Date(r.created_at).toLocaleString() },
      { label: 'Customer', get: (r) => r.customer_ref || '—' },
      { label: 'Source', get: (r) => r.source },
      { label: 'Months', get: (r) => r.tenure },
      { label: 'Contract', get: (r) => r.contract || '—' },
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

function customerToForm(customer) {
  const record = { ...customer };
  delete record.Churn; delete record.customerID;
  delete record.NumServices; delete record.TenureBand;
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
    button.innerHTML = '<span class="spinner"></span> Calculating…';
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
      button.textContent = 'Calculate churn risk';
    }
  });

  $('customerPicker').addEventListener('change', (event) => {
    if (!event.target.value) { fillForm(DEFAULTS); return; }
    const customer = state.insights.customers.find((c) => c.customerID === event.target.value);
    if (customer) {
      fillForm(customerToForm(customer));
      toast(`Loaded ${customer.customerID} — this customer actually ${customer.Churn === 'Yes' ? 'left' : 'stayed'}.`);
    }
  });

  $('btnRandom').addEventListener('click', () => {
    const list = state.insights.customers;
    const pick = list[Math.floor(Math.random() * list.length)];
    $('customerPicker').value = pick.customerID;
    $('customerPicker').dispatchEvent(new Event('change'));
  });

  $('btnReset').addEventListener('click', () => {
    $('customerPicker').value = '';
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
      const customers = state.insights.customers.map(customerToForm);
      const data = await api('/api/predict/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customers }),
      });
      // Re-attach the real IDs so the table names actual people.
      data.results.forEach((row) => {
        row.customerID = state.insights.customers[row.row - 1]?.customerID || row.customerID;
      });
      renderBatch(data);
      toast(`Scored all ${data.count} bundled customers.`);
      loadHistory();
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('btnDownloadResults').addEventListener('click', downloadBatch);

  $('btnClearHistory').addEventListener('click', async () => {
    try {
      const { deleted } = await api('/api/history', { method: 'DELETE' });
      toast(`Cleared ${deleted} saved predictions.`);
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
    $('customerPicker').innerHTML = '<option value="">Blank form</option>' +
      insights.value.customers.map((c) =>
        `<option value="${c.customerID}">${c.customerID} — ${c.tenure} months, ${c.Contract} (${c.Churn === 'Yes' ? 'left' : 'stayed'})</option>`,
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
