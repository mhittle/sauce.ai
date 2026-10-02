/* Workflow launchers — the same components as the main page (config-driven
   specialty/condition, harm categories, kind-dependent target fields, model
   pickers, engine knobs, quota/cost) plus run pickers and progress watchers. */
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
let CFG = null, RUNS = [];
const PICKS = {};   // formId -> role -> [spec]
const POLLS = {};

async function boot() {
  try { CFG = await (await fetch('/config')).json(); } catch (e) { CFG = null; }
  try { RUNS = (await (await fetch('/runs.json')).json()).runs || []; } catch (e) { RUNS = []; }
  $$('form.launch').forEach(form => {
    wireSpecialty(form); wireHarms(form); wireKind(form); buildModelPicks(form); wireLimits(form); wireQuota(form);
  });
  renderRunPicks();
}

// --- specialty → conditions datalist ---------------------------------------
function wireSpecialty(form) {
  const sp = form.querySelector('select[name="specialty"], select[name="category"]');
  const cond = form.querySelector('input[name="condition"]');
  if (!sp || !cond || !CFG) return;
  const dl = document.createElement('datalist'); dl.id = form.id + '-conditions'; form.appendChild(dl);
  cond.setAttribute('list', dl.id);
  const sync = () => {
    const s = CFG.specialties.find(x => x.key === sp.value);
    dl.innerHTML = (s ? s.conditions : []).map(c => `<option value="${c}">`).join('');
  };
  sp.addEventListener('change', sync); sync();
}

// --- harm categories ---------------------------------------------------------
function wireHarms(form) {
  const box = form.querySelector('[data-harms]');
  if (!box || !CFG) return;
  box.innerHTML = '';
  Object.entries(CFG.harm_categories).forEach(([k, v]) => {
    const l = document.createElement('label');
    l.innerHTML = `<input type="checkbox" name="focus_harms" data-t="multi" value="${k}"> ${k.replace(/_/g, ' ')}`;
    l.title = v; box.appendChild(l);
  });
}

// --- target kind → which fields show -------------------------------------------
function wireKind(form) {
  const kind = form.querySelector('select[name="target.kind"]');
  if (!kind) return;
  const sync = () => $$('[data-when]', form).forEach(el =>
    el.style.display = el.dataset.when.split(' ').includes(kind.value) ? '' : 'none');
  kind.addEventListener('change', sync); sync();
  const dl = form.querySelector('datalist[data-modelids]');
  if (dl && CFG) dl.innerHTML = [...new Set((CFG.model_catalog || []).map(m => m.model))].map(id => `<option value="${id}">`).join('');
}

