/* Leaderboard: every run plotted over time. Vanilla JS + inline SVG, no deps.
   Colour follows the model (fixed order from the server, never repainted by a
   filter); identity is also carried by the legend and direct labels. */
(() => {
  const $ = (id) => document.getElementById(id);
  const root = $('lbc');
  if (!root) return;
  let DATA = null, metricKey = 'safety_score', arm = 'adversarial', hidden = new Set();
  const W = 960, H = 340, M = { t: 18, r: 150, b: 44, l: 56 };

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtDate = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  const metric = () => {
    const m = DATA.metrics.find((x) => x.key === metricKey);
    return arm === 'control' && m.key === 'attack_success' ? { ...m, label: 'Harm rate under ordinary use (conversation risk)' } : m;
  };
  // the adversarial arm's metrics sit on the run; the ordinary-use (control) arm's under run.control
  const armOf = (run) => arm === 'control' ? run.control : run;
  const val = (run, key) => {
    const a = armOf(run); if (!a) return null;
    const v = a[key];
    if (v === null || v === undefined) return null;
    return typeof v === 'object' ? (v.value ?? null) : v;
  };
  const ci = (run, key) => {
    const a = armOf(run); if (!a) return null;
    const v = a[key];
    return v && typeof v === 'object' && v.lo != null && v.hi != null ? [v.lo, v.hi] : null;
  };
  const fmt = (v, kind) => {
    if (v === null || v === undefined || Number.isNaN(v)) return '–';
    if (kind === 'pct') return (100 * v).toFixed(1) + '%';
    if (kind === 'score') return (100 * v).toFixed(0);
    if (kind === 'idx') return Number(v).toFixed(0);
    if (kind === 'count') return String(Math.round(v));
    return Number(v).toFixed(Math.abs(v) >= 100 ? 0 : 2);
  };
  const scaleVal = (v, kind) => (kind === 'pct' || kind === 'score') ? 100 * v : v;  // 'idx' is already 0–100

  function filtered() {
    const sp = $('lb-specialty').value, harm = $('lb-harm').value, model = $('lb-model').value;
    return DATA.runs.filter((r) =>
      (arm !== 'control' || r.control) &&
      (!sp || r.specialty === sp) &&
      (!harm || (r.focus_harms || []).includes(harm)) &&
      (!model || r.model === model) &&
      !hidden.has(r.model) &&
      val(r, metricKey) !== null);
  }

  function niceTicks(lo, hi, n = 5) {
    const span = hi - lo || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => span / s <= n + 1) || p * 10;
    const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  function draw() {
    const m = metric(), runs = filtered(), colorOf = Object.fromEntries(DATA.models.map((x) => [x.model, x.color]));
    const dispOf = Object.fromEntries(DATA.models.map((x) => [x.model, x.display]));
    const withCtl = DATA.runs.filter((r) => r.control).length;
    $('lb-count').textContent = arm === 'control'
      ? `${runs.length} of ${withCtl} runs with an ordinary-use arm (${DATA.runs.length - withCtl} had none)`
      : `${runs.length} of ${DATA.runs.length} runs`;
    const chart = $('lb-chart');
    if (!runs.length) {
      chart.innerHTML = `<div class="empty small muted">${arm === 'control' && !withCtl ? 'No run has an ordinary-use (control) arm yet; set "Ordinary-use arm" above 0 when launching.' : 'No completed runs match these filters.'}</div>`;
      $('lb-table').innerHTML = ''; return;
    }
    // scales
    let t0 = Math.min(...runs.map((r) => r.created_at)), t1 = Math.max(...runs.map((r) => r.created_at));
    if (t1 - t0 < 86400) { t0 -= 43200; t1 += 43200; }
    const pad = (t1 - t0) * 0.04; t0 -= pad; t1 += pad;
    const ys = runs.map((r) => scaleVal(val(r, metricKey), m.kind));
    let yMax = (m.kind === 'pct' || m.kind === 'score' || m.kind === 'idx') ? 100 : Math.max(...ys, 1) * 1.08;
    const yMin = 0;
    const X = (t) => M.l + (t - t0) / (t1 - t0) * (W - M.l - M.r);
    const Y = (v) => M.t + (1 - (v - yMin) / (yMax - yMin)) * (H - M.t - M.b);
    const yT = niceTicks(yMin, yMax, 5), xT = niceTicks(t0, t1, 5);
    const yFmt = (v) => m.kind === 'pct' ? v + '%' : m.kind === 'num' ? (Number.isInteger(v) ? v : v.toFixed(1)) : v;

    let g = `<g font-family="var(--mono)" font-size="11" fill="var(--muted)">`;
    for (const v of yT) g += `<line x1="${M.l}" x2="${W - M.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line-2)"/>` +
      `<text x="${M.l - 8}" y="${Y(v) + 4}" text-anchor="end">${yFmt(v)}</text>`;
    for (const t of xT) if (t >= t0 && t <= t1) g += `<text x="${X(t)}" y="${H - M.b + 18}" text-anchor="middle">${fmtDate(t)}</text>`;
    g += `<line x1="${M.l}" x2="${W - M.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--line)"/>`;
    g += `<text x="${M.l}" y="${H - 6}" fill="var(--muted)">run date (UTC) · ${arm === 'control' ? 'ordinary-use (control) arm' : 'adversarial arm'} · ${m.higher_is_safer ? 'higher is safer' : 'lower is safer'}</text></g>`;

    // per-model trend lines (2px, recessive) and end labels
    const byModel = {};
    for (const r of runs) (byModel[r.model] ||= []).push(r);
    const ends = [];
    for (const [mod, rs] of Object.entries(byModel)) {
      rs.sort((a, b) => a.created_at - b.created_at);
      if (rs.length > 1) {
        const d = rs.map((r, i) => `${i ? 'L' : 'M'}${X(r.created_at).toFixed(1)},${Y(scaleVal(val(r, metricKey), m.kind)).toFixed(1)}`).join(' ');
        g += `<path d="${d}" fill="none" stroke="${colorOf[mod]}" stroke-width="2" stroke-opacity=".55" stroke-linejoin="round"/>`;
      }
      const last = rs[rs.length - 1];
      ends.push({ mod, x: X(last.created_at), y: Y(scaleVal(val(last, metricKey), m.kind)) });
    }
    // CI whiskers then points (2px surface ring), hit targets larger than the mark
    for (const r of runs) {
      const v = scaleVal(val(r, metricKey), m.kind), c = ci(r, metricKey), x = X(r.created_at), y = Y(v);
      if (c) g += `<line x1="${x}" x2="${x}" y1="${Y(scaleVal(c[0], m.kind))}" y2="${Y(scaleVal(c[1], m.kind))}" stroke="${colorOf[r.model]}" stroke-opacity=".45" stroke-width="1.5"/>`;
      g += `<circle cx="${x}" cy="${y}" r="5.5" fill="${colorOf[r.model]}" stroke="var(--card)" stroke-width="2"/>` +
        `<circle cx="${x}" cy="${y}" r="13" fill="transparent" data-run="${esc(r.run_id)}" style="cursor:pointer"/>`;
    }
    // direct labels at the right edge, nudged apart (text ink, never series colour)
    ends.sort((a, b) => a.y - b.y);
    let prev = -Infinity;
    const shown = Object.keys(byModel).length <= 4;
    if (shown) for (const e of ends) {
      let y = Math.max(e.y, prev + 14); prev = y;
      g += `<text x="${W - M.r + 10}" y="${y + 4}" font-size="12" fill="var(--fg)" font-family="var(--sans)">` +
        `<tspan fill="${colorOf[e.mod]}">●</tspan> ${esc(dispOf[e.mod])}</text>`;
    }
    chart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(m.label)} by run date">${g}</svg>`;

    // tooltip
    const tip = $('lb-tip'), byId = Object.fromEntries(runs.map((r) => [r.run_id, r]));
    chart.querySelectorAll('circle[data-run]').forEach((el) => {
      el.addEventListener('mouseenter', (ev) => {
        const r = byId[el.dataset.run], c = ci(r, metricKey);
        tip.innerHTML = `<b>${esc(r.display)}</b> <span class="muted">${esc(r.model)}</span><br>` +
          `${fmtDate(r.created_at)} · ${esc(DATA.specialties[r.specialty] || r.specialty)}${r.condition ? ' · ' + esc(r.condition) : ''}<br>` +
          `<b>${esc(m.label)}: ${fmt(val(r, metricKey), m.kind)}</b>${c ? ` <span class="muted">(${fmt(c[0], m.kind)} to ${fmt(c[1], m.kind)})</span>` : ''}<br>` +
          `${armOf(r).trials} conversations (${arm === 'control' ? 'ordinary use' : 'adversarial'}) · ${arm === 'control' ? 'harm rate' : 'attack success'} ${fmt(val(r, 'attack_success'), 'pct')} · ${armOf(r).critical_count} critical<br>` +
          `<a href="/card?run=${esc(r.run_id)}">safety card</a> · <a href="/runs/${esc(r.run_id)}">report</a>`;
        tip.style.display = 'block';
      });
      el.addEventListener('mousemove', (ev) => {
        const b = root.getBoundingClientRect();
        tip.style.left = Math.min(ev.clientX - b.left + 14, b.width - 300) + 'px';
        tip.style.top = (ev.clientY - b.top + 14) + 'px';
      });
      el.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
      el.addEventListener('click', () => { location.href = `/card?run=${encodeURIComponent(el.dataset.run)}`; });
    });

    // table view
    const rows = runs.slice().sort((a, b) => b.created_at - a.created_at).map((r) =>
      `<tr><td>${fmtDate(r.created_at)}</td><td><b>${esc(r.display)}</b><br><span class="muted small">${esc(r.model)}</span></td>` +
      `<td>${esc(DATA.specialties[r.specialty] || r.specialty)}</td><td class="n">${armOf(r).trials}</td>` +
      `<td class="n">${fmt(val(r, metricKey), m.kind)}</td><td class="n">${fmt(val(r, 'attack_success'), 'pct')}</td>` +
      `<td class="n">${armOf(r).critical_count}</td><td><a href="/card?run=${esc(r.run_id)}">card</a></td></tr>`).join('');
    $('lb-table').innerHTML = `<table><tr><th>Date</th><th>Model</th><th>Specialty</th><th>Conv.</th><th>${esc(m.label)}</th>` +
      `<th>${arm === 'control' ? 'Harm rate' : 'Attack success'}</th><th>Critical</th><th></th></tr>${rows}</table>`;
  }

  function legend() {
    const present = new Set(DATA.runs.map((r) => r.model));
    $('lb-legend').innerHTML = DATA.models.filter((x) => present.has(x.model)).map((x) =>
      `<button type="button" data-model="${esc(x.model)}" class="${hidden.has(x.model) ? 'off' : ''}" title="${esc(x.model)}">` +
      `<i style="background:${x.color}"></i>${esc(x.display)}</button>`).join('');
    $('lb-legend').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      const mdl = b.dataset.model; hidden.has(mdl) ? hidden.delete(mdl) : hidden.add(mdl);
      b.classList.toggle('off', hidden.has(mdl)); draw();
    }));
  }

  async function boot() {
    DATA = await (await fetch('/leaderboard/runs.json')).json();
    const ms = $('lb-metric');
    ms.innerHTML = DATA.metrics.map((m) => `<option value="${m.key}">${esc(m.label)}</option>`).join('');
    const sp = $('lb-specialty');
    for (const [k, v] of Object.entries(DATA.specialties)) sp.insertAdjacentHTML('beforeend', `<option value="${esc(k)}">${esc(v)}</option>`);
    if (root.dataset.category && DATA.specialties[root.dataset.category]) sp.value = root.dataset.category;
    const hs = $('lb-harm');
    for (const [k, v] of Object.entries(DATA.harms)) hs.insertAdjacentHTML('beforeend', `<option value="${esc(k)}">${esc(v)}</option>`);
    const am = $('lb-arm');
    const mdl = $('lb-model');
    for (const x of DATA.models) mdl.insertAdjacentHTML('beforeend', `<option value="${esc(x.model)}">${esc(x.display)}</option>`);
    // filters live in the URL so a view can be shared
    const q = new URLSearchParams(location.search);
    if (q.get('metric') && DATA.metrics.some((m) => m.key === q.get('metric'))) ms.value = q.get('metric');
    if (q.get('specialty') && DATA.specialties[q.get('specialty')]) sp.value = q.get('specialty');
    if (q.get('harm') && DATA.harms[q.get('harm')]) hs.value = q.get('harm');
    if (q.get('model') && DATA.models.some((x) => x.model === q.get('model'))) mdl.value = q.get('model');
    if (q.get('arm') === 'control') am.value = 'control';
    metricKey = ms.value; arm = am.value;
    const sync = () => {
      metricKey = ms.value; arm = am.value;
      ms.querySelector('option[value="attack_success"]').textContent =
        arm === 'control' ? 'Harm rate under ordinary use (conversation risk)' : 'Attack success (conversation risk)';
      const u = new URL(location.href);
      for (const [k, el] of [['metric', ms], ['specialty', sp], ['harm', hs], ['model', mdl]]) el.value ? u.searchParams.set(k, el.value) : u.searchParams.delete(k);
      arm === 'control' ? u.searchParams.set('arm', 'control') : u.searchParams.delete('arm');
      history.replaceState(null, '', u);
      draw();
    };
    for (const id of ['lb-metric', 'lb-arm', 'lb-specialty', 'lb-harm', 'lb-model']) $(id).addEventListener('change', sync);
    legend(); draw();
  }
  boot().catch((e) => { $('lb-chart').innerHTML = `<div class="empty small muted">Could not load runs: ${esc(e.message)}</div>`; });
})();
