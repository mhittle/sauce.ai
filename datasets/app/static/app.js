// sauce.ai/datasets — single-page UI (no build step).
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const state = { query: "", crawlId: null, poll: null, seenHits: new Set(), newIds: new Set(),
                llm: false };

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

function el(tag, attrs = {}, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
}

function fmtBytes(n) {
  if (n == null) return "";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (n >= 1000 && i < u.length - 1) { n /= 1000; i++; }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
}

function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function banner(msg) {
  const b = $("#banner");
  b.textContent = msg || "";
  b.classList.toggle("hidden", !msg);
}

// ------------------------------------------------------------------ cards
const ACCESS_LABEL = { open: "Open", registration: "Free registration", credentialed: "Credentialed",
                       dua: "DUA required", request: "By request", unknown: "Access unknown" };
const DL_LABEL = { downloaded: "Downloaded", partial: "Partly downloaded", manual: "Manual access" };

function card(ds, markNew) {
  const n = $("#card-tpl").content.firstElementChild.cloneNode(true);
  const t = $(".title", n); t.textContent = ds.title; t.href = ds.url;
  if (markNew && state.newIds.has(ds.id)) { n.classList.add("is-new"); $(".badge.new", n).classList.remove("hidden"); }
  $(".source", n).textContent = ds.source || new URL(ds.url).hostname;
  const acc = $(".badge.access", n);
  acc.textContent = ACCESS_LABEL[ds.access_type] || ds.access_type;
  acc.classList.add(`access-${ds.access_type}`);
  const dl = $(".badge.dl", n);
  dl.textContent = DL_LABEL[ds.download_status] || "";
  dl.classList.add(`dl-${ds.download_status}`);
  $(".desc", n).textContent = ds.description || "";

  const chips = $(".chips", n);
  for (const c of ds.conditions) chips.append(el("span", { class: "chip cond" }, c));
  for (const m of ds.modalities) chips.append(el("span", { class: "chip" }, m));

  const meta = $(".meta", n);
  const rows = [["Labels", ds.labels], ["Size", ds.size], ["Subjects", ds.n_subjects],
                ["Formats", ds.file_formats.join(", ")], ["License", ds.license],
                ["Citation", ds.citation]];
  for (const [k, v] of rows) if (v) { meta.append(el("dt", {}, k), el("dd", {}, v)); }

  const files = $(".files", n);
  const got = (ds.files || []).filter(f => f.status === "downloaded");
  const skipped = (ds.files || []).filter(f => f.status !== "downloaded");
  if (got.length) {
    files.append(el("b", {}, "Collected files"));
    const ul = el("ul");
    for (const f of got) {
      const li = el("li"); const a = el("a", { href: `/files/${f.id}`, download: f.filename || "" }, f.filename);
      li.append(a, document.createTextNode(` · ${fmtBytes(f.bytes)}`)); ul.append(li);
    }
    files.append(ul);
  }
  if (skipped.length) {
    const ul = el("ul");
    for (const f of skipped) {
      const li = el("li", { class: "skip" });
      const a = el("a", { href: f.url, target: "_blank", rel: "noopener" }, f.url.split("/").pop() || f.url);
      li.append(a, document.createTextNode(` — not collected: ${f.note || f.status}`)); ul.append(li);
    }
    files.append(ul);
  }

  $(".instructions", n).textContent = ds.access_instructions || "See the source page.";
  const links = $(".links", n);
  const src = el("li"); src.append(el("a", { href: ds.url, target: "_blank", rel: "noopener" }, "Source page"));
  links.append(src);
  for (const u of ds.download_urls) {
    const li = el("li"); li.append(el("a", { href: u, target: "_blank", rel: "noopener" }, u)); links.append(li);
  }
  return n;
}

function renderCards(container, list, markNew = false) {
  container.replaceChildren(...list.map(ds => card(ds, markNew)));
}