// --- model pickers (attacker / arbiter / judge) --------------------------------
function buildModelPicks(form) {
  const boxes = $$('.modelpick', form);
  if (!boxes.length) return;
  PICKS[form.id] = {};
  const byProv = {};
  ((CFG && CFG.model_catalog) || []).forEach(m => (byProv[m.provider] = byProv[m.provider] || []).push(m));
  const defaults = (CFG && CFG.defaults) || {};
  boxes.forEach(box => {
    const role = box.dataset.role; PICKS[form.id][role] = [];
    const sel = document.createElement('select'); sel.className = 'pick';
    sel.add(new Option('Add a model…', ''));
    Object.entries(byProv).forEach(([prov, models]) => {
      const og = document.createElement('optgroup'); og.label = prov;
      models.forEach(m => { const o = new Option(m.available ? m.label : m.label + ' — no key set', m.spec); o.disabled = !m.available; og.appendChild(o); });
      sel.appendChild(og);
    });
    sel.add(new Option('Custom — enter manually…', '__custom__'));
    const custom = document.createElement('input'); custom.className = 'custom'; custom.placeholder = 'provider:model';
    const add = document.createElement('button'); add.type = 'button'; add.className = 'sec add'; add.textContent = 'Add';
    box.innerHTML = '<div class="chips"></div>';
    const addrow = document.createElement('div'); addrow.className = 'addrow'; addrow.append(sel, custom, add); box.append(addrow);
    const phint = document.createElement('div'); phint.className = 'phint small muted'; box.append(phint);
    const addSpec = spec => { spec = (spec || '').trim(); if (spec && !PICKS[form.id][role].includes(spec)) PICKS[form.id][role].push(spec); renderPick(form, role, defaults); };
    sel.onchange = () => { if (sel.value === '__custom__') { custom.style.display = 'block'; custom.focus(); } else { custom.style.display = 'none'; if (sel.value) addSpec(sel.value); sel.value = ''; } };
    add.onclick = () => { if (custom.style.display !== 'none' && custom.value.trim()) { addSpec(custom.value); custom.value = ''; custom.style.display = 'none'; } else if (sel.value && sel.value !== '__custom__') { addSpec(sel.value); sel.value = ''; } };
    custom.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); add.onclick(); } };
    renderPick(form, role, defaults);
  });
  const prov = form.querySelector('[data-providers]');
  if (prov && CFG) prov.textContent = CFG.available_providers.length
    ? 'Provider keys configured on the server: ' + CFG.available_providers.join(', ') + '. Models from other providers need their key set server-side.'
    : 'Only the default (server-configured) provider is available; other providers need their API keys set server-side.';
}
function renderPick(form, role, defaults) {
  const box = form.querySelector(`.modelpick[data-role="${role}"]`); const chips = box.querySelector('.chips'); chips.innerHTML = '';
  PICKS[form.id][role].forEach(spec => {
    const c = document.createElement('span'); c.className = 'chip'; c.textContent = spec;
    const x = document.createElement('button'); x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', 'remove ' + spec);
    x.onclick = () => { PICKS[form.id][role] = PICKS[form.id][role].filter(s => s !== spec); renderPick(form, role, defaults); };
    c.appendChild(x); chips.appendChild(c);
  });
  box.querySelector('.phint').textContent = PICKS[form.id][role].length ? '' : 'Using default: ' + ((defaults[role] || []).join(', ') || 'server default');
}

// --- limits, cost, quota ---------------------------------------------------------
function wireLimits(form) {
  if (!CFG) return;
  const n = form.querySelector('input[name="n_trials"]'), mt = form.querySelector('input[name="max_turns"]');
  if (n) n.max = CFG.limits.free_trial_limit;
  if (mt) mt.max = CFG.limits.max_turns_cap;
  const cost = form.querySelector('[data-cost]'); const price = CFG.limits.price_per_trial_usd;
  if (n && cost && price > 0) { const f = () => cost.textContent = `≈ $${(price * (+n.value || 0)).toFixed(2)}`; n.addEventListener('input', f); f(); }
  const lim = form.querySelector('[data-limit]'); if (lim) lim.textContent = CFG.limits.free_trial_limit;
}
function wireQuota(form) {
  const email = form.querySelector('input[name="email"]'), out = form.querySelector('[data-quota]');
  if (!email || !out) return;
  email.addEventListener('change', async () => {
    const e = email.value.trim(); if (!e.includes('@')) { out.textContent = ''; return; }
    try { const q = await (await fetch('/quota/' + encodeURIComponent(e))).json(); out.textContent = `${q.remaining} of ${q.limit} free trials remaining for this email.`; } catch (err) { }
  });
}

