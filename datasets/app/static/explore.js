// Explore: per-dataset exploration page built from a fixed view library.
// The spec (which views, configured how) comes from /api/explore/{id}; each
// view type below renders the same way on every dataset.
/* global $, el, api, banner, ACCESS_LABEL, escapeHtml */

const EX = { id: null, data: null, poll: null };
const tokenKey = "pahlEditToken";
const C = { ink: "#0A0A0B", muted: "#5C5C62", line: "#DEDEDA", accent: "#2433D9",
            palette: ["#2433D9", "#D9480F", "#1F7A3A", "#9A6400", "#7A2CBF", "#0F7C8C", "#B3261E", "#5C5C62"] };

function exploreAvailable(ds) {
  if (ds.explore_status === "unavailable") return null;
  if (/huggingface\.co\/datasets\//.test(ds.url || "") || (ds.download_urls || []).some(u => /huggingface\.co\/datasets\//.test(u))) return "huggingface";
  if (/physionet\.org\/content\//.test(ds.url || "") && ds.access_type === "open") return "physionet";
  if (/cancerimagingarchive\.net/.test(ds.url || "") && ds.access_type === "open") return "tcia";
  if (/openneuro\.org\/datasets\/ds\d{6}/.test(ds.url || "") && ["open", "unknown"].includes(ds.access_type)) return "openneuro";
  if ((ds.files || []).some(f => f.status === "downloaded")) return "files";
  if (["open", "unknown"].includes(ds.access_type)) return "acquire";
  return null;
}

async function exApi(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  try { const t = localStorage.getItem(tokenKey); if (t) headers["X-Edit-Token"] = t; } catch {}
  try {
    return await api(path, { ...opts, headers });
  } catch (e) {
    if (String(e.message).includes("edit token")) {
      const t = prompt("This action needs the editor token:");
      if (t) { try { localStorage.setItem(tokenKey, t); } catch {} return exApi(path, opts); }
    }
    throw e;
  }
}

async function loadExplore(id) {
  EX.id = id;
  clearTimeout(EX.poll);
  const box = $("#explore");
  const d = await api(`/api/explore/${encodeURIComponent(id)}`);
  EX.data = d;
  const ds = d.dataset;
  const head = el("div", { class: "ex-head" });
  const back = el("a", { href: `#/dataset/${encodeURIComponent(id)}` }, "← Dataset");
  head.append(back, el("h2", {}, `Explore: ${ds.title}`));
  const sub = el("p", { class: "muted small" });
  sub.textContent = [ds.source, ACCESS_LABEL[ds.access_type], d.version ? `version ${d.version}` : "",
    d.source && d.source.via ? `data via ${d.source.via}` : ""].filter(Boolean).join(" · ");
  head.append(sub);
  const parts = [head];

  if (d.busy || d.status === "building") {
    const p = el("div", { class: "panel" });
    p.append(el("h3", {}, "Building the explore page…"));
    p.append(el("p", { class: "muted small" }, "Fetching a sample of the data, reading its structure, and composing views. This takes from a few seconds to a few minutes."));
    const log = el("pre", { class: "log" }, ((d.job && d.job.log) || []).join("\n") || "starting…");
    p.append(log);
    parts.push(p);
    box.replaceChildren(...parts);
    EX.poll = setTimeout(() => { if (location.hash.startsWith(`#/explore/${id}`)) loadExplore(id).catch(e => banner(e.message)); }, 2500);
    return;
  }
  if (!d.spec) {
    const p = el("div", { class: "panel" });
    if (d.status === "unavailable") {
      p.append(el("h3", {}, ""));
      p.append(el("p", { class: "small" }, d.error || ""));
    } else if (d.status === "failed") {
      p.append(el("h3", {}, "Couldn't build an explore page"));
      p.append(el("p", { class: "small" }, d.error || "Unknown error."));
    } else {
      p.append(el("h3", {}, "No explore page yet"));
    }
    const av = d.availability || {};
    if (!av.available) {
      if (d.status === "unavailable") p.firstChild.textContent = "This dataset needs access before it can be explored";
      else p.append(el("p", { class: "small" }, av.reason || "This dataset can't be explored yet."));
      p.append(el("h3", {}, "How to get access"));
      p.append(el("pre", { class: "instructions" }, ds.access_instructions || "See the source page."));
      const src = el("p", { class: "small" }); src.append(el("a", { href: ds.url, target: "_blank", rel: "noopener" }, "Source page →")); p.append(src);
      if (d.status === "unavailable") {
        const again = el("button", { class: "btn link small" }, "Look for open files again");
        again.onclick = async () => { try { await exApi(`/api/explore/${encodeURIComponent(EX.id)}/build`, { method: "POST" }); loadExplore(EX.id); } catch (e) { banner(e.message); } };
        p.append(again);
      }
    } else {
      const how = { huggingface: "read samples through the Hugging Face API", physionet: "stream records from PhysioNet",
                    tcia: "fetch a spread of DICOM series through the TCIA API and render them",
                    openneuro: "fetch EEG recordings or anatomical MRI from OpenNeuro's open bucket",
                    files: "read the files already downloaded", acquire: "look for direct download links and fetch a sample (capped)" }[av.via];
      p.append(el("p", { class: "small" }, `Building will ${how}, then ${d.llm ? "have Claude compose views for this dataset" : "set up default views"}. The page is saved for everyone.`));
      const b = el("button", { class: "btn" }, d.status === "failed" ? "Try again" : "Build explore page");
      b.onclick = async () => { b.disabled = true; try { await exApi(`/api/explore/${encodeURIComponent(id)}/build`, { method: "POST" }); loadExplore(id); } catch (e) { banner(e.message); b.disabled = false; } };
      p.append(b);
    }
    parts.push(p);
    box.replaceChildren(...parts);
    return;
  }

  const spec = d.spec;
  const layout = el("div", { class: "ex-layout" });
  const main = el("div", { class: "ex-main" });
  if (spec.summary) main.append(el("p", { class: "ex-summary" }, spec.summary));
  const ctx = { id, probe: (d.source && d.source.probe) || {}, series: spec.series };
  for (const panel of spec.panels) {
    const card = el("section", { class: `panel ex-panel ex-${panel.type}` });
    card.append(el("h3", {}, panel.title));
    if (panel.description) card.append(el("p", { class: "muted small" }, panel.description));
    const body = el("div", { class: "ex-body" });
    card.append(body);
    main.append(card);
    const fn = VIEWS[panel.type];
    if (fn) fn(body, panel.params || {}, ctx).catch(e => body.append(el("p", { class: "compat-warn" }, `Couldn't load: ${e.message}`)));
  }
  layout.append(main, sidePanel(d));
  parts.push(layout);
  box.replaceChildren(...parts);
}

function chatPanel(d) {
  const p = el("div", { class: "panel ex-chat" });
  p.append(el("h3", {}, "Chat with this dataset"));
  p.append(el("p", { class: "muted small" }, "Ask questions about the data, e.g. “how does systolic pressure differ by hypertension stage?”, “which labels are rare?”, “what could explain the difference between these groups?”. Answers come from queries on the data sample."));
  const log = el("div", { class: "ex-chat-log" });
  const key = `pahlChat:${EX.id}`;
  let history = [];
  try { history = JSON.parse(sessionStorage.getItem(key) || "[]"); } catch {}
  const render = () => {
    log.replaceChildren(...history.map(h => { const m = el("div", { class: `ex-msg ex-${h.role}` }); if (h.role === "assistant") m.innerHTML = miniMarkdown(h.content); else m.textContent = h.content; return m; }));
    log.scrollTop = log.scrollHeight;
  };
  const ta = el("textarea", { rows: "3", placeholder: "Ask about this dataset…" });
  const send = el("button", { class: "btn" }, "Ask");
  const clear = el("button", { class: "btn link small" }, "Clear");
  async function ask() {
    const q = ta.value.trim();
    if (!q) return;
    history.push({ role: "user", content: q }); ta.value = ""; render();
    send.disabled = true; send.textContent = "Thinking…";
    try {
      const r = await exApi(`/api/explore/${encodeURIComponent(EX.id)}/chat`, { method: "POST", body: JSON.stringify({ messages: history.slice(-12) }) });
      history.push({ role: "assistant", content: r.answer + (r.tools_used && r.tools_used.length ? `\n\n_(queried: ${[...new Set(r.tools_used)].join(", ")})_` : "") });
    } catch (e) { history.push({ role: "assistant", content: `Error: ${e.message}` }); }
    try { sessionStorage.setItem(key, JSON.stringify(history.slice(-30))); } catch {}
    send.disabled = false; send.textContent = "Ask"; render();
  }
  send.onclick = ask;
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } });
  clear.onclick = () => { history = []; try { sessionStorage.removeItem(key); } catch {} render(); };
  if (!d.llm) { ta.disabled = true; send.disabled = true; }
  p.append(log, ta, send, clear);
  render();
  return p;
}

