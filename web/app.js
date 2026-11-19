// Barndo Planner front-end (no build step).
const $ = (s, el = document) => el.querySelector(s);
const form = $('#form');
let CONFIG = null;
let current = null;   // currently open layout id

const money = (v) => '$' + Math.round(v).toLocaleString();

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join('; ') : data.detail;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return data;
}

function show(el, html, kind = '') {
  el.hidden = !html;
  el.className = 'msg' + (kind ? ' ' + kind : '');
  el.innerHTML = html || '';
}

// ---------------------------------------------------------------- form <-> requirements
function fillForm(req) {
  const fp = `${req.building_width}x${req.building_length}`;
  const sel = $('#footprint');
  sel.value = [...sel.options].some((o) => o.value === fp) ? fp : 'custom';
  $('#custom-size').hidden = sel.value !== 'custom';
  for (const [k, v] of Object.entries(req)) {
    const el = form.elements[k];
    if (!el) continue;
    if (k === 'laundry') { el.checked = !!(req.laundry || req.mudroom); continue; }
    if (el.type === 'checkbox') el.checked = !!v;
    else el.value = v ?? '';
  }
}

function readForm() {
  const f = form.elements;
  const num = (n, d = 0) => (f[n].value === '' ? d : Number(f[n].value));
  let w = num('building_width', 40), l = num('building_length', 60);
  const fp = $('#footprint').value;
  if (fp && fp !== 'custom') [w, l] = fp.split('x').map(Number);
  return {
    building_width: w, building_length: l,
    bedrooms: num('bedrooms', 3), full_baths: num('full_baths', 2), half_baths: num('half_baths', 0),
    walk_in_closet: f.walk_in_closet.checked, laundry: f.laundry.checked, pantry: f.pantry.checked,
    mudroom: f.laundry.checked, office: f.office.checked,
    main_entrance: f.main_entrance.value, eave_height: num('eave_height', 12), roof_pitch: num('roof_pitch', 4),
    shop_length: num('shop_length', 0), shop_side: f.shop_side.value, overhead_doors: num('overhead_doors', 1),
    front_porch_depth: num('front_porch_depth', 0), back_porch_depth: num('back_porch_depth', 0),
    budget: f.budget.value === '' ? null : Number(f.budget.value), notes: f.notes.value,
  };
}

// ---------------------------------------------------------------- init
async function init() {
  for (const b of ['#btn-describe', '#btn-generate']) $(b).disabled = true;
  CONFIG = await api('/api/config');
  $('#company').textContent = CONFIG.company;
  document.title = `${CONFIG.company} - Barndo Planner`;
  const sel = $('#footprint');
  for (const [w, l] of CONFIG.footprints) sel.add(new Option(`${w}' x ${l}'  (${(w * l).toLocaleString()} sq ft)`, `${w}x${l}`));
  sel.add(new Option('Custom size...', 'custom'));
  sel.addEventListener('change', () => { $('#custom-size').hidden = sel.value !== 'custom'; });
  fillForm(CONFIG.defaults);
  for (const b of ['#btn-describe', '#btn-generate']) $(b).disabled = false;
  if (CONFIG.dwg) $('#d-dwg').hidden = false;
}