// --- run pickers -----------------------------------------------------------------
function runLabel(r) {
  const bits = [r.specialty, r.condition, 'n=' + r.n_trials, 'seed ' + r.seed, r.status === 'complete' ? '' : r.status].filter(Boolean);
  return `<b>${esc(r.label)}</b> <span class="meta">· ${esc(bits.join(' · '))} · ${r.run_id.slice(0, 8)}</span>`;
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function renderRunPicks() {
  $$('.runpick').forEach(box => {
    const multi = box.hasAttribute('data-runs'); const name = box.dataset.name; const list = box.querySelector('.list');
    const filter = box.querySelector('input[type=search]');
    const draw = () => {
      const q = (filter.value || '').toLowerCase();
      const rows = RUNS.filter(r => !q || JSON.stringify(r).toLowerCase().includes(q));
      list.innerHTML = rows.length ? rows.map(r =>
        `<label><input type="${multi ? 'checkbox' : 'radio'}" name="${name}" data-t="${multi ? 'runs' : 'run'}" value="${r.run_id}"${box.dataset.path ? ' data-path="1"' : ''}> <span>${runLabel(r)}</span></label>`).join('')
        : '<div class="empty">' + (RUNS.length ? 'no runs match' : 'no runs yet — launch one from "Run an evaluation"') + '</div>';
    };
    filter.oninput = draw;
    const all = box.querySelector('[data-all]'), none = box.querySelector('[data-none]');
    if (all) all.onclick = () => $$('input', list).forEach(i => i.checked = true);
    if (none) none.onclick = () => $$('input', list).forEach(i => i.checked = false);
    draw();
  });
}

// --- collect + launch --------------------------------------------------------------
function setDeep(obj, name, v) { const parts = name.split('.'); let o = obj; parts.slice(0, -1).forEach(p => { o[p] = o[p] || {}; o = o[p]; }); o[parts[parts.length - 1]] = v; }
function collect(form) {
  const body = {}; let path = form.dataset.p; const multi = {};
  $$('[name]', form).forEach(el => {
    if (el.closest('[data-when]') && el.closest('[data-when]').style.display === 'none') return;  // hidden by target kind
    const t = el.dataset.t || el.type; let v;
    if (t === 'multi' || t === 'runs' || t === 'models') { if (el.checked) (multi[el.name] = multi[el.name] || []).push(el.value); return; }
    if (t === 'run') { if (!el.checked) return; v = el.value; }
    else if (t === 'checkbox') { v = el.checked; }
    else if (t === 'number') { if (el.value === '') return; v = Number(el.value); }
    else if (t === 'list') { v = el.value.split(',').map(s => s.trim()).filter(Boolean); if (!v.length) return; }
    else if (t === 'bool') { v = el.value === 'true'; }
    else { v = el.value; if (v === '') return; }
    if (el.dataset.path) { path = path.replace('{' + el.name + '}', encodeURIComponent(v)); return; }
    setDeep(body, el.name, v);
  });
  Object.entries(multi).forEach(([k, v]) => { if (v.length || k === 'runs') setDeep(body, k, v); });
  const picks = PICKS[form.id] || {};
  if (picks.attackers && picks.attackers.length) setDeep(body, 'orchestration.attackers', picks.attackers.slice());
  if (picks.arbiters && picks.arbiters.length) setDeep(body, 'orchestration.arbiters', picks.arbiters.slice());
  if (picks.judges && picks.judges.length) body.judges = picks.judges.slice();
  return { path, body };
}
function fill(tpl, j) { return tpl.replace(/\{(\w+)\}/g, (m, k) => j[k] !== undefined ? encodeURIComponent(j[k]) : m); }

async function launch(ev) {
  ev.preventDefault(); const form = ev.target; const { path, body } = collect(form);
  const out = form.querySelector('.result'), status = form.querySelector('.status-line'); out.innerHTML = ''; status.textContent = '';
  if (path.includes('{')) { out.innerHTML = '<span class="err">choose a run first</span>'; return false; }
  if (form.dataset.m === 'GET') {
    const q = new URLSearchParams(); Object.entries(body).forEach(([k, v]) => { if (Array.isArray(v)) { if (v.length) q.set(k, v.join(',')); } else if (typeof v === 'object') { } else q.set(k, v); });
    if (form.querySelector('[data-runs]') && !(body.runs || []).length) { out.innerHTML = '<span class="err">pick at least one run</span>'; return false; }
    const url = path + (q.toString() ? '?' + q.toString() : ''); window.open(url, '_blank');
    out.innerHTML = `opened <a href="${url}" target="_blank">${esc(url)}</a>`; return false;
  }
  const btn = form.querySelector('button[type=submit]'); btn.disabled = true; status.textContent = 'launching…';
  try {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { out.innerHTML = '<span class="err">' + esc(j.detail ? (typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)) : r.status) + '</span>'; status.textContent = ''; btn.disabled = false; return false; }
    status.textContent = 'launched';
    let links = '';
    if (form.dataset.result && !fill(form.dataset.result, j).includes('{')) links += `<a target="_blank" href="${fill(form.dataset.result, j)}">open result →</a>`;
    if (Array.isArray(j.skipped) && j.skipped.length) links += '<div class="muted small">skipped: ' + esc(j.skipped.map(s => s.display + ' (' + s.reason + ')').join(', ')) + '</div>';
    out.innerHTML = links + '<details><summary class="small muted">response</summary><pre>' + esc(JSON.stringify(j, null, 1)) + '</pre></details>';
    const ids = j.run_id ? [{ run_id: j.run_id, label: 'run' }] : (Array.isArray(j.runs) ? j.runs.filter(x => x.run_id) : []);
    if (ids.length) watchRuns(form, ids, j);
    try { RUNS = (await (await fetch('/runs.json')).json()).runs || []; renderRunPicks(); } catch (e) { }
  } catch (e) { out.innerHTML = '<span class="err">' + esc(e) + '</span>'; status.textContent = ''; }
  btn.disabled = false; return false;
}

