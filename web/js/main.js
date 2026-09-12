/**
 * Application wiring: reads the control panel, calls the API, and keeps the 2D
 * plan, the 3D model and the analysis panels in sync with one plan payload.
 */

import { Plan2D } from './plan2d.js';
import { View3D } from './view3d.js';
import {
  renderCost, renderHeader, renderMetrics, renderSchedule, renderScore, renderValidation,
} from './panels.js';

const $ = (id) => document.getElementById(id);

const NUMBER_FIELDS = ['plot_width', 'plot_depth', 'setback_front', 'setback_rear',
  'setback_left', 'setback_right', 'max_far', 'max_coverage'];
const RANGE_FIELDS = ['floors', 'bedrooms', 'bathrooms', 'parking_cars', 'balconies', 'restarts'];
const SELECT_FIELDS = ['roof_type', 'facing', 'quality', 'city_tier'];

const state = {
  plan: null,
  floor: 0,
  view: '2d',
  units: 'ft',
  parking_type: 'covered',
  extras: new Set(['pooja', 'utility']),
  busy: false,
  pending: false,
};

const plan2d = new Plan2D($('svgHost'));
const view3d = new View3D($('canvas3d'));

// ── helpers ───────────────────────────────────────────────
let toastTimer = null;
function toast(msg, ms = 3200) {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

function busy(on, label = 'Planning…') {
  state.busy = on;
  $('loading').hidden = !on;
  $('loadingText').textContent = label;
  $('btnGenerate').disabled = on;
}

function readForm() {
  const req = { units: state.units, parking_type: state.parking_type, extras: [...state.extras] };
  NUMBER_FIELDS.forEach((f) => { req[f] = parseFloat($(f).value) || 0; });
  RANGE_FIELDS.forEach((f) => { req[f] = parseInt($(f).value, 10) || 0; });
  SELECT_FIELDS.forEach((f) => { req[f] = $(f).value; });
  req.ground_bedroom = $('ground_bedroom').checked;
  req.notes = $('briefText').value.slice(0, 2000);
  return req;
}

function writeForm(req) {
  state.units = req.units;
  $('plot_width').value = req.plot_width_input ?? req.plot_width;
  $('plot_depth').value = req.plot_depth_input ?? req.plot_depth;
  ['setback_front', 'setback_rear', 'setback_left', 'setback_right', 'max_far', 'max_coverage']
    .forEach((f) => { if (req[f] !== undefined) $(f).value = req[f]; });
  RANGE_FIELDS.forEach((f) => { if (req[f] !== undefined) $(f).value = req[f]; });
  SELECT_FIELDS.forEach((f) => { if (req[f] !== undefined) $(f).value = req[f]; });
  $('ground_bedroom').checked = !!req.ground_bedroom;

  state.parking_type = req.parking_type || 'covered';
  state.extras = new Set(req.extras || []);
  syncSegs();
  syncOutputs();
}

function syncOutputs() {
  RANGE_FIELDS.forEach((f) => {
    const out = $(`${f}Out`);
    if (!out) return;
    const v = $(f).value;
    out.textContent = (f === 'bathrooms' && v === '0') ? 'auto' : v;
  });
  $('unitW').textContent = state.units;
  $('unitD').textContent = state.units;
  const k = state.units === 'ft' ? 0.3048 : 1;
  const w = (parseFloat($('plot_width').value) || 0) * k;
  const d = (parseFloat($('plot_depth').value) || 0) * k;
  $('plotSummary').textContent =
    `${w.toFixed(2)} × ${d.toFixed(2)} m = ${(w * d).toFixed(1)} m² (${(w * d * 10.7639).toFixed(0)} sq ft)`;
}

function syncSegs() {
  document.querySelectorAll('#unitsSeg button').forEach((b) => {
    b.classList.toggle('active', b.dataset.units === state.units);
  });
  document.querySelectorAll('#parkingSeg button').forEach((b) => {
    b.classList.toggle('active', b.dataset.parking === state.parking_type);
  });
  document.querySelectorAll('#extrasChips button').forEach((b) => {
    b.classList.toggle('active', state.extras.has(b.dataset.extra));
  });
}

// ── generate ──────────────────────────────────────────────
let debounce = null;
function scheduleGenerate() {
  if (!$('autoUpdate').checked) return;
  clearTimeout(debounce);
  debounce = setTimeout(generate, 280);
}

async function generate() {
  if (state.busy) { state.pending = true; return; }
  busy(true);
  try {
    const res = await fetch('/api/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(readForm()),
    });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || 'Could not plan these requirements');
      return;
    }
    state.plan = data;
    state.floor = Math.min(state.floor, data.levels.length - 1);
    paint();
  } catch (err) {
    toast(`Request failed: ${err.message}`);
  } finally {
    busy(false);
    if (state.pending) { state.pending = false; generate(); }
  }
}