function sidePanel(d) {
  const side = el("aside", { class: "ex-side" });
  side.append(chatPanel(d));
  const p = el("div", { class: "panel" });
  p.append(el("h3", {}, "Change this page"));
  p.append(el("p", { class: "muted small" }, "Ask for new views or changes, e.g. “group images by view position”, “spaghetti of accel_z for falls vs walking, 5 s around the event”. Requests the view library can't do yet are logged as tool requests."));
  const ta = el("textarea", { rows: "4", placeholder: "Describe a change or a new exploration tool…" });
  const go = el("button", { class: "btn" }, "Apply");
  const out = el("div", { class: "small ex-reply" });
  if (d.spec.reply) out.textContent = d.spec.reply;
  go.onclick = async () => {
    const prompt = ta.value.trim();
    if (prompt.length < 3) return;
    go.disabled = true; go.textContent = "Working…";
    try {
      const r = await exApi(`/api/explore/${encodeURIComponent(EX.id)}/edit`, { method: "POST", body: JSON.stringify({ prompt }) });
      ta.value = "";
      await loadExplore(EX.id);
      const o = document.querySelector(".ex-reply");
      if (o) o.textContent = r.reply || "Updated.";
    } catch (e) { banner(e.message); go.disabled = false; go.textContent = "Apply"; }
  };
  if (!d.llm) { ta.disabled = true; go.disabled = true; out.textContent = "Editing needs ANTHROPIC_API_KEY on the server."; }
  p.append(ta, go, out);
  side.append(p);

  if ((d.history || []).length) {
    const h = el("div", { class: "panel" });
    h.append(el("h3", {}, "History"));
    for (const v of d.history) {
      const row = el("div", { class: "link-row small" });
      row.append(el("b", {}, `v${v.version} `), document.createTextNode(v.prompt || "initial page"));
      if (v.version !== d.version) {
        const r = el("button", { class: "btn link" }, " restore");
        r.onclick = async () => { await exApi(`/api/explore/${encodeURIComponent(EX.id)}/revert/${v.version}`, { method: "POST" }); loadExplore(EX.id); };
        row.append(r);
      }
      h.append(row);
    }
    side.append(h);
  }
  if ((d.requests || []).length) {
    const q = el("div", { class: "panel" });
    q.append(el("h3", {}, "Requested tools"));
    for (const r of d.requests) q.append(el("div", { class: "link-row small" }, r.request));
    side.append(q);
  }
  const rb = el("button", { class: "btn link small" }, "Rebuild from the data");
  rb.onclick = async () => { if (!confirm("Re-fetch the sample and recompose the page? Edits are kept in History.")) return; await exApi(`/api/explore/${encodeURIComponent(EX.id)}/build`, { method: "POST" }); loadExplore(EX.id); };
  side.append(rb);
  return side;
}

