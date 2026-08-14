/**
 * Minimal SVG chart library - no external dependencies, no CDN, no build step.
 *
 * Every mark follows one spec sheet: bars capped at 24px with a 4px rounded
 * data-end, 2px lines, a 2px surface-coloured gap between touching fills, solid
 * hairline gridlines, and labels in text tokens rather than the series colour.
 * Colours come from the CSS custom properties in styles.css, which were checked
 * for colour-blind separation against the dark navy surface before being used.
 */

const NS = 'http://www.w3.org/2000/svg';

export const PALETTE = {
  series1: '#0b9ada', // sky blue  - the default single series
  series2: '#d95926', // orange    - "churned" where two series are shown
  series3: '#199e70', // aqua      - spare third slot
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
};

const GAP = 2;        // surface gap between touching marks
const MAX_BAR = 24;   // bars never fill their slot - the leftover is air
const RADIUS = 4;     // rounded data-end

/* ------------------------------------------------------------------ */
/* helpers                                                             */
/* ------------------------------------------------------------------ */

function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  if (parent) parent.appendChild(node);
  return node;
}

function svgRoot(host, width, height) {
  host.innerHTML = '';
  const svg = el('svg', {
    viewBox: `0 0 ${width} ${height}`,
    preserveAspectRatio: 'xMidYMid meet',
    role: 'img',
  }, host);
  return svg;
}

/** A bar with its data-end rounded and its baseline end square. */
function barPath(x, y, w, h, side = 'top') {
  const r = Math.min(RADIUS, w / 2, h);
  if (h <= 0.5) return `M${x} ${y + h} h${w}`;
  if (side === 'top') {
    return `M${x} ${y + h} V${y + r} a${r} ${r} 0 0 1 ${r} -${r} h${w - 2 * r} a${r} ${r} 0 0 1 ${r} ${r} V${y + h} Z`;
  }
  // horizontal bar growing to the right
  return `M${x} ${y} h${w - r} a${r} ${r} 0 0 1 ${r} ${r} v${h - 2 * r} a${r} ${r} 0 0 1 -${r} ${r} H${x} Z`;
}

/* ------------------------------------------------------------------ */
/* shared tooltip                                                      */
/* ------------------------------------------------------------------ */

let tipNode = null;

function tooltip() {
  if (!tipNode) {
    tipNode = document.createElement('div');
    tipNode.className = 'chart-tip';
    tipNode.setAttribute('role', 'status');
    document.body.appendChild(tipNode);
  }
  return tipNode;
}

function showTip(event, html) {
  const tip = tooltip();
  tip.innerHTML = html;
  tip.classList.add('is-visible');
  const box = tip.getBoundingClientRect();
  let left = event.clientX + 14;
  let top = event.clientY - box.height - 12;
  if (left + box.width > window.innerWidth - 8) left = event.clientX - box.width - 14;
  if (top < 8) top = event.clientY + 18;
  tip.style.transform = `translate(${left}px, ${top}px)`;
}

function hideTip() {
  if (tipNode) tipNode.classList.remove('is-visible');
}

/**
 * Make a mark interactive. The hit area is a separate transparent rect that is
 * always at least 24px, so a thin bar is still comfortable to hover, and the
 * same content is exposed to keyboard focus.
 */
function interactive(svg, hit, html) {
  hit.setAttribute('tabindex', '0');
  hit.setAttribute('class', 'chart-hit');
  hit.addEventListener('mousemove', (e) => showTip(e, html));
  hit.addEventListener('mouseleave', hideTip);
  hit.addEventListener('focus', (e) => {
    const box = e.target.getBoundingClientRect();
    showTip({ clientX: box.left + box.width / 2, clientY: box.top }, html);
  });
  hit.addEventListener('blur', hideTip);
}

const pct = (v) => `${(v * 100).toFixed(0)}%`;
const pct1 = (v) => `${(v * 100).toFixed(1)}%`;

/* ------------------------------------------------------------------ */
/* column chart - one series (the default form)                        */
/* ------------------------------------------------------------------ */

/**
 * Vertical columns for a single measure across categories.
 * One series means one colour and no legend box: the card title names it.
 */