function paint() {
  const p = state.plan;
  if (!p) return;

  $('floorTabs').innerHTML = p.levels.map((l) => `
    <button data-floor="${l.level}" class="${l.level === state.floor ? 'active' : ''}">
      ${l.name} · ${l.area.toFixed(0)} m²</button>`).join('')
    + `<button data-floor="all" class="${state.floor === 'all' ? 'active' : ''}">All levels (3D)</button>`;
  $('floorTabs').querySelectorAll('button').forEach((b) => {
    b.addEventListener('click', () => {
      state.floor = b.dataset.floor === 'all' ? 'all' : parseInt(b.dataset.floor, 10);
      paint();
    });
  });

  const f2d = state.floor === 'all' ? 0 : state.floor;
  plan2d.setPlan(p);
  plan2d.setFloor(f2d);
  view3d.setPlan(p);
  view3d.setFloor(state.floor === 'all' ? null : state.floor);

  renderHeader(p);
  renderMetrics(p);
  renderValidation(p, focusRooms, applyFix);
  renderScore(p, focusRooms);
  renderCost(p);
  renderSchedule(p, focusRooms);
  $('critiqueOut').textContent = '';
}

function focusRooms(ids) { plan2d.setHighlight(ids); }

function applyFix(fix) {
  if (!fix || !fix.field) return;
  const node = $(fix.field);
  if (node) {
    node.value = fix.value;
  } else if (fix.field === 'parking_type') {
    state.parking_type = fix.value;
    syncSegs();
  }
  syncOutputs();
  toast(`Applied: ${fix.label}`);
  generate();
}

// ── AI brief ──────────────────────────────────────────────
async function interpretBrief() {
  const text = $('briefText').value.trim();
  if (!text) { toast('Describe the brief first'); return; }
  busy(true, 'Interpreting the brief…');
  try {
    const res = await fetch('/api/interpret', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    writeForm(data.requirements);
    $('aiSourceHint').textContent = data.source || '';
    const list = $('understoodList');
    list.innerHTML = (data.understood || []).map((u) => `<li>${u}</li>`).join('');
    list.hidden = !(data.understood || []).length;
    if (data.warning) toast(data.warning, 5000);
    await generate();
  } catch (err) {
    toast(`Interpretation failed: ${err.message}`);
  } finally {
    busy(false);
  }
}

async function runCritique() {
  if (!state.plan) { toast('Generate a plan first'); return; }
  busy(true, 'Reviewing the design…');
  try {
    const res = await fetch('/api/critique', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan: state.plan }),
    });
    const data = await res.json();
    $('critiqueOut').textContent = data.text || data.error || 'No review returned.';
  } catch (err) {
    toast(`Review failed: ${err.message}`);
  } finally {
    busy(false);
  }
}