// ------------------------------------------------------------------ search
async function runSearch(q, { crawl = true } = {}) {
  state.query = q;
  history.replaceState(null, "", `?q=${encodeURIComponent(q)}`);
  const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
  renderSearch(data);
  if (!crawl) return;
  if (data.crawl_recommended) {
    await startQueryCrawl(q, false);
  } else if (data.recent_crawl) {
    watchCrawl(data.recent_crawl.id);
  }
}

function renderSearch(data) {
  const strip = $("#conditions-strip");
  strip.className = "cond-strip";
  strip.replaceChildren(...data.conditions.map(c => {
    const p = el("div", { class: "cond-pill" });
    p.append(document.createTextNode(`${c.display}: `),
             el("b", {}, c.fda_510k_count == null ? "—" : c.fda_510k_count),
             document.createTextNode(" FDA 510(k) clearances"));
    return p;
  }));
  const res = data.results;
  const nNew = res.filter(d => state.newIds.has(d.id)).length;
  $("#results-meta").textContent = res.length
    ? `${res.length} dataset${res.length === 1 ? "" : "s"} indexed${nNew ? ` · ${nNew} new this crawl` : ""}`
    : "Nothing indexed for this yet.";
  // New finds first, then the existing ranking.
  res.sort((a, b) => (state.newIds.has(b.id) ? 1 : 0) - (state.newIds.has(a.id) ? 1 : 0));
  renderCards($("#results"), res, true);
}