// ------------------------------------------------------------------ charts
function hiDpiCanvas(w, h) {
  const c = el("canvas");
  const r = window.devicePixelRatio || 1;
  c.width = w * r; c.height = h * r; c.style.width = "100%"; c.style.maxWidth = `${w}px`; c.style.height = `${h}px`;
  const g = c.getContext("2d"); g.scale(r, r);
  return [c, g];
}

function extent(arrs) {
  let lo = Infinity, hi = -Infinity;
  for (const a of arrs) for (const v of a) if (v != null && isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
  if (!isFinite(lo)) return [0, 1];
  if (lo === hi) return [lo - 1, hi + 1];
  const pad = (hi - lo) * 0.05;
  return [lo - pad, hi + pad];
}

function drawLine(g, vals, x0, y0, w, h, [lo, hi], color, width = 1, alpha = 1) {
  g.save(); g.globalAlpha = alpha; g.strokeStyle = color; g.lineWidth = width; g.beginPath();
  let started = false;
  vals.forEach((v, i) => {
    if (v == null) { started = false; return; }
    const x = x0 + (i / Math.max(1, vals.length - 1)) * w, y = y0 + h - ((v - lo) / (hi - lo)) * h;
    if (started) g.lineTo(x, y); else { g.moveTo(x, y); started = true; }
  });
  g.stroke(); g.restore();
}

function barChart(counts, { color = C.accent, max = 30 } = {}) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, max);
  const top = Math.max(1, ...entries.map(e => e[1]));
  const wrap = el("div", { class: "ex-bars" });
  for (const [k, v] of entries) {
    const row = el("div", { class: "ex-bar" });
    row.append(el("span", { class: "ex-bar-label", title: k }, k || "(blank)"));
    const track = el("span", { class: "ex-bar-track" });
    const fill = el("span", { class: "ex-bar-fill" }); fill.style.width = `${(v / top) * 100}%`; fill.style.background = color;
    track.append(fill);
    row.append(track, el("span", { class: "ex-bar-n" }, v.toLocaleString()));
    wrap.append(row);
  }
  return wrap;
}