export function columnChart(host, { data, label = 'value', valueFormat = pct, color = PALETTE.series1, highlightMax = true, yMax = null }) {
  const W = 560, H = 260;
  const pad = { top: 26, right: 12, bottom: 46, left: 44 };
  const svg = svgRoot(host, W, H);
  if (!data.length) return;

  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;
  const max = yMax ?? (Math.max(...data.map((d) => d.value)) * 1.15 || 1);
  const band = plotW / data.length;
  const barW = Math.min(MAX_BAR, band - GAP * 4);
  const peak = highlightMax ? Math.max(...data.map((d) => d.value)) : NaN;

  // gridlines - solid hairlines, one step off the surface
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotH / 4) * i;
    el('line', { x1: pad.left, x2: W - pad.right, y1: y, y2: y, class: 'grid' }, svg);
    el('text', {
      x: pad.left - 8, y: y + 4, class: 'tick tick-y', 'text-anchor': 'end',
    }, svg).textContent = valueFormat(max * (1 - i / 4));
  }
  el('line', { x1: pad.left, x2: W - pad.right, y1: pad.top + plotH, y2: pad.top + plotH, class: 'axis' }, svg);

  data.forEach((d, i) => {
    const x = pad.left + band * i + (band - barW) / 2;
    const h = Math.max(1, (d.value / max) * plotH);
    const y = pad.top + plotH - h;

    el('path', { d: barPath(x, y, barW, h), fill: color, class: 'mark' }, svg);

    // Label only the extreme, never every column.
    if (d.value === peak) {
      el('text', { x: x + barW / 2, y: y - 8, class: 'mark-label', 'text-anchor': 'middle' }, svg)
        .textContent = valueFormat(d.value);
    }

    const caption = el('text', {
      x: pad.left + band * i + band / 2, y: pad.top + plotH + 18, class: 'tick', 'text-anchor': 'middle',
    }, svg);
    wrapLabel(caption, d.label, band);

    const hit = el('rect', {
      x: pad.left + band * i, y: pad.top, width: band, height: plotH, fill: 'none', 'pointer-events': 'all',
    }, svg);
    interactive(svg, hit, `<strong>${d.label}</strong><span>${label}: ${valueFormat(d.value)}</span>${d.note ? `<span>${d.note}</span>` : ''}`);
  });
}

/** Split a long category name over at most two lines so it never overlaps. */
function wrapLabel(textNode, label, available) {
  const perChar = 6.2;
  if (label.length * perChar <= available) {
    textNode.textContent = label;
    return;
  }
  const words = label.split(' ');
  const lines = [''];
  words.forEach((word) => {
    const current = lines[lines.length - 1];
    if (((current ? current + ' ' : '') + word).length * perChar > available && current) lines.push(word);
    else lines[lines.length - 1] = current ? `${current} ${word}` : word;
  });
  const x = textNode.getAttribute('x');
  const y = Number(textNode.getAttribute('y'));
  textNode.textContent = '';
  lines.slice(0, 2).forEach((line, i) => {
    el('tspan', { x, y: y + i * 12 }, textNode).textContent = line;
  });
}

/* ------------------------------------------------------------------ */
/* horizontal bars - one series                                        */
/* ------------------------------------------------------------------ */

export function barChart(host, { data, label = 'value', valueFormat = (v) => v.toFixed(3), color = PALETTE.series1, labelWidth = 150 }) {
  const rowH = 30;
  const W = 560;
  const pad = { top: 8, right: 60, bottom: 8, left: labelWidth };
  const H = pad.top + pad.bottom + data.length * rowH;
  const svg = svgRoot(host, W, H);
  if (!data.length) return;

  const plotW = W - pad.left - pad.right;
  const max = Math.max(...data.map((d) => d.value)) || 1;
  const barH = Math.min(MAX_BAR - 6, rowH - GAP * 4);

  data.forEach((d, i) => {
    const y = pad.top + i * rowH + (rowH - barH) / 2;
    const w = Math.max(2, (d.value / max) * plotW);

    const maxChars = Math.floor((labelWidth - 12) / 6.2);
    el('text', { x: pad.left - 10, y: y + barH / 2 + 4, class: 'tick', 'text-anchor': 'end' }, svg)
      .textContent = d.label.length > maxChars ? `${d.label.slice(0, maxChars - 1)}…` : d.label;
    el('path', { d: barPath(pad.left, y, w, barH, 'right'), fill: color, class: 'mark' }, svg);
    // Bars → value at the tip.
    el('text', { x: pad.left + w + 8, y: y + barH / 2 + 4, class: 'mark-label' }, svg)
      .textContent = valueFormat(d.value);

    const hit = el('rect', { x: pad.left, y: pad.top + i * rowH, width: plotW + 60, height: rowH, fill: 'transparent' }, svg);
    interactive(svg, hit, `<strong>${d.label}</strong><span>${label}: ${valueFormat(d.value)}</span>${d.note ? `<span>${d.note}</span>` : ''}`);
  });
}

/* ------------------------------------------------------------------ */
/* stacked columns - two series                                        */
/* ------------------------------------------------------------------ */

/**
 * Two stacked series (stayed / left) per category. A 2px surface gap - not a
 * stroke - separates the two segments.
 */