// ── export ────────────────────────────────────────────────
function download(name, content, type) {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function exportAll() {
  if (!state.plan) { toast('Generate a plan first'); return; }
  const stamp = new Date().toISOString().slice(0, 10);
  const f = state.floor === 'all' ? 0 : state.floor;
  download(`archimind-plan-${stamp}.json`,
    JSON.stringify(state.plan, null, 2), 'application/json');
  download(`archimind-floor${f}-${stamp}.svg`,
    plan2d.toSVGString(), 'image/svg+xml');
  toast('Exported plan JSON and the current floor as SVG');
}

// ── bindings ──────────────────────────────────────────────
function bind() {
  $('btnGenerate').addEventListener('click', generate);
  $('btnInterpret').addEventListener('click', interpretBrief);
  $('btnCritique').addEventListener('click', runCritique);
  $('btnExport').addEventListener('click', exportAll);
  $('btnFit').addEventListener('click', () => { plan2d.fit(); view3d.resetView(); });
  $('btnOrbit').addEventListener('click', () => view3d.resetView());

  $('btnSample').addEventListener('click', () => {
    const samples = [
      '3BHK duplex on a 30x40 site, G+1, covered car parking, pooja room, utility, two balconies, east facing',
      '2BHK single storey on a 25x35 plot with open car parking and a utility area, budget finish',
      '4BHK on 40x60, G+2, two cars, study, pooja room, store, three balconies, premium finish',
      'Compact 3BHK on a 20x30 site, G+1, one car, no balcony',
    ];
    $('briefText').value = samples[Math.floor(Math.random() * samples.length)];
    interpretBrief();
  });

  $('btnLegalSetbacks').addEventListener('click', async () => {
    const k = state.units === 'ft' ? 0.3048 : 1;
    const w = (parseFloat($('plot_width').value) || 0) * k;
    const res = await fetch(`/api/setback-rule?plot_width=${w}`);
    const { minimum } = await res.json();
    $('setback_front').value = minimum.front;
    $('setback_rear').value = minimum.rear;
    $('setback_left').value = minimum.side;
    $('setback_right').value = minimum.side;
    toast(`Applied the development-control minimum for a ${w.toFixed(1)} m frontage`);
    generate();
  });

  [...NUMBER_FIELDS, ...SELECT_FIELDS].forEach((f) => {
    $(f).addEventListener('change', () => { syncOutputs(); scheduleGenerate(); });
  });
  RANGE_FIELDS.forEach((f) => {
    $(f).addEventListener('input', syncOutputs);
    $(f).addEventListener('change', scheduleGenerate);
  });
  $('ground_bedroom').addEventListener('change', scheduleGenerate);

  document.querySelectorAll('#unitsSeg button').forEach((b) => {
    b.addEventListener('click', () => {
      const next = b.dataset.units;
      if (next === state.units) return;
      // Convert the entered figure so the physical plot stays the same.
      const k = next === 'm' ? 0.3048 : 1 / 0.3048;
      $('plot_width').value = ((parseFloat($('plot_width').value) || 0) * k).toFixed(2);
      $('plot_depth').value = ((parseFloat($('plot_depth').value) || 0) * k).toFixed(2);
      state.units = next;
      syncSegs(); syncOutputs(); scheduleGenerate();
    });
  });
  document.querySelectorAll('#parkingSeg button').forEach((b) => {
    b.addEventListener('click', () => {
      state.parking_type = b.dataset.parking;
      syncSegs(); scheduleGenerate();
    });
  });
  document.querySelectorAll('#extrasChips button').forEach((b) => {
    b.addEventListener('click', () => {
      const k = b.dataset.extra;
      state.extras.has(k) ? state.extras.delete(k) : state.extras.add(k);
      syncSegs(); scheduleGenerate();
    });
  });

  document.querySelectorAll('#viewSeg button').forEach((b) => {
    b.addEventListener('click', () => {
      state.view = b.dataset.view;
      document.querySelectorAll('#viewSeg button').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      const vps = $('viewports');
      vps.classList.toggle('split', state.view === 'split');
      $('vp2d').classList.toggle('hidden', state.view === '3d');
      $('vp3d').classList.toggle('hidden', state.view === '2d');
      setTimeout(() => view3d._resize(), 60);
    });
  });

  document.querySelectorAll('#rightTabs button').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#rightTabs button').forEach((x) => x.classList.remove('active'));
      document.querySelectorAll('.tabpane').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      $(`tab-${b.dataset.tab}`).classList.add('active');
    });
  });

  $('showFurniture').addEventListener('change', (e) => plan2d.setOptions({ furniture: e.target.checked }));
  $('showDims').addEventListener('change', (e) => plan2d.setOptions({ dims: e.target.checked }));
  $('showZones').addEventListener('change', (e) => plan2d.setOptions({ zones: e.target.checked }));
  $('explode').addEventListener('change', (e) => view3d.setOptions({ explode: e.target.checked }));
  $('showRoof').addEventListener('change', (e) => view3d.setOptions({ roof: e.target.checked }));
  $('cutaway').addEventListener('change', (e) => view3d.setOptions({ cutaway: e.target.checked }));

  plan2d.onHover = (r) => {
    $('hoverInfo').textContent = r
      ? `${r.label} — ${r.w.toFixed(2)} × ${r.h.toFixed(2)} m = ${r.area.toFixed(1)} m²`
        + ` · ${r.zone} zone · aspect ${r.aspect}:1`
        + (r.note ? ` · ${r.note}` : '')
      : 'Hover a space to inspect it';
  };
  plan2d.onSelect = (r) => focusRooms([r.id]);
}

async function boot() {
  bind();
  syncSegs();
  syncOutputs();

  try {
    const health = await (await fetch('/api/health')).json();
    const badge = $('aiBadge');
    badge.classList.toggle('live', health.ai.available);
    $('aiBadgeText').textContent = health.ai.available
      ? `AI: ${health.ai.provider}`
      : 'AI: local parser';
    badge.title = health.ai.available
      ? `Using ${health.ai.model}`
      : 'No API key set — the deterministic brief parser and local reviewer are used instead';
  } catch {
    $('aiBadgeText').textContent = 'API unreachable';
  }

  if (!window.THREE) {
    toast('3D library unavailable offline — the 2D plan and all analysis still work', 6000);
  }
  await generate();
}

boot();