function legend(items) {
  const l = el("div", { class: "ex-legend" });
  items.forEach(([name, color]) => { const s = el("span"); const sw = el("i"); sw.style.background = color; s.append(sw, document.createTextNode(name)); l.append(s); });
  return l;
}

// ------------------------------------------------------------------ views
const VIEWS = {
  async label_distribution(body, p, ctx) {
    const r = await api(`/api/explore/${ctx.id}/distribution?field=${encodeURIComponent(p.field || "label")}`);
    body.append(barChart(r.groups[0].counts));
  },

  async histogram(body, p, ctx) {
    const q = new URLSearchParams({ field: p.field, bins: p.bins || 20 });
    if (p.group_by) q.set("group_by", p.group_by);
    const r = await api(`/api/explore/${ctx.id}/distribution?${q}`);
    if (r.type === "categorical") { body.append(barChart(r.groups[0].counts)); return; }
    const [cv, g] = hiDpiCanvas(640, 200);
    const n = r.edges.length - 1;
    const dens = r.groups.map(gr => gr.counts.map(c => c / Math.max(1, gr.n || gr.counts.reduce((a, b) => a + b, 0))));
    const top = Math.max(...dens.flat(), 1e-9);
    r.groups.forEach((gr, gi) => {
      const col = C.palette[gi % C.palette.length];
      g.strokeStyle = col; g.fillStyle = col; g.globalAlpha = r.groups.length > 1 ? 0.25 : 0.6;
      dens[gi].forEach((v, i) => { const x = 30 + (i / n) * 600, w = 600 / n, h = (v / top) * 170; g.fillRect(x, 185 - h, w - 1, h); });
    });
    g.globalAlpha = 1; g.fillStyle = C.muted; g.font = "11px Geist, sans-serif";
    g.fillText(String(r.edges[0]), 30, 198); const last = String(r.edges[n]); g.fillText(last, 630 - g.measureText(last).width, 198);
    body.append(cv);
    if (r.groups.length > 1) body.append(legend(r.groups.map((gr, i) => [`${gr.group} (n=${gr.n})`, C.palette[i % C.palette.length]])));
  },

  async group_summary(body, p, ctx) {
    const r = await api(`/api/explore/${ctx.id}/summary?group_by=${encodeURIComponent(p.group_by)}&fields=${encodeURIComponent((p.fields || []).join(","))}`);
    const t = el("table", { class: "dir ex-table" });
    const hr = el("tr"); hr.append(el("th", {}, r.group_by), el("th", { class: "num" }, "n"), ...r.fields.map(f => el("th", { class: "num" }, f)));
    t.append(el("thead")); t.tHead.append(hr);
    const tb = el("tbody");
    for (const row of r.rows) {
      const tr = el("tr"); tr.append(el("td", {}, row.group), el("td", { class: "num" }, row.n));
      for (const f of r.fields) { const v = row[f]; tr.append(el("td", { class: "num" }, v && v.mean != null ? `${fmt(v.mean)} ± ${fmt(v.sd)}` : "")); }
      tb.append(tr);
    }
    t.append(tb);
    const w = el("div", { class: "table-wrap" }); w.append(t); body.append(w);
  },

  async record_table(body, p, ctx) {
    let offset = 0;
    const wrap = el("div", { class: "table-wrap" });
    const pager = el("div", { class: "pager" });
    const prev = el("button", { class: "btn link" }, "← Previous"), next = el("button", { class: "btn link" }, "Next →"), info = el("span", { class: "muted small" });
    pager.append(prev, info, next);
    body.append(wrap, pager);
    async function load() {
      const q = new URLSearchParams({ offset, length: 25 });
      if (p.columns && p.columns.length) q.set("columns", p.columns.join(","));
      const r = await api(`/api/explore/${ctx.id}/rows?${q}`);
      const cols = r.columns || Object.keys(r.rows[0] || {});
      const t = el("table", { class: "dir ex-table" });
      const hr = el("tr"); cols.forEach(c => hr.append(el("th", {}, c)));
      t.append(el("thead")); t.tHead.append(hr);
      const tb = el("tbody");
      r.rows.forEach(row => { const tr = el("tr"); cols.forEach(c => tr.append(el("td", {}, row[c] == null ? "" : String(row[c]).slice(0, 80)))); tb.append(tr); });
      t.append(tb);
      wrap.replaceChildren(t);
      info.textContent = r.total ? `${offset + 1}–${offset + r.rows.length} of ${r.total.toLocaleString()}` : "";
      prev.disabled = offset <= 0; next.disabled = !r.total || offset + 25 >= r.total;
    }
    prev.onclick = () => { offset = Math.max(0, offset - 25); load(); };
    next.onclick = () => { offset += 25; load(); };
    await load();
  },

  async notes(body, p) {
    const div = el("div", { class: "ex-notes" });
    div.innerHTML = miniMarkdown(p.text || "");
    body.append(div);
  },

  async image_gallery(body, p, ctx) {
    const groupBy = p.group_by;
    let groups = [null];
    if (groupBy) {
      try {
        const r = await api(`/api/explore/${ctx.id}/distribution?field=${encodeURIComponent(groupBy)}`);
        groups = Object.entries(r.groups[0].counts).sort((a, b) => b[1] - a[1]).slice(0, 12);
      } catch { groups = [null]; }
    }
    const tabs = el("div", { class: "seg ex-tabs" });
    const grid = el("div", { class: "ex-grid" });
    const more = el("button", { class: "btn link" }, "More");
    body.append(tabs, grid, more);
    let cur = null, offset = 0, rows = [];
    const per = p.per_group || 24;
    async function load(reset) {
      if (reset) { offset = 0; rows = []; grid.replaceChildren(); }
      const q = new URLSearchParams({ offset, length: per });
      if (groupBy && cur != null) q.set("where", `${groupBy}:${cur}`);
      const r = await api(`/api/explore/${ctx.id}/rows?${q}`);
      const start = rows.length;
      rows.push(...r.rows);
      r.rows.forEach((row, i) => {
        const src = row[p.image_field || "image"];
        if (!src) return;
        const fig = el("figure", { class: "ex-thumb" });
        const img = el("img", { loading: "lazy", alt: "" }); img.src = src;
        fig.append(img);
        if (p.mask_field && row[p.mask_field]) fig.append(el("span", { class: "ex-has-mask", title: "has mask" }, "mask"));
        fig.onclick = () => lightbox(rows, start + i, p, groupBy);
        grid.append(fig);
      });
      offset += r.rows.length;
      more.classList.toggle("hidden", r.rows.length < per);
    }
    groups.forEach((gEntry, i) => {
      const short = gEntry && (gEntry[0].length <= 3 || gEntry[0] === "(blank)");
      const b = el("button", {}, gEntry ? `${short ? `${groupBy}: ` : ""}${gEntry[0]} (${gEntry[1].toLocaleString()})` : "All");
      b.onclick = () => { tabs.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); cur = gEntry ? gEntry[0] : null; load(true).catch(e => grid.append(el("p", { class: "compat-warn" }, e.message))); };
      tabs.append(b);
      if (i === 0) b.classList.add("on");
    });
    cur = groups[0] ? groups[0][0] : null;
    more.onclick = () => load(false);
    await load(true);
  },

  async signal_viewer(body, p, ctx) {
    const labels = Object.keys(ctx.probe.labels || {});
    const bar = el("div", { class: "dev-controls" });
    const labSel = el("select"); labSel.append(el("option", { value: "" }, "All records"));
    labels.forEach(l => labSel.append(el("option", { value: l }, `with ${l}`)));
    const recSel = el("select");
    const winSel = el("select"); [2, 5, 10, 30, 60, 300].forEach(s => winSel.append(el("option", { value: s }, `${s} s`)));
    winSel.value = String(p.window_sec || 10);
    const prev = el("button", { class: "btn secondary" }, "◀"), next = el("button", { class: "btn secondary" }, "▶");
    const info = el("span", { class: "muted small" });
    bar.append(labSel, recSel, winSel, prev, next, info);
    const plot = el("div", { class: "ex-signal" });
    body.append(bar, plot);
    let start = 0, recSeconds = 0;
    async function loadRecords() {
      const r = await api(`/api/explore/${ctx.id}/records${labSel.value ? `?label=${encodeURIComponent(labSel.value)}` : ""}`);
      recSel.replaceChildren(...r.records.slice(0, 500).map(x => el("option", { value: x.id }, `${x.id}${x.labels && x.labels.length ? ` · ${x.labels.slice(0, 4).join(", ")}` : ""}`)));
      start = 0;
      if (r.records.length) await draw().catch(skipOnError); else plot.replaceChildren(el("p", { class: "muted" }, "No records match."));
    }
    async function draw() {
      const dur = +winSel.value;
      const q = new URLSearchParams({ record: recSel.value, start, dur });
      if (p.channels && p.channels.length) q.set("channels", p.channels.join(","));
      const r = await api(`/api/explore/${ctx.id}/signal?${q}`);
      recSeconds = r.record_seconds || 0;
      info.textContent = `${fmt(r.start)}–${fmt(r.start + r.dur)} s of ${fmt(recSeconds)} s${r.fs ? ` · ${r.fs} Hz` : ""}`;
      const W = 900, rowH = 110, H = rowH * r.channels.length + 24;
      const [cv, g] = hiDpiCanvas(W, H);
      g.font = "11px Geist, sans-serif";
      r.channels.forEach((ch, i) => {
        const y0 = 4 + i * rowH, ext = extent([ch.values]);
        g.fillStyle = C.muted; g.fillText(`${ch.name}${ch.unit ? ` (${ch.unit})` : ""}`, 4, y0 + 10);
        drawLine(g, ch.values, 60, y0 + 6, W - 70, rowH - 14, ext, C.ink, 1);
      });
      // Annotations: vertical ticks with labels; label changes drawn stronger.
      let prevLab = null;
      for (const a of r.annotations) {
        const x = 60 + ((a.t - r.start) / r.dur) * (W - 70);
        const change = a.label !== prevLab; prevLab = a.label;
        g.strokeStyle = change ? C.accent : "rgba(36,51,217,.25)"; g.lineWidth = change ? 1.5 : 1;
        g.beginPath(); g.moveTo(x, 4); g.lineTo(x, H - 18); g.stroke();
        if (change || r.annotations.length < 60) { g.fillStyle = C.accent; g.fillText(a.label || a.symbol, x + 2, H - 6); }
      }
      plot.replaceChildren(cv);
    }
    labSel.onchange = () => loadRecords().catch(e => banner(e.message));
    recSel.onchange = () => { start = 0; draw().catch(skipOnError); };
    // Records with annotations only (no signal): say so and move to the next one.
    function skipOnError(e) {
      if (/no signal/.test(e.message) && recSel.selectedIndex < recSel.options.length - 1) {
        recSel.selectedIndex += 1; start = 0; return draw().catch(skipOnError);
      }
      plot.replaceChildren(el("p", { class: "compat-warn" }, e.message));
    }
    winSel.onchange = () => draw().catch(e => banner(e.message));
    prev.onclick = () => { start = Math.max(0, start - +winSel.value); draw(); };
    next.onclick = () => { start = Math.min(Math.max(0, recSeconds - +winSel.value), start + +winSel.value); draw(); };
    await loadRecords();
  },

  async spaghetti(body, p, ctx) {
    let labels = (p.labels && p.labels.length) ? p.labels : Object.keys(ctx.probe.labels || {}).slice(0, 4);
    if (!labels.length && ctx.series && ctx.series.label_col) {
      const d = await api(`/api/explore/${ctx.id}/distribution?field=${encodeURIComponent(ctx.series.label_col)}`);
      labels = Object.entries(d.groups[0].counts).sort((a, b) => b[1] - a[1]).slice(0, 4).map(e => e[0]);
    }
    if (!labels.length) labels = [""];
    const wrap = el("div", { class: "ex-small-multiples" });
    body.append(el("p", { class: "muted small" }, `${p.channel || "first channel"}: individual records (thin) with pooled mean ± SD (bold, band); ${p.window_sec || 10} s ${p.align === "start" ? "from the start" : "around the label's first occurrence"}. Shared y-axis.`), wrap);
    const results = await Promise.all(labels.map(l => api(`/api/explore/${ctx.id}/traces?${new URLSearchParams({ channel: p.channel || "", label: l, n: p.n_per_group || 12, window: p.window_sec || 10, align: p.align || "event" })}`).catch(e => ({ error: e.message }))));
    const ext = extent(results.filter(r => !r.error).flatMap(r => r.traces));
    results.forEach((r, i) => {
      const cell = el("div", { class: "ex-sm" });
      const color = C.palette[i % C.palette.length];
      cell.append(el("div", { class: "small" }, `${labels[i] || "all records"}${r.traces ? ` · n=${r.traces.length}` : ""}`));
      if (r.error || !r.traces.length) { cell.append(el("p", { class: "muted small" }, r.error || "No records with this label.")); wrap.append(cell); return; }
      const [cv, g] = hiDpiCanvas(420, 180);
      r.traces.forEach(t => drawLine(g, t, 8, 6, 404, 160, ext, color, 1, 0.22));
      const m = r.pooled.mean, sd = r.pooled.sd;
      g.save(); g.globalAlpha = 0.18; g.fillStyle = color; g.beginPath();
      m.forEach((v, j) => { const x = 8 + (j / (m.length - 1)) * 404, y = 6 + 160 - (((v ?? 0) + (sd[j] ?? 0) - ext[0]) / (ext[1] - ext[0])) * 160; j ? g.lineTo(x, y) : g.moveTo(x, y); });
      for (let j = m.length - 1; j >= 0; j--) { const x = 8 + (j / (m.length - 1)) * 404, y = 6 + 160 - (((m[j] ?? 0) - (sd[j] ?? 0) - ext[0]) / (ext[1] - ext[0])) * 160; g.lineTo(x, y); }
      g.closePath(); g.fill(); g.restore();
      drawLine(g, m, 8, 6, 404, 160, ext, color, 2.5, 1);
      g.fillStyle = C.muted; g.font = "10px Geist, sans-serif"; g.fillText(`0 s`, 8, 178); g.fillText(`${r.seconds} s`, 390, 178);
      cell.append(cv);
      wrap.append(cell);
    });
  },
};