export function stackedChart(host, { data, series }) {
  const W = 560, H = 250;
  const pad = { top: 18, right: 12, bottom: 44, left: 44 };
  const svg = svgRoot(host, W, H);
  if (!data.length) return;

  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;
  const max = Math.max(...data.map((d) => series.reduce((sum, s) => sum + d[s.key], 0))) * 1.1 || 1;
  const band = plotW / data.length;
  const barW = Math.min(MAX_BAR, band - GAP * 4);

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotH / 4) * i;
    el('line', { x1: pad.left, x2: W - pad.right, y1: y, y2: y, class: 'grid' }, svg);
    el('text', { x: pad.left - 8, y: y + 4, class: 'tick tick-y', 'text-anchor': 'end' }, svg)
      .textContent = Math.round(max * (1 - i / 4));
  }
  el('line', { x1: pad.left, x2: W - pad.right, y1: pad.top + plotH, y2: pad.top + plotH, class: 'axis' }, svg);

  data.forEach((d, i) => {
    const x = pad.left + band * i + (band - barW) / 2;
    let cursor = pad.top + plotH;

    series.forEach((s, sIndex) => {
      const raw = (d[s.key] / max) * plotH;
      if (raw <= 0) return;
      // Take the gap out of the lower segment so the total height stays true.
      const h = sIndex === 0 ? Math.max(1, raw - GAP) : Math.max(1, raw);
      const y = cursor - h;
      const isTop = sIndex === series.length - 1;
      el('path', {
        d: isTop ? barPath(x, y, barW, h) : `M${x} ${y} h${barW} v${h} h-${barW} Z`,
        fill: s.color, class: 'mark',
      }, svg);
      cursor -= raw;
    });

    const caption = el('text', {
      x: pad.left + band * i + band / 2, y: pad.top + plotH + 18, class: 'tick', 'text-anchor': 'middle',
    }, svg);
    wrapLabel(caption, d.label, band);

    const total = series.reduce((sum, s) => sum + d[s.key], 0);
    const hit = el('rect', { x: pad.left + band * i, y: pad.top, width: band, height: plotH, fill: 'transparent' }, svg);
    interactive(svg, hit,
      `<strong>${d.label}</strong>` +
      series.map((s) => `<span>${s.label}: ${d[s.key]}</span>`).join('') +
      `<span>Left: ${total ? pct1(d[series[1].key] / total) : '0%'}</span>`);
  });
}

/* ------------------------------------------------------------------ */
/* donut - part to whole, two segments                                 */
/* ------------------------------------------------------------------ */

export function donutChart(host, { segments, centerValue, centerLabel }) {
  const size = 220, r = 82, thickness = 20;
  const svg = svgRoot(host, size, size);
  const cx = size / 2, cy = size / 2;
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;

  // A 2px surface gap, expressed as an angle, separates the segments.
  const gapAngle = (GAP / r);
  let angle = -Math.PI / 2;

  segments.forEach((s) => {
    const sweep = (s.value / total) * Math.PI * 2;
    const start = angle + gapAngle / 2;
    const end = angle + sweep - gapAngle / 2;
    if (end > start) {
      const large = end - start > Math.PI ? 1 : 0;
      const path = el('path', {
        d: `M${cx + r * Math.cos(start)} ${cy + r * Math.sin(start)} A${r} ${r} 0 ${large} 1 ${cx + r * Math.cos(end)} ${cy + r * Math.sin(end)}`,
        fill: 'none', stroke: s.color, 'stroke-width': thickness, class: 'mark',
      }, svg);
      interactive(svg, path, `<strong>${s.label}</strong><span>${s.value} customers</span><span>${pct1(s.value / total)} of the base</span>`);
    }
    angle += sweep;
  });

  el('text', { x: cx, y: cy - 2, class: 'donut-value', 'text-anchor': 'middle' }, svg).textContent = centerValue;
  el('text', { x: cx, y: cy + 20, class: 'donut-label', 'text-anchor': 'middle' }, svg).textContent = centerLabel;
}

/* ------------------------------------------------------------------ */
/* line chart - ROC curve                                              */
/* ------------------------------------------------------------------ */