// --- progress watchers (same as the main page, one per created run) -------------------
function watchRuns(form, ids, resp) {
  const holder = form.querySelector('.result');
  ids.forEach(x => {
    const id = x.run_id; const box = document.createElement('div'); box.className = 'status'; box.id = 'st-' + id;
    box.innerHTML = `<h4>${esc(x.display || x.arm || x.label || 'run')} <span class="muted">${id}</span></h4>
      <div class="msg small">Queued…</div><div class="bar"><div></div></div>
      <p class="small" style="margin:4px 0 0"><a href="/runs/${id}" target="_blank">Open live report ↗</a> · <a href="/runs/${id}/export" target="_blank">JSON export</a> ·
      <button class="sec sm" type="button" data-cancel>Cancel</button></p><div class="headline small"></div>`;
    holder.appendChild(box);
    box.querySelector('[data-cancel]').onclick = () => fetch('/runs/' + id + '/cancel', { method: 'POST' });
    clearInterval(POLLS[id]);
    POLLS[id] = setInterval(async () => {
      let s; try { s = await (await fetch('/runs/' + id + '/status')).json(); } catch (e) { return; }
      const pct = Math.round(100 * s.completed_trials / Math.max(1, s.n_trials));
      box.querySelector('.bar>div').style.width = pct + '%';
      box.querySelector('.msg').innerHTML = { queued: 'Queued…', running: `Running — ${s.completed_trials}/${s.n_trials} trials (${pct}%)`,
        complete: 'Complete. ' + (s.emailed ? 'Report emailed.' : 'Report ready.'), failed: `<span class="err">Failed: ${esc(s.error || '')}</span>` }[s.status] || s.status;
      if (s.headline) box.querySelector('.headline').innerHTML = `Conversations reaching a harmful reply: <b>${s.headline.trials_with_harm}</b> · harmful replies: <b>${s.headline.harmful_responses}</b>`;
      if (s.status === 'complete' || s.status === 'failed') { clearInterval(POLLS[id]); try { RUNS = (await (await fetch('/runs.json')).json()).runs || []; renderRunPicks(); } catch (e) { } }
    }, 3000);
  });
  if (resp && resp.field_id) { const a = document.createElement('p'); a.className = 'small'; a.innerHTML = `Field report (updates as runs finish): <a target="_blank" href="/field?field=${resp.field_id}">/field?field=${resp.field_id}</a>`; holder.appendChild(a); }
}
document.addEventListener('DOMContentLoaded', boot);