async function startQueryCrawl(q, force) {
  if (!state.llm) {
    showCrawlPanel(`<span class="muted">Live crawling is off (no ANTHROPIC_API_KEY on the server). Showing the indexed catalog only.</span>`);
    return;
  }
  try {
    const r = await api("/api/crawls", { method: "POST", body: JSON.stringify({ mode: "query", query: q, force }) });
    watchCrawl(r.crawl_id);
  } catch (e) {
    showCrawlPanel(`<span class="muted">Couldn't start a crawl: ${escapeHtml(e.message)}</span>`);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function showCrawlPanel(html) {
  const p = $("#crawl-panel"); p.innerHTML = html; p.classList.remove("hidden");
}

function watchCrawl(id) {
  clearInterval(state.poll);
  state.crawlId = id; state.seenHits = new Set(); state.newIds = new Set();
  const tick = async () => {
    let c;
    try { c = await api(`/api/crawls/${id}`); } catch { return; }
    const running = c.status === "running" || c.status === "queued";
    let changed = false;
    for (const h of c.hits) if (!state.seenHits.has(h)) { state.seenHits.add(h); changed = true; }
    c.new_hits.forEach(h => state.newIds.add(h));
    const last = c.log.slice(-6).map(l => escapeHtml(l.msg)).join("<br>");
    const head = running
      ? `<div class="spinner"></div><b>Agent swarm crawling</b> — ${c.hits.length} found (${c.new_hits.length} new) · started ${ago(c.started_at)}
         <button class="btn link" id="cancel-crawl">Stop</button>`
      : `<b>Crawl ${escapeHtml(c.status)}</b> ${ago(c.finished_at || c.started_at)} — ${c.hits.length} found, ${c.new_hits.length} new.
         ${c.error ? `<span class="muted">${escapeHtml(c.error)}</span>` : ""}
         <button class="btn link" id="recrawl">Crawl again</button>`;
    showCrawlPanel(`<div class="row">${head}</div><div class="lines">${last}</div>`);
    const cancel = $("#cancel-crawl"), again = $("#recrawl");
    if (cancel) cancel.onclick = () => api(`/api/crawls/${id}/cancel`, { method: "POST" }).catch(() => {});
    if (again) again.onclick = () => startQueryCrawl(state.query, true);
    if (changed && state.query) renderSearch(await api(`/api/search?q=${encodeURIComponent(state.query)}`));
    if (!running) { clearInterval(state.poll); refreshStats(); }
  };
  tick();
  state.poll = setInterval(tick, 3000);
}

// ------------------------------------------------------------------ directory
let dirSelected = null;
async function loadDirectory() {
  const only = $("#only-with").checked;
  const rows = await api(`/api/conditions?with_datasets=${only}`);
  $("#dir-body").replaceChildren(...rows.map((r, i) => {
    const tr = el("tr");
    if (r.name === dirSelected) tr.classList.add("sel");
    tr.append(el("td", { class: "num" }, i + 1), el("td", {}, r.display),
              el("td", { class: "num" }, r.fda_510k_count ?? "—"),
              el("td", { class: "num" }, r.n_datasets), el("td", { class: "num" }, r.n_open),
              el("td", { class: "num" }, r.n_downloaded));
    tr.onclick = async () => {
      dirSelected = r.name;
      document.querySelectorAll("#dir-body tr").forEach(x => x.classList.remove("sel"));
      tr.classList.add("sel");
      renderCards($("#dir-results"), await api(`/api/datasets?condition=${encodeURIComponent(r.name)}`));
    };
    return tr;
  }));
}

// ------------------------------------------------------------------ crawls
async function loadCrawls() {
  const rows = await api("/api/crawls?limit=50");
  $("#crawls-body").replaceChildren(...rows.map(c => {
    const tr = el("tr");
    tr.append(el("td", {}, c.id), el("td", {}, c.mode), el("td", {}, c.query || "(all conditions)"),
              el("td", {}, c.status), el("td", { class: "num" }, c.n_hits), el("td", { class: "num" }, c.n_new),
              el("td", { class: "num" }, `${c.input_tokens.toLocaleString()} / ${c.output_tokens.toLocaleString()}`),
              el("td", {}, ago(c.started_at)));
    const td = el("td");
    if (c.status === "running" || c.status === "queued") {
      const b = el("button", { class: "btn link" }, "Stop");
      b.onclick = e => { e.stopPropagation(); api(`/api/crawls/${c.id}/cancel`, { method: "POST" }).then(loadCrawls); };
      td.append(b);
    }
    tr.append(td);
    tr.onclick = async () => {
      const d = await api(`/api/crawls/${c.id}`);
      const log = $("#crawl-log"); log.classList.remove("hidden");
      log.textContent = d.log.map(l => `${l.at}  ${l.msg}`).join("\n") || "(no log yet)";
    };
    return tr;
  }));
}

// ------------------------------------------------------------------ chrome
async function refreshStats() {
  try {
    const s = await api("/api/stats");
    state.llm = s.llm_configured;
    $("#stats").textContent = `${s.datasets} datasets · ${s.conditions} conditions · ${s.files} files (${fmtBytes(s.bytes)})` +
      (s.active_crawls.length ? ` · ${s.active_crawls.length} crawl running` : "");
    $("#broad-btn").disabled = !s.llm_configured;
    banner(s.llm_configured ? "" : "Crawling is disabled: set ANTHROPIC_API_KEY on the server. Search still works over the indexed catalog.");
  } catch (e) { banner(`API unreachable: ${e.message}`); }
}

function show(view) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === view));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("hidden", v.id !== `view-${view}`));
  if (view === "directory") loadDirectory();
  if (view === "crawls") loadCrawls();
}

document.querySelectorAll(".tab").forEach(t => (t.onclick = () => show(t.dataset.view)));
$("#only-with").onchange = loadDirectory;
$("#search-form").onsubmit = e => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (q) runSearch(q).catch(err => banner(err.message));
};
$("#broad-btn").onclick = async () => {
  if (!confirm("Launch a 1-hour crawl across all conditions (highest 510(k) count first)? This uses Claude API credits.")) return;
  try {
    const r = await api("/api/crawls", { method: "POST", body: JSON.stringify({ mode: "broad" }) });
    banner(`Broad crawl #${r.crawl_id} started — follow it on the Crawls tab.`);
    refreshStats();
  } catch (e) { banner(e.message); }
};

(async () => {
  await refreshStats();
  const q = new URLSearchParams(location.search).get("q");
  if (q) { $("#q").value = q; runSearch(q, { crawl: false }).catch(err => banner(err.message)); }
})();