// ---------------------------------------------------------------- AI intake
$('#btn-describe').addEventListener('click', async () => {
  const text = $('#describe').value.trim();
  const msg = $('#intake-msg');
  if (text.length < 3) return show(msg, 'Write a sentence or two about the barndo you want.', 'error');
  const btn = $('#btn-describe');
  btn.disabled = true; btn.textContent = 'Reading your description...';
  try {
    const out = await api('/api/intake', { method: 'POST', body: JSON.stringify({ text, requirements: readForm() }) });
    fillForm(out.requirements);
    let html = '<b>Form updated.</b> Check it, then generate plans.';
    if (out.assumptions?.length) html += '<ul>' + out.assumptions.map((a) => `<li>${esc(a)}</li>`).join('') + '</ul>';
    if (out.questions?.length) html += '<b>Questions for you:</b><ul>' + out.questions.map((q) => `<li>${esc(q)}</li>`).join('') + '</ul>';
    show(msg, html);
    generate();
  } catch (e) {
    show(msg, esc(e.message), 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Fill in my plan';
  }
});

// ---------------------------------------------------------------- generate
form.addEventListener('submit', (e) => { e.preventDefault(); generate(); });

async function generate() {
  const btn = $('#btn-generate');
  const status = $('#status');
  btn.disabled = true; btn.textContent = 'Designing...';
  show(status, 'Assembling layouts from the module library...');
  try {
    const out = await api('/api/layouts', { method: 'POST', body: JSON.stringify(readForm()) });
    $('#empty').hidden = true;
    show(status, '');
    renderGrid(out.layouts);
    if (window.innerWidth < 980) $('#grid').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    show(status, esc(e.message), 'error');
    $('#grid').innerHTML = '';
  } finally {
    btn.disabled = false; btn.textContent = 'Generate floor plans';
  }
}

function renderGrid(layouts) {
  const grid = $('#grid');
  grid.innerHTML = '';
  layouts.forEach((l, i) => {
    const m = l.metrics, e = l.estimate;
    const card = document.createElement('article');
    card.className = 'plan-card';
    card.tabIndex = 0;
    const chips = [
      `<span class="chip">${m.living_sqft.toLocaleString()} sq ft living</span>`,
      m.shop_sqft ? `<span class="chip">${m.shop_sqft.toLocaleString()} sq ft shop</span>` : '',
      `<span class="chip">${m.bedrooms} bed / ${m.full_baths}${m.half_baths ? '.5' : ''} bath</span>`,
      l.rules ? `<span class="chip ${l.rules.failed ? 'bad' : 'good'}">&#10003; ${l.rules.passed}/${l.rules.total} company rules</span>` : '',
      l.rules && l.rules.warnings ? `<span class="chip warn">${l.rules.warnings} warning${l.rules.warnings > 1 ? 's' : ''}</span>` : '',
      e.within_budget === true ? '<span class="chip good">Within budget</span>' : '',
      e.within_budget === false ? '<span class="chip bad">Over budget</span>' : '',
    ].join('');
    card.innerHTML = `
      <div class="thumb">${l.svg}</div>
      <div class="meta">
        <div class="line1"><span class="name">Option ${i + 1}</span><span class="price">${money(e.total)}</span></div>
        <div class="concept">${esc(l.concept || '')}</div>
        <div class="chips">${chips}</div>
        <div class="score">Design score ${l.score} / 100 &middot; Great room ${m.great_room}</div>
        ${l.notes.length ? `<div class="small">${l.notes.map(esc).join(' ')}</div>` : ''}
      </div>`;
    const open = () => openDetail(l.id, i + 1);
    card.addEventListener('click', open);
    card.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') open(); });
    grid.appendChild(card);
  });
}

// ---------------------------------------------------------------- detail
async function openDetail(id, n) {
  current = id;
  const dlg = $('#detail');
  $('#d-title').textContent = `Option ${n}`;
  $('#d-rules').innerHTML = '';
  $('#d-plan').innerHTML = '<p class="small">Loading...</p>';
  $('#d-summary').textContent = '';
  show($('#lead-msg'), '');
  dlg.showModal();
  const l = await api(`/api/layouts/${id}`);
  const m = l.metrics, e = l.estimate;
  $('#d-plan').innerHTML = l.svg;
  $('#d-kpis').innerHTML = [
    [m.footprint, 'building'], [m.living_sqft.toLocaleString(), 'living sq ft'], [m.shop_sqft.toLocaleString(), 'shop sq ft'],
    [`${m.bedrooms} / ${m.full_baths}${m.half_baths ? '.5' : ''}`, 'bed / bath'], [m.great_room, 'great room'], [money(e.total), 'estimate'],
    [`${e.building.eave_height}'`, 'eave height'], [`${e.building.roof_pitch}:12`, 'roof slope'], [`${e.building.ridge_height.toFixed(1)}'`, 'ridge height'],
  ].map(([b, s]) => `<div><b>${esc(String(b))}</b><span>${s}</span></div>`).join('');
  $('#d-title').textContent = `Option ${n} - ${l.concept || ''}`;
  $('#d-rules').innerHTML = (l.rule_checks || []).map((r) =>
    `<li class="${r.status}"><span class="mark">${r.status === 'pass' ? '&#10003;' : r.status === 'warn' ? '!' : '&#10007;'}</span>`
    + `<span><b>${esc(r.id)}. ${esc(r.rule)}</b><br><small>${esc(r.detail)}</small></span></li>`).join('');
  $('#d-notes').innerHTML = l.notes.length ? `<div class="msg">${l.notes.map(esc).join('<br>')}</div>` : '';
  $('#d-est').innerHTML = Object.entries(e.groups).map(([g, v]) => `<tr><td>${esc(g)}</td><td class="n">${money(v)}</td></tr>`).join('')
    + `<tr><td>Contingency</td><td class="n">${money(e.contingency)}</td></tr>`
    + `<tr class="tot"><td>Total</td><td class="n">${money(e.total)}</td></tr>`;
  $('#d-proposal').href = `/proposal/${id}`;
  $('#d-dxf').href = `/api/layouts/${id}/dxf`;
  $('#d-dwg').href = `/api/layouts/${id}/dwg`;
  api(`/api/layouts/${id}/summary`).then((s) => { if (current === id) $('#d-summary').textContent = s.text; }).catch(() => {});
}
$('#d-close').addEventListener('click', () => $('#detail').close());
$('#detail').addEventListener('click', (e) => { if (e.target.id === 'detail') $('#detail').close(); });

// ---------------------------------------------------------------- lead
$('#lead').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const msg = $('#lead-msg');
  try {
    await api('/api/leads', { method: 'POST', body: JSON.stringify({
      name: f.name.value, email: f.email.value, phone: f.phone.value, message: f.message.value, layout_id: current || '' }) });
    show(msg, 'Thanks! Our team will reach out with a quote for this plan.');
    e.target.reset();
  } catch (err) {
    show(msg, esc(err.message), 'error');
  }
});

function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]); }

init().catch((e) => show($('#status'), 'Could not reach the server: ' + esc(e.message), 'error'));
