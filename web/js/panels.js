/**
 * Right-hand analysis panels: metrics, validation findings, score breakdown,
 * cost table and room schedule.
 *
 * Every panel renders straight from the plan payload. Nothing is recomputed in
 * the browser, so what the user reads is exactly what the engine decided.
 */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const inr = (n) => '₹' + Math.round(n).toLocaleString('en-IN');
const SEV_ORDER = { error: 0, warning: 1, info: 2, pass: 3 };
const SEV_LABEL = { error: 'Must fix', warning: 'Review', info: 'Notes', pass: 'Passed' };

export function renderMetrics(plan) {
  const m = plan.metrics;
  const cells = [
    ['Plot', `${m.plot_area.toFixed(1)} m²`, `${m.plot_area_sqft.toFixed(0)} sq ft`],
    ['Built-up', `${m.builtup_area.toFixed(1)} m²`, `${m.builtup_area_sqft.toFixed(0)} sq ft`],
    ['Carpet', `${m.carpet_area.toFixed(1)} m²`, `${(m.efficiency * 100).toFixed(0)}% efficient`],
    ['Coverage', `${(m.coverage * 100).toFixed(1)}%`, `limit ${(plan.requirements.max_coverage * 100).toFixed(0)}%`],
    ['FAR', m.far.toFixed(2), `limit ${plan.requirements.max_far.toFixed(2)}`],
    ['Open space', `${(m.open_space * 100).toFixed(0)}%`, `${m.site_work_area.toFixed(0)} m²`],
  ];
  $('metricsStrip').innerHTML = cells.map(([k, v, s]) => `
    <div class="metric"><div class="k">${esc(k)}</div>
      <div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('');
}

export function renderValidation(plan, onFocus, onFix) {
  const host = $('validationList');
  const findings = plan.validation.findings;
  const groups = { error: [], warning: [], info: [], pass: [] };
  findings.forEach((f) => groups[f.severity].push(f));

  host.innerHTML = Object.entries(groups)
    .filter(([, list]) => list.length)
    .sort((a, b) => SEV_ORDER[a[0]] - SEV_ORDER[b[0]])
    .map(([sev, list]) => `
      <div class="group-head">${SEV_LABEL[sev]} · ${list.length}</div>
      ${list.map((f) => card(f)).join('')}`).join('');

  host.querySelectorAll('.finding').forEach((node) => {
    const id = node.dataset.id;
    const f = findings.find((x) => x.id === id);
    node.addEventListener('mouseenter', () => onFocus && onFocus(f.rooms));
    node.addEventListener('mouseleave', () => onFocus && onFocus([]));
  });
  host.querySelectorAll('.fixbtn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      onFix && onFix(JSON.parse(btn.dataset.fix));
    });
  });

  const errs = groups.error.length;
  $('tabBadge').textContent = errs ? String(errs) : '';
}

function card(f) {
  const metric = (f.value !== null && f.limit !== null && f.unit)
    ? `<span class="code">${f.value} / ${f.limit} ${esc(f.unit)}</span>` : '';
  const fix = f.fix
    ? `<button class="btn small ghost fixbtn" data-fix='${esc(JSON.stringify(f.fix))}'>${esc(f.fix.label)}</button>`
    : '';
  return `
    <div class="finding ${f.severity}" data-id="${f.id}">
      <div class="ft"><h4>${esc(f.title)}</h4><span class="cat">${esc(f.category)}</span></div>
      <p>${esc(f.message)}</p>
      ${f.suggestion ? `<p class="sugg">${esc(f.suggestion)}</p>` : ''}
      <div class="ft" style="margin-top:5px">
        <span class="code">${esc(f.code)}</span>${metric}
      </div>
      ${fix}
    </div>`;
}

export function renderScore(plan, onFocus) {
  const s = plan.score;
  const why = {
    relationships: 'Required and preferred adjacencies between spaces',
    feasibility: 'Every room meets its minimum area and clear width',
    proportion: 'Rooms stay within a workable length-to-width ratio',
    area_fit: 'Delivered areas match the programme budget',
    daylight: 'Habitable rooms reach an external wall',
    privacy: 'Bedrooms do not open off the entrance or parking',
    circulation: 'Every space is reachable through a door',
  };

  $('scoreBreakdown').innerHTML = `
    <div class="cost-head">
      <div class="big">${s.total.toFixed(1)} / 100</div>
      <div class="sub">Layout quality, weighted across ${Object.keys(s.parts).length}
        criteria. Search seed #${s.seed}.</div>
    </div>
    ${Object.entries(s.parts).map(([k, v]) => {
    const cls = v >= 80 ? 'good' : v >= 55 ? 'mid' : 'bad';
    const w = (s.weights[k] * 100).toFixed(0);
    return `<div class="bar-row">
        <div class="bl"><span>${esc(k.replace('_', ' '))} <span class="code">${w}% weight</span></span>
          <b>${v.toFixed(0)}</b></div>
        <div class="bar"><i class="${cls}" style="width:${Math.max(2, v)}%"></i></div>
        <div class="why">${esc(why[k] || '')}</div>
      </div>`;
  }).join('')}`;

  const rel = plan.relationships;
  const byId = Object.fromEntries(plan.rooms.map((r) => [r.id, r.label]));
  const row = (item, required) => `
    <div class="finding ${item.satisfied ? 'pass' : (required ? 'error' : 'warning')}"
         data-rooms='${esc(JSON.stringify(item.rooms))}'>
      <div class="ft"><h4>${item.satisfied ? '✓' : '✗'} ${esc(item.label)}</h4>
        <span class="cat">L${item.floor}</span></div>
      <p>${esc(item.why)}</p>
      <span class="code">${esc(item.rooms.map((r) => byId[r] || r).join(' · '))}</span>
    </div>`;

  $('relationshipList').innerHTML = `
    <div class="group-head">Required relationships · ${rel.required_satisfied}/${rel.required_total}</div>
    ${rel.required.map((i) => row(i, true)).join('')}
    ${rel.preferred.length ? `<div class="group-head">Preferred relationships</div>
      ${rel.preferred.map((i) => row(i, false)).join('')}` : ''}
    ${rel.violations.length ? `<div class="group-head">Conflicts · ${rel.violations.length}</div>
      ${rel.violations.map((v) => `
        <div class="finding error" data-rooms='${esc(JSON.stringify([v.a, v.b]))}'>
          <div class="ft"><h4>✗ ${esc(byId[v.a] || v.a)} ↔ ${esc(byId[v.b] || v.b)}</h4>
            <span class="cat">L${v.floor}</span></div>
          <p>${esc(v.why)}</p></div>`).join('')}` : ''}`;

  $('relationshipList').querySelectorAll('[data-rooms]').forEach((n) => {
    const ids = JSON.parse(n.dataset.rooms);
    n.addEventListener('mouseenter', () => onFocus && onFocus(ids));
    n.addEventListener('mouseleave', () => onFocus && onFocus([]));
  });
}

export function renderCost(plan) {
  const c = plan.cost;
  $('costSummary').innerHTML = `
    <div class="cost-head">
      <div class="big">${inr(c.grand_total)}</div>
      <div class="sub">${inr(c.per_sqft)} per sq ft · ${inr(c.per_sqm)} per m²<br>
        likely range ${inr(c.range_low)} – ${inr(c.range_high)}<br>
        ${esc(c.quality_label)} specification · ${esc(c.city_label)}</div>
    </div>`;

  $('costTable').innerHTML = `
    <table>
      <thead><tr><th>Item</th><th class="num">Quantity × rate</th><th class="num">Amount</th></tr></thead>
      <tbody>
        ${c.items.map((i) => `
          <tr>
            <td><b>${esc(i.label)}</b>
              <details class="formula"><summary>${esc(i.formula)}</summary>
                <p>${esc(i.basis)}<br>${esc(i.note)}</p></details></td>
            <td class="num">${i.quantity.toLocaleString('en-IN')}<br>
              <span class="code">@ ${inr(i.applied_rate)}</span></td>
            <td class="num">${inr(i.amount)}</td>
          </tr>`).join('')}
        <tr class="total"><td>Direct construction cost</td><td></td>
          <td class="num">${inr(c.direct_total)}</td></tr>
        ${c.addons.map((a) => `
          <tr><td><b>${esc(a.label)}</b>
            <details class="formula"><summary>${esc(a.formula)}</summary>
              <p>${esc(a.note)}</p></details></td>
            <td class="num">${(a.pct * 100).toFixed(1)}%</td>
            <td class="num">${inr(a.amount)}</td></tr>`).join('')}
        <tr class="total"><td>Total project cost</td><td></td>
          <td class="num">${inr(c.grand_total)}</td></tr>
      </tbody>
    </table>
    <ul class="assump">${c.assumptions.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>`;
}

export function renderSchedule(plan, onFocus) {
  const byLevel = {};
  plan.rooms.forEach((r) => { (byLevel[r.floor] ||= []).push(r); });

  $('roomSchedule').innerHTML = Object.entries(byLevel).map(([lvl, rooms]) => {
    const total = rooms.reduce((s, r) => s + r.area, 0);
    const level = plan.levels.find((l) => l.level === +lvl);
    return `
      <div class="group-head">${esc(level ? level.name : `Level ${lvl}`)} · ${rooms.length} spaces · ${total.toFixed(1)} m²</div>
      <table>
        <thead><tr><th>Space</th><th class="num">Size (m)</th><th class="num">Area</th><th class="num">vs brief</th></tr></thead>
        <tbody>
          ${rooms.sort((a, b) => b.area - a.area).map((r) => {
      const delta = r.target_area > 0 ? ((r.area - r.target_area) / r.target_area * 100) : 0;
      const flag = r.area < r.min_area - 0.01 || Math.min(r.w, r.h) < r.min_dim - 0.01;
      return `<tr data-room="${r.id}" ${flag ? 'style="color:var(--err)"' : ''}>
              <td>${esc(r.label)}<br><span class="code">${esc(r.type)}</span></td>
              <td class="num">${r.w.toFixed(2)} × ${r.h.toFixed(2)}</td>
              <td class="num">${r.area.toFixed(1)} m²</td>
              <td class="num">${delta >= 0 ? '+' : ''}${delta.toFixed(0)}%</td>
            </tr>`;
    }).join('')}
        </tbody>
      </table>`;
  }).join('');

  $('roomSchedule').querySelectorAll('[data-room]').forEach((n) => {
    n.addEventListener('mouseenter', () => onFocus && onFocus([n.dataset.room]));
    n.addEventListener('mouseleave', () => onFocus && onFocus([]));
  });
}

export function renderHeader(plan) {
  const s = plan.score.total;
  $('scoreVal').textContent = s.toFixed(0);
  const v = plan.validation;
  const pill = $('compliancePill');
  const errs = v.counts.error;
  pill.className = 'status-pill ' + (errs ? 'err' : 'ok');
  $('complianceText').textContent = errs
    ? `${errs} issue${errs > 1 ? 's' : ''} to fix`
    : `${v.counts.pass} checks passed`;
  $('timing').textContent =
    `solved in ${plan.timing_ms} ms · seed ${plan.score.seed} · ${plan.rooms.length} spaces`;
}