export function lineChart(host, { points, reference = true, xLabel = '', yLabel = '', color = PALETTE.series1 }) {
  const W = 400, H = 300;
  const pad = { top: 16, right: 16, bottom: 46, left: 50 };
  const svg = svgRoot(host, W, H);
  if (!points.length) return;

  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;
  const sx = (v) => pad.left + v * plotW;
  const sy = (v) => pad.top + plotH - v * plotH;

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotH / 4) * i;
    el('line', { x1: pad.left, x2: W - pad.right, y1: y, y2: y, class: 'grid' }, svg);
    el('text', { x: pad.left - 8, y: y + 4, class: 'tick tick-y', 'text-anchor': 'end' }, svg)
      .textContent = (1 - i / 4).toFixed(2);
  }
  [0, 0.5, 1].forEach((v) => {
    el('text', { x: sx(v), y: pad.top + plotH + 20, class: 'tick', 'text-anchor': 'middle' }, svg)
      .textContent = v.toFixed(1);
  });
  el('line', { x1: pad.left, x2: W - pad.right, y1: pad.top + plotH, y2: pad.top + plotH, class: 'axis' }, svg);

  if (reference) {
    el('line', { x1: sx(0), y1: sy(0), x2: sx(1), y2: sy(1), class: 'reference' }, svg);
    el('text', { x: sx(0.62), y: sy(0.52), class: 'tick reference-label' }, svg).textContent = 'random guessing';
  }

  const d = points.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x)} ${sy(p.y)}`).join(' ');
  el('path', {
    d: `${d} L${sx(1)} ${sy(0)} Z`, fill: color, opacity: 0.1, stroke: 'none',
  }, svg);
  el('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);

  el('text', { x: pad.left + plotW / 2, y: H - 6, class: 'axis-title', 'text-anchor': 'middle' }, svg).textContent = xLabel;
  el('text', { x: 14, y: pad.top + plotH / 2, class: 'axis-title', 'text-anchor': 'middle', transform: `rotate(-90 14 ${pad.top + plotH / 2})` }, svg).textContent = yLabel;

  // A nearest-point layer, so hovering anywhere in the plot reads the curve.
  const hit = el('rect', { x: pad.left, y: pad.top, width: plotW, height: plotH, fill: 'transparent' }, svg);
  const marker = el('circle', { r: 5, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2, opacity: 0 }, svg);
  hit.addEventListener('mousemove', (event) => {
    const box = hit.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / box.width;
    let nearest = points[0];
    points.forEach((p) => { if (Math.abs(p.x - ratio) < Math.abs(nearest.x - ratio)) nearest = p; });
    marker.setAttribute('cx', sx(nearest.x));
    marker.setAttribute('cy', sy(nearest.y));
    marker.setAttribute('opacity', 1);
    showTip(event, `<strong>Detection trade-off</strong><span>Catches ${pct(nearest.y)} of leavers</span><span>False alarms on ${pct(nearest.x)} of stayers</span>`);
  });
  hit.addEventListener('mouseleave', () => { marker.setAttribute('opacity', 0); hideTip(); });
}

/* ------------------------------------------------------------------ */
/* meter - the single-customer risk gauge                              */
/* ------------------------------------------------------------------ */

/** Severity rides the fill; the unfilled track is a lighter step of the ramp. */
export function gauge(host, { value, band, caption = 'risk' }) {
  const W = 260, H = 150;
  const svg = svgRoot(host, W, H);
  const cx = W / 2, cy = 128, r = 96, thickness = 16;
  const colors = { Low: PALETTE.good, Moderate: PALETTE.warning, High: PALETTE.serious, Critical: PALETTE.critical };
  const color = colors[band] || PALETTE.series1;

  const arc = (from, to) => {
    const a0 = Math.PI + from * Math.PI;
    const a1 = Math.PI + to * Math.PI;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    return `M${cx + r * Math.cos(a0)} ${cy + r * Math.sin(a0)} A${r} ${r} 0 ${large} 1 ${cx + r * Math.cos(a1)} ${cy + r * Math.sin(a1)}`;
  };

  el('path', { d: arc(0, 1), fill: 'none', stroke: 'var(--track)', 'stroke-width': thickness, 'stroke-linecap': 'round' }, svg);
  if (value > 0.002) {
    el('path', {
      d: arc(0, Math.max(0.02, value)), fill: 'none', stroke: color,
      'stroke-width': thickness, 'stroke-linecap': 'round', class: 'gauge-fill',
    }, svg);
  }

  el('text', { x: cx, y: cy - 30, class: 'gauge-value', 'text-anchor': 'middle' }, svg).textContent = `${(value * 100).toFixed(0)}%`;
  el('text', { x: cx, y: cy - 8, class: 'gauge-caption', 'text-anchor': 'middle' }, svg).textContent = caption;
  el('text', { x: cx - r, y: cy + 22, class: 'tick', 'text-anchor': 'middle' }, svg).textContent = '0%';
  el('text', { x: cx + r, y: cy + 22, class: 'tick', 'text-anchor': 'middle' }, svg).textContent = '100%';
}

export { pct, pct1 };