// ------------------------------------------------------------------ image viewer
function lightbox(rows, i, p, groupBy) {
  const ov = el("div", { class: "ex-lightbox" });
  const stage = el("div", { class: "ex-stage" });
  const layer = el("div", { class: "ex-layer" });
  const img = el("img", { alt: "" }), mask = el("img", { alt: "", class: "ex-mask" });
  layer.append(img, mask); stage.append(layer);
  const bar = el("div", { class: "ex-lb-bar" });
  const title = el("span", { class: "small" });
  const showMask = el("input", { type: "checkbox" }); showMask.checked = true;
  const op = el("input", { type: "range", min: "0", max: "1", step: "0.05", value: "0.45" });
  const maskCtl = el("label", { class: "small" }); maskCtl.append(showMask, " overlay ", op);
  const prev = el("button", { class: "btn secondary" }, "◀"), next = el("button", { class: "btn secondary" }, "▶"), reset = el("button", { class: "btn secondary" }, "Fit"), close = el("button", { class: "btn" }, "Close");
  bar.append(title, maskCtl, prev, next, reset, close);
  ov.append(stage, bar);
  document.body.append(ov);
  let s = 1, tx = 0, ty = 0, drag = null;
  const apply = () => { layer.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`; mask.style.opacity = showMask.checked ? op.value : 0; };
  function show(k) {
    i = (k + rows.length) % rows.length;
    const row = rows[i];
    img.src = row[p.image_field || "image"];
    const m = p.mask_field && row[p.mask_field];
    mask.classList.toggle("hidden", !m); if (m) mask.src = m;
    maskCtl.classList.toggle("hidden", !m);
    const meta = Object.entries(row).filter(([k, v]) => k !== p.image_field && k !== p.mask_field && v != null && typeof v !== "object" && !String(v).startsWith("http") && !String(v).startsWith("/api/")).map(([k, v]) => `${k}: ${v}`);
    title.textContent = `${i + 1}/${rows.length} · ${meta.join(" · ")}`;
    s = 1; tx = 0; ty = 0; apply();
  }
  stage.addEventListener("wheel", e => { e.preventDefault(); const f = e.deltaY < 0 ? 1.15 : 1 / 1.15; const r = stage.getBoundingClientRect(); const cx = e.clientX - r.left - r.width / 2 - tx, cy = e.clientY - r.top - r.height / 2 - ty; tx -= cx * (f - 1); ty -= cy * (f - 1); s = Math.min(20, Math.max(1, s * f)); if (s === 1) { tx = 0; ty = 0; } apply(); }, { passive: false });
  stage.addEventListener("pointerdown", e => { drag = [e.clientX - tx, e.clientY - ty]; stage.setPointerCapture(e.pointerId); });
  stage.addEventListener("pointermove", e => { if (drag) { tx = e.clientX - drag[0]; ty = e.clientY - drag[1]; apply(); } });
  stage.addEventListener("pointerup", () => { drag = null; });
  stage.addEventListener("dblclick", () => { s = s > 1 ? 1 : 3; if (s === 1) { tx = 0; ty = 0; } apply(); });
  showMask.onchange = apply; op.oninput = apply;
  prev.onclick = () => show(i - 1); next.onclick = () => show(i + 1); reset.onclick = () => { s = 1; tx = 0; ty = 0; apply(); };
  const key = e => { if (e.key === "Escape") done(); else if (e.key === "ArrowLeft") show(i - 1); else if (e.key === "ArrowRight") show(i + 1); };
  function done() { ov.remove(); document.removeEventListener("keydown", key); }
  close.onclick = done; document.addEventListener("keydown", key);
  show(i);
}

// ------------------------------------------------------------------ helpers
function fmt(v) { if (v == null) return ""; const a = Math.abs(v); return a >= 1000 ? Math.round(v).toLocaleString() : a >= 10 ? v.toFixed(1) : v.toFixed(3).replace(/0+$/, "").replace(/\.$/, ""); }

function miniMarkdown(md) {
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<i>$2</i>");
  const out = []; let list = null;
  for (const line of md.split("\n")) {
    const m = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)/);
    if (m) { if (!list) { list = []; } list.push(`<li>${inline(m[1])}</li>`); continue; }
    if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
    const h = line.match(/^#+\s+(.*)/);
    if (h) out.push(`<h4>${inline(h[1])}</h4>`); else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`<ul>${list.join("")}</ul>`);
  return out.join("");
}
