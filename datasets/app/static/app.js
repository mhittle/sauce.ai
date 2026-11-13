// Palo Alto Health Labs Datasets — single-page UI (no build step).
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const state = { query: "", crawlId: null, poll: null, seenHits: new Set(), newIds: new Set(),
                llm: false };

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } });
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
  if (ds.kind === "repository") {
    const r = el("span", { class: "badge repo", title: "A multi-study archive or data-access platform, not one dataset. Not counted as a dataset; papers are linked to the studies it hosts, not to it." }, "Repository");
    $(".sub", n).append(" ", r);
  }
  $(".desc", n).textContent = ds.description || "";

  const chips = $(".chips", n);
  for (const c of ds.conditions) chips.append(el("span", { class: "chip cond" }, c));
  for (const m of ds.modalities) chips.append(el("span", { class: "chip" }, m));

  const meta = $(".meta", n);
  const rows = [["Labels", ds.labels], ["Size", ds.size], ["Subjects", ds.n_subjects],
                ["Formats", ds.file_formats.join(", ")], ["License", ds.license],
                ["Citation", ds.citation]];
  const dp = dataLine(ds.profile);
  if (dp) rows.unshift(["Data", dp]);
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

  const fdaBox = $(".fda", n);
  if (ds.devices && ds.devices.length) {
    fdaBox.classList.remove("hidden");
    fdaBox.append(el("b", {}, `Referenced in ${ds.devices.length} FDA submission${ds.devices.length === 1 ? "" : "s"}: `));
    ds.devices.slice(0, 6).forEach((d, i) => {
      if (i) fdaBox.append(document.createTextNode(", "));
      const a = el("a", { href: `#/device/${d.k_number}`, title: `${d.device_name || ""} — ${d.applicant || ""}` }, d.k_number);
      fdaBox.append(a);
    });
    if (ds.devices.length > 6) fdaBox.append(" ", el("a", { href: `#/dataset/${ds.id}` }, "all…"));
  }

  if (typeof exploreAvailable === "function" && exploreAvailable(ds) && ds.kind !== "repository") {
    const b = el("a", { class: "btn secondary explore-btn", href: `#/explore/${encodeURIComponent(ds.id)}`, title: "Look at the data: images, signals or tables, grouped by label" }, "Explore");
    $(".card-head", n).append(b);
  }
  setupCompat($(".compat", n), ds);
  setupPapers($(".papers", n), ds);

  $(".instructions", n).textContent = ds.access_instructions || "See the source page.";
  const links = $(".links", n);
  const src = el("li"); src.append(el("a", { href: ds.url, target: "_blank", rel: "noopener" }, "Source page"));
  links.append(src);
  for (const u of ds.download_urls) {
    const li = el("li"); li.append(el("a", { href: u, target: "_blank", rel: "noopener" }, u)); links.append(li);
  }
  return n;
}

// Data profile, one line: "chest x-ray · png · 1024x1024 · adult".
function dataLine(p) {
  if (!p) return "";
  const size = p.image_size || (p.sampling_hz ? `${p.sampling_hz} Hz${p.channels ? ` × ${p.channels} ch` : ""}` : "");
  const labels = (p.targets || []).length;
  return [p.modality !== "other" && p.modality, (p.formats || []).join("/"), size, p.views,
          p.age_group !== "unknown" && p.age_group,
          labels && `${labels} label target${labels === 1 ? "" : "s"}`].filter(Boolean).join(" · ");
}

const ROLE_LABEL = { "train together": ["role-train", "Train together"], "external validation": ["role-val", "External validation"],
                     pretraining: ["role-pre", "Pretraining"], "related task": ["role-pre", "Related task"] };
function compatRow(r) {
  const d = el("div", { class: "compat-row" });
  const head = el("div", { class: "compat-head" });
  head.append(el("span", { class: "score", title: "Compatibility from this dataset's side (0–100): shared labels, data format/resolution, population" }, Math.round(r.score)));
  head.append(el("a", { href: `#/dataset/${encodeURIComponent(r.id)}` }, r.title));
  d.append(head);
  const tags = el("div", { class: "compat-tags" });
  for (const role of r.roles) { const [cls, lab] = ROLE_LABEL[role] || ["role-pre", role]; tags.append(el("span", { class: `tag ${cls}` }, lab)); }
  const shared = (r.shared || []).map(x => `${x.target}${x.how ? ` (${x.how})` : ""}`).join(", ");
  tags.append(el("span", { class: "pmeta" }, shared ? `Shared labels: ${shared}` : `Same data type: ${r.modality}`));
  d.append(tags);
  const dl = dataLine(r.data);
  const meta = [r.source, dl, r.n_subjects && `${r.n_subjects} subjects`, ACCESS_LABEL[r.access_type]].filter(Boolean).join(" · ");
  if (meta) d.append(el("div", { class: "pmeta" }, meta));
  for (const w of r.warnings || []) d.append(el("div", { class: "compat-warn" }, `⚠ ${w}`));
  if (r.notes && r.notes.length) d.append(el("div", { class: "pmeta" }, `To combine: ${r.notes.join("; ")}`));
  return d;
}

// Compatible datasets (computed in the background); loaded on first open.
function setupCompat(det, ds) {
  if (!ds.n_compatible) return;
  det.classList.remove("hidden");
  $("summary", det).textContent = `Compatible datasets (${ds.n_compatible})`;
  let loaded = false;
  det.addEventListener("toggle", async () => {
    if (!det.open || loaded) return;
    loaded = true;
    const r = await api(`/api/datasets/${encodeURIComponent(ds.id)}/compatible?limit=8`);
    const list = $(".compat-list", det);
    list.append(el("div", { class: "pmeta" }, "Other datasets usable in the same model or study, scored from this dataset's side."));
    for (const x of r.items) list.append(compatRow(x));
    if (ds.n_compatible > 8) list.append(el("a", { class: "small", href: `#/dataset/${encodeURIComponent(ds.id)}` }, `All ${ds.n_compatible} →`));
  });
}

// Papers linked by the background literature worker; loaded on first open.
function setupPapers(det, ds) {
  const sum = $("summary", det);
  sum.textContent = ds.n_articles ? `Used in ${ds.n_articles.toLocaleString()} papers` : "Papers";
  const list = $(".paper-list", det);
  let offset = 0, loaded = false;
  const more = el("button", { class: "btn link" }, "Show more");
  async function load() {
    const r = await api(`/api/datasets/${ds.id}/articles?limit=20&offset=${offset}`);
    if (!loaded) {
      loaded = true;
      const st = r.state;
      const head = el("div", { class: "pmeta" });
      head.textContent = !st ? "Not searched yet — the literature worker will get to it."
        : `${r.cites} cite the dataset paper · ${r.mentions_only} name it in the text` +
          (st.status === "active" || st.status === "retry" ? " · still collecting" : "");
      list.append(head);
    }
    for (const a of r.items) list.append(paper(a));
    offset += r.items.length;
    more.remove();
    $(".all-papers", list)?.remove();
    if (r.items.length === 20) list.append(more);
    if (r.total) list.append(el("a", { class: "all-papers small", href: `#/papers?dataset=${encodeURIComponent(ds.id)}` },
                                `Browse all ${r.total.toLocaleString()} in the Papers tab →`));
  }
  more.onclick = () => load().catch(() => {});
  det.addEventListener("toggle", () => { if (det.open && !loaded) load().catch(() => {}); });
}

function paper(a) {
  const d = el("div", { class: "paper" });
  const kind = a.is_descriptor ? ["descriptor", "Dataset paper"] : a.cites ? ["cites", "Cites"] : ["mentions", "Mentions"];
  d.append(el("span", { class: `tag ${kind[0]}` }, kind[1]));
  if (a.url && /^https?:/.test(a.url)) d.append(el("a", { href: a.url, target: "_blank", rel: "noopener" }, a.title));
  else d.append(el("span", {}, a.title));
  const meta = [a.authors && a.authors.split(",").slice(0, 3).join(",") + (a.authors.split(",").length > 3 ? " et al." : ""),
                a.venue, a.year, `${a.cited_by_count.toLocaleString()} citations`].filter(Boolean).join(" · ");
  d.append(el("div", { class: "pmeta" }, meta));
  if (a.devices && a.devices.length) {
    const u = el("div", { class: "used-in" });
    u.append(el("span", { class: "pmeta" }, "Used in FDA submission: "));
    for (const k of a.devices) u.append(el("a", { href: `#/device/${k}` }, k));
    d.append(u);
  }
  return d;
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
    const q = encodeURIComponent(c.name);
    p.append(document.createTextNode(`${c.display}: `),
             countLink(c.fda_510k_count, `#/devices?condition=${q}&type=510k`),
             document.createTextNode(" FDA 510(k) clearances · "),
             countLink(c.fda_denovo_count, `#/devices?condition=${q}&type=denovo`),
             document.createTextNode(" De Novo"));
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

// ------------------------------------------------------------------ browse all datasets
const BR_DEFAULTS = { q: "", modality: "", condition: "", access: "", source: "", sort: "papers", repositories: "", offset: "0" };
const br = { ...BR_DEFAULTS };
let brCondsLoaded = false;
const MOD_GROUPS = [["Imaging", ["imaging", "chest x-ray", "x-ray (other)", "mammography", "ct", "mri", "pet", "ultrasound", "echocardiography", "fundus", "oct", "dermatology photo", "pathology slide", "endoscopy", "dental x-ray"]],
                    ["Signals", ["ecg", "eeg", "emg", "ppg", "imu", "polysomnography", "physiological waveforms", "audio"]],
                    ["Other", ["ehr / tabular", "clinical text", "genomics", "video", "other", "unprofiled"]]];

function browseHash(over = {}) {
  const p = { ...br, ...over };
  const qs = Object.entries(p).filter(([k, v]) => v !== "" && v !== BR_DEFAULTS[k]).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  return `#/browse${qs ? "?" + qs : ""}`;
}

function setDirMode(mode) {
  document.querySelectorAll("#dir-mode button").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
  $("#dir-datasets").classList.toggle("hidden", mode !== "datasets");
  $("#dir-conditions").classList.toggle("hidden", mode !== "conditions");
}

async function loadBrowse() {
  setDirMode("datasets");
  if (!brCondsLoaded) {
    const conds = await api("/api/conditions?with_datasets=true");
    const sel = $("#br-cond");
    for (const c of conds.slice().sort((a, b) => (a.display || a.name).localeCompare(b.display || b.name)))
      sel.append(el("option", { value: c.name }, `${c.display || c.name} (${c.n_datasets})`));
    brCondsLoaded = true;
  }
  const params = new URLSearchParams({ sort: br.sort, limit: 50, offset: br.offset });
  for (const k of ["q", "modality", "condition", "access", "source"]) if (br[k]) params.set(k, br[k]);
  if (br.repositories) params.set("repositories", "true");
  const r = await api(`/api/datasets/browse?${params}`);
  const f = r.facets || {};
  // Data type: grouped options with counts (counts ignore the data-type filter itself).
  const mod = $("#br-mod");
  mod.replaceChildren(el("option", { value: "" }, "All data types"));
  for (const [group, keys] of MOD_GROUPS) {
    const og = el("optgroup", { label: group });
    for (const k of keys) {
      const n = (f.modality || {})[k];
      if (!n) continue;
      og.append(el("option", { value: k }, `${k === "imaging" ? "Any imaging" : k} (${n})`));
    }
    if (og.children.length) mod.append(og);
  }
  mod.value = br.modality;
  const fill = (sel, all, counts, label) => {
    sel.replaceChildren(el("option", { value: "" }, all));
    for (const [k, n] of Object.entries(counts || {}).sort((a, b) => b[1] - a[1])) sel.append(el("option", { value: k }, `${label ? label(k) : k} (${n})`));
    if (br[sel.dataset.key] && ![...sel.options].some(o => o.value === br[sel.dataset.key])) sel.append(el("option", { value: br[sel.dataset.key] }, br[sel.dataset.key]));
    sel.value = br[sel.dataset.key] || "";
  };
  $("#br-acc").dataset.key = "access"; $("#br-src").dataset.key = "source";
  fill($("#br-acc"), "Any access", f.access, k => ACCESS_LABEL[k] || k);
  fill($("#br-src"), "All sources", f.source);
  $("#br-cond").value = br.condition; $("#br-q").value = br.q; $("#br-sort").value = br.sort; $("#br-repo").checked = !!br.repositories;
  $("#br-sub").textContent = `${r.total.toLocaleString()} datasets match. Data type comes from each dataset's profile (what Claude read from its card); "unprofiled" ones haven't been profiled yet.`;
  $("#br-body").replaceChildren(...r.items.map(d => {
    const tr = el("tr");
    const t = el("td", { class: "br-title" }); t.append(el("a", { href: `#/dataset/${encodeURIComponent(d.id)}` }, d.title));
    t.append(el("div", { class: "pmeta" }, [d.source, d.n_subjects && `${d.n_subjects} subjects`].filter(Boolean).join(" · ")));
    const data = [d.modality !== "unprofiled" && d.modality, (d.formats || []).slice(0, 2).join("/"), d.image_size || (d.sampling_hz ? `${d.sampling_hz} Hz` : "")].filter(Boolean).join(" · ");
    const conds = el("td", { class: "small" });
    d.conditions.slice(0, 3).forEach(c => conds.append(el("span", { class: "chip" }, c), " "));
    if (d.conditions.length > 3) conds.append(el("span", { class: "pmeta" }, `+${d.conditions.length - 3}`));
    const acc = el("td"); const b = el("span", { class: `badge access-${d.access_type}` }, ACCESS_LABEL[d.access_type] || d.access_type); acc.append(b);
    if (d.kind === "repository") acc.append(" ", el("span", { class: "badge repo" }, "Repository"));
    const ex = el("td");
    if (typeof exploreAvailable === "function" && exploreAvailable({ ...d, files: [] }) && d.kind !== "repository")
      ex.append(el("a", { class: "small", href: `#/explore/${encodeURIComponent(d.id)}` }, d.explore_status === "ready" ? "Explore" : "Explore…"));
    tr.append(t, el("td", { class: "small" }, data), conds, acc, el("td", { class: "num" }, d.n_articles || ""),
              el("td", { class: "num" }, d.n_compatible || ""), el("td", { class: "num" }, d.n_devices || ""), ex);
    return tr;
  }));
  if (!r.items.length) $("#br-body").append(Object.assign(el("tr"), { innerHTML: `<td colspan="8" class="muted">No datasets match.</td>` }));
  const off = +br.offset;
  $("#br-page").textContent = r.total ? `${off + 1}–${off + r.items.length} of ${r.total.toLocaleString()}` : "";
  $("#br-prev").disabled = off <= 0; $("#br-next").disabled = off + 50 >= r.total;
}

document.querySelectorAll("#dir-mode button").forEach(b => (b.onclick = () => {
  if (b.dataset.mode === "datasets") location.hash = browseHash();
  else { if (location.hash) history.pushState(null, "", location.pathname + location.search); setDirMode("conditions"); loadDirectory(); }
}));
let brTimer;
$("#br-q").oninput = e => { clearTimeout(brTimer); brTimer = setTimeout(() => { location.hash = browseHash({ q: e.target.value.trim(), offset: "0" }); }, 350); };
for (const [id, key] of [["#br-mod", "modality"], ["#br-cond", "condition"], ["#br-acc", "access"], ["#br-src", "source"], ["#br-sort", "sort"]])
  $(id).onchange = e => { location.hash = browseHash({ [key]: e.target.value, offset: "0" }); };
$("#br-repo").onchange = e => { location.hash = browseHash({ repositories: e.target.checked ? "1" : "", offset: "0" }); };
$("#br-prev").onclick = () => { location.hash = browseHash({ offset: String(Math.max(0, +br.offset - 50)) }); };
$("#br-next").onclick = () => { location.hash = browseHash({ offset: String(+br.offset + 50) }); };

// ------------------------------------------------------------------ directory
let dirSelected = null;
async function loadDirectory() {
  const only = $("#only-with").checked;
  const sw = $("#dir-sw").checked;
  try { localStorage.setItem("dirSw", sw ? "1" : ""); } catch {}
  const [rows, st] = await Promise.all([api(`/api/conditions?with_datasets=${only}`), api("/api/stats")]);
  $("#dir-total").textContent = `${st.datasets.toLocaleString()} unique datasets` +
    (st.repositories ? ` (plus ${st.repositories} data repositories)` : "") +
    ` across ${st.conditions.toLocaleString()} conditions. A dataset covering several conditions is listed under each, so the Datasets column adds up to more than ${st.datasets.toLocaleString()}.`;
  if (sw) rows.sort((a, b) => (b.sw_510k - a.sw_510k) || (b.sw_denovo - a.sw_denovo) || (b.n_datasets - a.n_datasets));
  $("#dir-body").replaceChildren(...rows.map((r, i) => {
    const tr = el("tr");
    if (r.name === dirSelected) tr.classList.add("sel");
    const q = encodeURIComponent(r.name);
    const cat = sw ? "&category=software" : "";
    const k510 = el("td", { class: "num" }), kden = el("td", { class: "num" }), kai = el("td", { class: "num" });
    const synced = r.fda_510k_count != null;
    k510.append(countLink(sw ? (synced ? r.sw_510k : null) : r.fda_510k_count, `#/devices?condition=${q}&type=510k${cat}`));
    kden.append(countLink(sw ? (synced ? r.sw_denovo : null) : r.fda_denovo_count, `#/devices?condition=${q}&type=denovo${cat}`));
    kai.append(countLink(synced ? r.n_ai : null, `#/devices?condition=${q}&category=ai`));
    const name = el("td"); name.append(el("a", { class: "count", href: condHash(r.name) }, r.display));
    const dl = (n, f) => { const td = el("td", { class: "num" }); td.append(countLink(n, condHash(r.name, f))); return td; };
    tr.append(el("td", { class: "num" }, i + 1), name, k510, kden, kai,
              dl(r.n_datasets, ""), dl(r.n_open, "open"), dl(r.n_downloaded, "downloaded"));
    tr.onclick = () => { dirSelected = r.name; location.hash = condHash(r.name); };
    return tr;
  }));
}

// One condition's datasets, opened from the Directory.
const condHash = (name, f = "") => `#/datasets?condition=${encodeURIComponent(name)}${f ? `&filter=${f}` : ""}`;
async function loadCondition(name, filter) {
  const [list, conds] = await Promise.all([
    api(`/api/datasets?condition=${encodeURIComponent(name)}&limit=500`),
    api("/api/conditions?with_datasets=true")]);
  const c = conds.find(x => x.name === name) || { display: name };
  const keep = filter === "open" ? list.filter(d => d.access_type === "open")
    : filter === "downloaded" ? list.filter(d => ["downloaded", "partial"].includes(d.download_status)) : list;
  keep.sort((a, b) => ((a.kind === "repository") - (b.kind === "repository")) || (b.n_articles || 0) - (a.n_articles || 0));
  const nRepo = list.filter(d => d.kind === "repository").length;
  $("#cond-title").textContent = `${c.display}: datasets`;
  $("#cond-sub").textContent = `${list.length - nRepo} datasets` + (nRepo ? ` and ${nRepo} data ${nRepo === 1 ? "repository" : "repositories"} (listed last)` : "") + " in the catalog" +
    (filter ? ` · showing ${keep.length} ${filter === "open" ? "open-access" : "downloaded"}` : "") + " · most-used first.";
  document.querySelectorAll("#cond-filter button").forEach(b => {
    b.classList.toggle("on", b.dataset.f === (filter || ""));
    b.onclick = () => { location.hash = condHash(name, b.dataset.f); };
  });
  const q = encodeURIComponent(name);
  const links = $("#cond-links"); links.replaceChildren();
  links.append(el("a", { href: `#/papers?condition=${q}` }, "Papers using these datasets"), " · ",
               el("a", { href: `#/devices?condition=${q}` }, "FDA submissions"));
  renderCards($("#cond-results"), keep);
  if (!keep.length) $("#cond-results").append(el("p", { class: "muted" }, "No datasets match."));
}
$("#cond-back").onclick = e => { e.preventDefault(); show("directory"); };

// ------------------------------------------------------------------ FDA devices
function countLink(n, href) {
  if (n == null) return el("span", { class: "muted" }, "—");
  if (!n) return el("span", {}, "0");
  const a = el("a", { class: "count", href }, n.toLocaleString());
  a.onclick = e => e.stopPropagation();
  return a;
}

const TYPE_LABEL = { "510k": "510(k)", denovo: "De Novo", pma: "PMA" };
const AI_SOURCE = { fda_list: "on FDA's AI-Enabled Medical Devices list", summary_text: "summary PDF describes a trained model",
                    summary_review: "summary review identified AI/ML" };
function flags(d) {
  const f = document.createDocumentFragment();
  if (d.is_ai) f.append(el("span", { class: "flag ai", title: AI_SOURCE[d.ai_source] || "AI-enabled" }, "AI"));
  else if (d.is_software) f.append(el("span", { class: "flag sw", title: "Software function" }, "Software"));
  return f;
}
const typeBadge = t => el("span", { class: `type type-${t}` }, TYPE_LABEL[t] || t);
const DEV_DEFAULTS = { condition: "", type: "", category: "", q: "", linked: "", dataset: "", sort: "decision_date", dir: "desc", offset: "0" };
const dev = { ...DEV_DEFAULTS };
const PAGE = 50;

function devicesHash(over = {}) {
  const p = { ...dev, ...over };
  const qs = Object.entries(p).filter(([k, v]) => v !== "" && v !== DEV_DEFAULTS[k])
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  return `#/devices${qs ? "?" + qs : ""}`;
}

async function loadDevices() {
  const params = new URLSearchParams({ sort: dev.sort, dir: dev.dir, limit: PAGE, offset: dev.offset });
  for (const k of ["condition", "type", "category", "q", "dataset"]) if (dev[k]) params.set(k, dev[k]);
  if (dev.linked) params.set("linked", "true");
  const res = await api(`/api/devices?${params}`);
  const cond = res.condition;
  $("#dev-title").textContent = cond ? `${cond.display}: FDA submissions` : "FDA submissions";
  $("#dev-sub").textContent = cond
    ? `Submissions whose device name contains ${[...new Set([cond.name, ...cond.fda_terms])].map(t => `“${t}”`).join(", ")}, plus AI-enabled devices Claude assigned to this condition.`
      + (cond.fda_devices_capped ? " Showing the most recent submissions only." : "")
    : "Every 510(k) and De Novo decided recently, plus older ones on FDA's AI-enabled list, matched to directory conditions, or opened directly.";
  const rs = res.recent_sync;
  if (!cond && rs && rs.since) $("#dev-sub").textContent += ` Complete for decisions since ${rs.since} (openFDA data as of ${rs.openfda_updated || rs.newest}; FDA posts with a lag of about two weeks).`;
  if (res.total) {
    const f = res.facets;
    $("#dev-sub").textContent += ` In this view: ${f.n_510k.toLocaleString()} 510(k) · ${f.n_denovo.toLocaleString()} De Novo`
      + (f.n_pma ? ` · ${f.n_pma.toLocaleString()} PMA` : "")
      + ` — ${f.software.toLocaleString()} software, ${f.ai.toLocaleString()} AI-enabled.`;
  }
  document.querySelectorAll("#dev-type button").forEach(b => b.classList.toggle("on", b.dataset.type === dev.type));
  document.querySelectorAll("#dev-cat button").forEach(b => b.classList.toggle("on", b.dataset.cat === dev.category));
  $("#dev-q").value = dev.q;
  $("#dev-linked").checked = !!dev.linked;
  document.querySelectorAll("table.devices th[data-sort]").forEach(th => {
    th.classList.toggle("sorted", th.dataset.sort === dev.sort);
    th.classList.toggle("asc", th.dataset.sort === dev.sort && dev.dir === "asc");
  });
  $("#dev-body").replaceChildren(...res.items.map(d => {
    const tr = el("tr");
    const num = el("td", { class: "nowrap" }); num.append(el("a", { href: `#/device/${d.k_number}` }, d.k_number));
    const typ = el("td"); typ.append(typeBadge(d.submission_type));
    const name = el("td", {}, d.device_name || ""); name.append(flags(d));
    tr.append(num, typ, name, el("td", {}, d.applicant || ""),
              el("td", { class: "nowrap" }, d.decision_date || ""), el("td", { class: "nowrap" }, d.date_received || ""),
              el("td", {}, d.product_code || ""), el("td", { class: "num" }, d.n_links || ""));
    tr.onclick = () => { location.hash = `#/device/${d.k_number}`; };
    return tr;
  }));
  if (!res.items.length) $("#dev-body").append(Object.assign(el("tr"), { innerHTML: `<td colspan="8" class="muted">No submissions match.</td>` }));
  const off = +dev.offset;
  $("#dev-page").textContent = res.total ? `${off + 1}–${off + res.items.length} of ${res.total.toLocaleString()}` : "";
  $("#dev-prev").disabled = off <= 0;
  $("#dev-next").disabled = off + PAGE >= res.total;
}

document.querySelectorAll("#dev-type button").forEach(b => (b.onclick = () => { location.hash = devicesHash({ type: b.dataset.type, offset: "0" }); }));
document.querySelectorAll("#dev-cat button").forEach(b => (b.onclick = () => { location.hash = devicesHash({ category: b.dataset.cat, offset: "0" }); }));
document.querySelectorAll("table.devices th[data-sort]").forEach(th => (th.onclick = () => {
  const same = th.dataset.sort === dev.sort;
  const defDir = ["applicant", "device_name", "product_code", "type"].includes(th.dataset.sort) ? "asc" : "desc";
  location.hash = devicesHash({ sort: th.dataset.sort, dir: same ? (dev.dir === "asc" ? "desc" : "asc") : defDir, offset: "0" });
}));
let devQTimer;
$("#dev-q").oninput = e => { clearTimeout(devQTimer); devQTimer = setTimeout(() => { location.hash = devicesHash({ q: e.target.value.trim(), offset: "0" }); }, 350); };
$("#dev-linked").onchange = e => { location.hash = devicesHash({ linked: e.target.checked ? "1" : "", offset: "0" }); };
$("#dev-prev").onclick = () => { location.hash = devicesHash({ offset: String(Math.max(0, +dev.offset - PAGE)) }); };
$("#dev-next").onclick = () => { location.hash = devicesHash({ offset: String(+dev.offset + PAGE) }); };

// ------------------------------------------------------------------ papers
const PAP_DEFAULTS = { q: "", dataset: "", condition: "", relation: "", fda: "", sort: "cited_by_count", dir: "desc", offset: "0" };
const pap = { ...PAP_DEFAULTS };
const REL_TAG = { descriptor: ["descriptor", "Dataset paper"], cites: ["cites", "Cites"], mentions: ["mentions", "Mentions"] };
let papCondsLoaded = false;

function papersHash(over = {}) {
  const p = { ...pap, ...over };
  const qs = Object.entries(p).filter(([k, v]) => v !== "" && v !== PAP_DEFAULTS[k])
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  return `#/papers${qs ? "?" + qs : ""}`;
}

async function loadPaperConditions() {
  if (papCondsLoaded) return;
  const conds = await api("/api/conditions?with_datasets=true");
  const sel = $("#pap-cond");
  for (const c of conds.slice().sort((a, b) => (a.display || a.name).localeCompare(b.display || b.name)))
    sel.append(el("option", { value: c.name }, `${c.display || c.name} (${c.n_datasets})`));
  papCondsLoaded = true;
}

async function loadPapers() {
  loadPaperConditions().then(() => { $("#pap-cond").value = pap.condition; }).catch(() => {});
  const params = new URLSearchParams({ sort: pap.sort, dir: pap.dir, limit: PAGE, offset: pap.offset });
  for (const k of ["q", "dataset", "condition", "relation"]) if (pap[k]) params.set(k, pap[k]);
  if (pap.fda) params.set("fda", "true");
  const res = await api(`/api/articles?${params}`);
  $("#pap-title").textContent = res.dataset ? `Papers: ${res.dataset.title}` : "Papers";
  $("#pap-sub").textContent = "Papers that introduce, cite or name a catalog dataset, found by the literature linker in Europe PMC and OpenAlex. "
    + `${res.total.toLocaleString()} match.`;
  const filt = $("#pap-filter");
  filt.replaceChildren();
  if (pap.dataset) {
    const clear = el("a", { href: papersHash({ dataset: "", offset: "0" }) }, "show all datasets");
    const open = el("a", { href: `#/dataset/${encodeURIComponent(pap.dataset)}` }, "open dataset");
    filt.append(el("span", { class: "chip" }, `Dataset: ${res.dataset ? res.dataset.title : pap.dataset}`), open, " · ", clear);
  }
  filt.classList.toggle("hidden", !pap.dataset);
  document.querySelectorAll("#pap-rel button").forEach(b => b.classList.toggle("on", b.dataset.rel === pap.relation));
  $("#pap-q").value = pap.q;
  $("#pap-fda").checked = !!pap.fda;
  document.querySelectorAll("table.papers th[data-sort]").forEach(th => {
    th.classList.toggle("sorted", th.dataset.sort === pap.sort);
    th.classList.toggle("asc", th.dataset.sort === pap.sort && pap.dir === "asc");
  });
  $("#pap-body").replaceChildren(...res.items.map(a => {
    const tr = el("tr");
    const t = el("td", { class: "ptitle" });
    if (a.url && /^https?:/.test(a.url)) t.append(el("a", { href: a.url, target: "_blank", rel: "noopener" }, a.title));
    else t.append(el("span", {}, a.title));
    const au = a.authors ? a.authors.split(",") : [];
    const meta = [au.length ? au.slice(0, 3).join(",") + (au.length > 3 ? " et al." : "") : "",
                  a.doi ? `doi:${a.doi}` : a.pmid ? `PMID ${a.pmid}` : ""].filter(Boolean).join(" · ");
    if (meta) t.append(el("div", { class: "pmeta" }, meta));
    if (a.devices && a.devices.length) {
      const u = el("div", { class: "used-in" });
      u.append(el("span", { class: "pmeta" }, "Used in FDA submission: "));
      for (const k of a.devices) u.append(el("a", { href: `#/device/${k}` }, k));
      t.append(u);
    }
    const ds = el("td", { class: "pds" });
    for (const d of a.datasets.slice(0, 4)) {
      const l = el("a", { class: "ds-link", href: `#/dataset/${encodeURIComponent(d.id)}` });
      const tag = REL_TAG[d.relation];
      l.append(el("span", { class: `tag ${tag[0]}` }, tag[1]), d.title);
      ds.append(l);
    }
    if (a.datasets.length > 4) ds.append(el("span", { class: "pmeta" }, `+${a.datasets.length - 4} more`));
    tr.append(t, el("td", {}, a.venue || ""), el("td", { class: "num" }, a.year || ""),
              el("td", { class: "num" }, (a.cited_by_count || 0).toLocaleString()), ds);
    return tr;
  }));
  if (!res.items.length) $("#pap-body").append(Object.assign(el("tr"), { innerHTML: `<td colspan="5" class="muted">No papers match.</td>` }));
  const off = +pap.offset;
  $("#pap-page").textContent = res.total ? `${off + 1}–${off + res.items.length} of ${res.total.toLocaleString()}` : "";
  $("#pap-prev").disabled = off <= 0;
  $("#pap-next").disabled = off + PAGE >= res.total;
}

document.querySelectorAll("#pap-rel button").forEach(b => (b.onclick = () => { location.hash = papersHash({ relation: b.dataset.rel, offset: "0" }); }));
document.querySelectorAll("table.papers th[data-sort]").forEach(th => (th.onclick = () => {
  const same = th.dataset.sort === pap.sort;
  const defDir = ["title", "venue"].includes(th.dataset.sort) ? "asc" : "desc";
  location.hash = papersHash({ sort: th.dataset.sort, dir: same ? (pap.dir === "asc" ? "desc" : "asc") : defDir, offset: "0" });
}));
let papQTimer;
$("#pap-q").oninput = e => { clearTimeout(papQTimer); papQTimer = setTimeout(() => { location.hash = papersHash({ q: e.target.value.trim(), offset: "0" }); }, 350); };
$("#pap-cond").onchange = e => { location.hash = papersHash({ condition: e.target.value, offset: "0" }); };
$("#pap-fda").onchange = e => { location.hash = papersHash({ fda: e.target.checked ? "1" : "", offset: "0" }); };
$("#pap-prev").onclick = () => { location.hash = papersHash({ offset: String(Math.max(0, +pap.offset - PAGE)) }); };
$("#pap-next").onclick = () => { location.hash = papersHash({ offset: String(+pap.offset + PAGE) }); };

// One submission: public record, FDA links, catalog links, structured review.
let devicePoll = null;
async function loadDevice(k) {
  clearTimeout(devicePoll);
  const box = $("#device");
  let d;
  try { d = await api(`/api/devices/${encodeURIComponent(k)}`); }
  catch (e) { box.replaceChildren(el("p", { class: "muted" }, `${k}: ${e.message}`)); return; }
  if (location.hash !== `#/device/${k}`) return;
  const doc = d.doc || {};
  const frag = document.createDocumentFragment();

  const back = el("a", { href: "#" }, "← Back"); back.onclick = e => { e.preventDefault(); history.back(); };
  const head = el("div", { class: "dev-head" });
  head.append(back, el("h2", {}, d.device_name || d.k_number));
  const sub = el("div", { class: "sub" });
  sub.append(el("b", {}, d.k_number), " ", typeBadge(d.submission_type), flags(d),
             ` · ${d.applicant || ""} · ${d.decision_description || ""} ${d.decision_date || ""}`);
  head.append(sub);
  const links = el("div", { class: "dev-links" });
  links.append(el("a", { href: d.fda_url, target: "_blank", rel: "noopener" }, "FDA database record ↗"));
  if (doc.status !== "none") links.append(el("a", { href: d.pdf_url, target: "_blank", rel: "noopener" },
    { denovo: "Decision summary (PDF) ↗", pma: "SSED (PDF) ↗" }[d.submission_type] || "510(k) summary (PDF) ↗"));
  if (doc.pages) links.append(el("span", { class: "muted" }, `${doc.pages} pages`));
  head.append(links);
  frag.append(head);

  const grid = el("div", { class: "two-col" });
  const left = el("div"), right = el("div");

  // Catalog links (datasets / papers this submission's summary references)
  if (d.links.length) {
    const p = el("div", { class: "panel" });
    p.append(el("h3", {}, "Catalog datasets & papers referenced"));
    for (const l of d.links) {
      const row = el("div", { class: "link-row" });
      row.append(el("a", { href: `#/dataset/${l.dataset_id}` }, l.dataset_title));
      if (l.article_title) {
        row.append(" · paper: ");
        row.append(l.article_url ? el("a", { href: l.article_url, target: "_blank", rel: "noopener" }, l.article_title) : el("span", {}, l.article_title));
      }
      row.append(el("div", { class: "pmeta" }, `matched ${l.via}: “${l.matched}”`));
      if (l.snippet) row.append(el("div", { class: "snippet" }, `…${l.snippet}…`));
      p.append(row);
    }
    left.append(p);
  }

  // Structured review of the summary PDF
  const rev = el("div", { class: "panel review" });
  rev.append(el("h3", {}, "Summary review"));
  const x = doc.extracted;
  if (x) {
    const sec = (title, text) => { if (text) { rev.append(el("h4", {}, title), el("p", {}, text)); } };
    sec("Overview", x.summary);
    sec("Intended use", x.intended_use);
    sec(`Technology${x.is_ai_ml ? " (AI/ML)" : ""}`, x.technology);
    sec("Training data", x.training_data);
    const t = x.test_data || {};
    const tparts = [t.description, t.n_cases && `Cases: ${t.n_cases}`, t.n_sites && `Sites: ${t.n_sites}`,
                    t.countries && `Countries: ${t.countries}`, t.design && `Design: ${t.design}`].filter(Boolean);
    sec("Test data", tparts.join(" · "));
    sec("Reference standard", x.reference_standard);
    if (x.performance && x.performance.length) {
      rev.append(el("h4", {}, "Reported performance"));
      const tb = el("table");
      tb.append(Object.assign(el("tr"), { innerHTML: "<th>Metric</th><th>Value</th><th>95% CI</th><th>Population</th>" }));
      for (const m of x.performance) {
        const tr = el("tr"); for (const v of [m.metric, m.value, m.ci, m.population]) tr.append(el("td", {}, v || ""));
        tb.append(tr);
      }
      rev.append(tb);
    }
    if (x.datasets_named && x.datasets_named.length) sec("Datasets named", x.datasets_named.join("; "));
    sec("Limitations", x.limitations);
    if (x.references && x.references.length) {
      rev.append(el("h4", {}, "References cited"));
      const ul = el("ul", { class: "small" }); x.references.forEach(r => ul.append(el("li", {}, r))); rev.append(ul);
    }
    rev.append(el("p", { class: "pmeta" }, "Extracted by Claude from the public summary PDF — verify against the document."));
  } else if (d.pending) {
    const row = el("div", { class: "row" }); row.style.display = "flex"; row.style.gap = "8px"; row.style.alignItems = "center";
    row.append(el("div", { class: "spinner" }), el("span", { class: "muted" },
      doc.status === "done" ? "Summarizing the PDF…" : "Downloading and reading the summary PDF…"));
    rev.append(row);
    devicePoll = setTimeout(() => loadDevice(k), 4000);
  } else if (doc.status === "none") {
    rev.append(el("p", { class: "muted" }, "FDA has no public summary PDF for this submission (common for older filings and 510(k) “Statements”). The public record is on the right."));
  } else if (doc.status === "failed") {
    rev.append(el("p", { class: "muted" }, `Couldn't read the summary PDF (${doc.error || "error"}). Open it directly with the link above.`));
  } else if (!d.llm_available) {
    rev.append(el("p", { class: "muted" }, "Structured reviews need ANTHROPIC_API_KEY on the server. The summary PDF is linked above."));
  } else {
    rev.append(el("p", { class: "muted" }, doc.error || "No structured review yet."));
  }
  left.append(rev);

  // Public record (openFDA) + relationships
  const rec = el("div", { class: "panel" });
  rec.append(el("h3", {}, "Public record (openFDA)"));
  const kv = el("dl", { class: "kv" });
  const fields = [["Number", d.k_number], ["Type", TYPE_LABEL[d.submission_type]], ["Device", d.device_name],
    ["Applicant", d.applicant], ["Contact", d.contact], ["Address", d.address], ["Received", d.date_received],
    ["Decision", [d.decision_description, d.decision_code && `(${d.decision_code})`].filter(Boolean).join(" ")],
    ["Decision date", d.decision_date], ["Product code", d.product_code], ["Generic name", d.generic_name],
    ["Device class", d.device_class], ["Regulation", d.regulation_number], ["Specialty", d.medical_specialty],
    ["Review panel", d.advisory_committee], ["Clearance type", d.clearance_type],
    ["Summary / statement", d.statement_or_summary], ["Third-party review", d.third_party_flag],
    ["Expedited", d.expedited_review_flag],
    ["Software / AI", d.is_ai ? `AI-enabled — ${AI_SOURCE[d.ai_source] || ""}` : d.is_software ? "Software function" : ""]];
  for (const [k2, v] of fields) if (v) kv.append(el("dt", {}, k2), el("dd", {}, v));
  rec.append(kv);
  right.append(rec);

  const preds = (doc.predicates || []);
  if (preds.length) {
    const p = el("div", { class: "panel" });
    p.append(el("h3", {}, "Submissions named in the summary (predicates, references)"));
    const cl = el("div", { class: "chip-links" });
    preds.forEach(pr => cl.append(el("a", { href: `#/device/${pr.k_number}` }, pr.k_number)));
    p.append(cl);
    right.append(p);
  }
  if (d.conditions && d.conditions.length) {
    const p = el("div", { class: "panel" });
    p.append(el("h3", {}, "Conditions"));
    const cl = el("div", { class: "chip-links" });
    d.conditions.forEach(c => {
      const mapped = (d.condition_sources || {})[c] === "llm";
      cl.append(el("a", { href: `#/devices?condition=${encodeURIComponent(c)}`,
                          title: mapped ? "Assigned by Claude from the device's name and FDA codes" : "Device name matches the condition" },
                    mapped ? `${c} ✦` : c));
    });

    p.append(cl);
    if (Object.values(d.condition_sources || {}).includes("llm")) p.append(el("div", { class: "muted small" }, "✦ assigned by Claude"));
    right.append(p);
  }
  grid.append(left, right);
  frag.append(grid);
  box.replaceChildren(frag);
}

async function loadDataset(id) {
  const box = $("#dataset");
  const ds = await api(`/api/datasets/${encodeURIComponent(id)}`);
  const back = el("a", { href: "#" }, "← Back"); back.onclick = e => { e.preventDefault(); history.back(); };
  const cards = el("div", { class: "cards" }); cards.append(card(ds));
  const parts = [back, cards];
  if (ds.devices.length) {
    const p = el("div", { class: "panel" }); p.style.marginTop = "14px";
    p.append(el("h3", {}, "FDA submissions whose summaries reference this dataset"));
    for (const d of ds.devices) {
      const row = el("div", { class: "link-row" });
      row.append(el("a", { href: `#/device/${d.k_number}` }, d.k_number), " ", typeBadge(d.submission_type),
                 ` ${d.device_name || ""} · ${d.applicant || ""} · ${d.decision_date || ""}`);
      p.append(row);
    }
    parts.push(p);
  }
  if (ds.n_compatible) {
    const p = el("div", { class: "panel" }); p.style.marginTop = "14px";
    p.append(el("h3", {}, `Compatible datasets (${ds.n_compatible})`));
    p.append(el("p", { class: "muted small" }, "Datasets that can go into the same model or study. Train together: same labels and data close enough to pool. External validation: same task, with no sign of shared patients. Pretraining: same data type without shared labels. Scores are from this dataset's side: a single-label dataset scores a multi-label one higher than the reverse."));
    const r = await api(`/api/datasets/${encodeURIComponent(id)}/compatible?limit=100`);
    for (const x of r.items) p.append(compatRow(x));
    parts.push(p);
  }
  box.replaceChildren(...parts);
}

// ------------------------------------------------------------------ routing
function route() {
  const h = location.hash;
  if (h.startsWith("#/browse")) {
    const params = new URLSearchParams(h.split("?")[1] || "");
    Object.assign(br, BR_DEFAULTS);
    for (const k of Object.keys(BR_DEFAULTS)) if (params.has(k)) br[k] = params.get(k);
    show("directory", false);
    loadBrowse().catch(e => banner(e.message));
  } else if (h.startsWith("#/explore/")) {
    show("explore", false);
    window.scrollTo(0, $(".hero").offsetHeight + $(".hero").offsetTop - 72);
    loadExplore(decodeURIComponent(h.slice(10))).catch(e => banner(e.message));
  } else if (h.startsWith("#/datasets")) {
    const params = new URLSearchParams(h.split("?")[1] || "");
    show("cond", false);
    window.scrollTo(0, $(".hero").offsetHeight + $(".hero").offsetTop - 72);
    loadCondition(params.get("condition") || "", params.get("filter") || "").catch(e => banner(e.message));
  } else if (h.startsWith("#/papers")) {
    const params = new URLSearchParams(h.split("?")[1] || "");
    Object.assign(pap, PAP_DEFAULTS);
    for (const k of Object.keys(PAP_DEFAULTS)) if (params.has(k)) pap[k] = params.get(k);
    show("papers", false);
    loadPapers().catch(e => banner(e.message));
  } else if (h.startsWith("#/devices")) {
    const params = new URLSearchParams(h.split("?")[1] || "");
    Object.assign(dev, DEV_DEFAULTS);
    for (const k of Object.keys(DEV_DEFAULTS)) if (params.has(k)) dev[k] = params.get(k);
    show("devices", false);
    loadDevices().catch(e => banner(e.message));
  } else if (h.startsWith("#/device/")) {
    show("device", false);
    loadDevice(decodeURIComponent(h.slice(9))).catch(e => banner(e.message));
  } else if (h.startsWith("#/crawl/")) {
    show("crawl", false);
    loadCrawl(decodeURIComponent(h.slice(8))).catch(e => banner(e.message));
  } else if (h.startsWith("#/dataset/")) {
    show("dataset", false);
    loadDataset(decodeURIComponent(h.slice(10))).catch(e => banner(e.message));
  }
}
window.addEventListener("hashchange", route);

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
    tr.onclick = () => { location.hash = `#/crawl/${c.id}`; };
    return tr;
  }));
}

// One crawl: header, plan, the cards it found (new first), and its log.
let crawlPoll = null;
async function loadCrawl(id) {
  clearTimeout(crawlPoll);
  const [c, found] = await Promise.all([api(`/api/crawls/${id}`), api(`/api/crawls/${id}/datasets`)]);
  if (location.hash !== `#/crawl/${id}`) return;
  const running = c.status === "running" || c.status === "queued";
  const back = el("a", { href: "#" }, "← Back"); back.onclick = e => { e.preventDefault(); history.back(); };
  const head = el("div", { class: "dev-head" });
  head.append(back, el("h2", {}, c.query ? `Crawl #${c.id}: “${c.query}”` : `Crawl #${c.id}: all conditions`));
  const sub = el("div", { class: "sub" });
  sub.textContent = [`${c.mode} crawl`, c.status, `started ${ago(c.started_at)}`, `${c.minutes} min budget`,
    `${c.hits.length} datasets found (${c.new_hits.length} new)`,
    `${c.input_tokens.toLocaleString()} in / ${c.output_tokens.toLocaleString()} out tokens`].join(" · ");
  head.append(sub);
  if (running) {
    const stop = el("button", { class: "btn link" }, "Stop crawl");
    stop.onclick = () => api(`/api/crawls/${id}/cancel`, { method: "POST" }).then(() => loadCrawl(id)).catch(() => {});
    head.append(stop);
  }
  if (c.error) head.append(el("p", { class: "muted small" }, `Error: ${c.error}`));
  if (c.query) {
    const row = el("div", { class: "small" });
    row.append(el("a", { href: `?q=${encodeURIComponent(c.query)}` }, "Open as a search"));
    head.append(row);
  }
  const parts = [head];

  if (c.plan) {
    const p = el("div", { class: "panel" }); p.style.marginTop = "12px";
    p.append(el("h3", {}, "Plan"));
    if (c.plan.summary) p.append(el("p", { class: "small" }, c.plan.summary));
    const conds = (c.plan.conditions || []).map(x => x.name).filter(Boolean);
    if (conds.length) {
      const cl = el("div", { class: "chip-links" });
      conds.forEach(n => cl.append(el("a", { href: `#/devices?condition=${encodeURIComponent(n)}` }, n)));
      p.append(cl);
    }
    const ul = el("ul", { class: "small" });
    (c.plan.angles || []).forEach(a => ul.append(el("li", {}, `${a.focus}: ${a.instructions}`)));
    if (ul.children.length) p.append(ul);
    parts.push(p);
  }

  const meta = el("p", { class: "muted small" });
  meta.textContent = found.items.length ? `${found.items.length} dataset cards — new finds first` + (running ? " (updating while the crawl runs)" : "")
    : running ? "No datasets recorded yet — cards appear here as the agents find them." : "This crawl recorded no datasets.";
  const cards = el("div", { class: "cards" });
  state.newIds = new Set(found.items.filter(d => d.is_new).map(d => d.id));
  found.items.forEach(d => cards.append(card(d, true)));
  parts.push(meta, cards);

  const det = el("details", { class: "panel" }); det.style.marginTop = "14px";
  det.append(el("summary", {}, `Agent log (${c.log.length} lines)`));
  const pre = el("pre", { class: "log" });
  pre.textContent = c.log.map(l => `${l.at}  ${l.msg}`).join("\n") || "(no log yet)";
  det.append(pre);
  if (crawlLogOpen) det.open = true;
  det.addEventListener("toggle", () => { crawlLogOpen = det.open; });
  parts.push(det);

  $("#crawl").replaceChildren(...parts);
  if (running) crawlPoll = setTimeout(() => loadCrawl(id).catch(() => {}), 4000);
}
let crawlLogOpen = false;

// ------------------------------------------------------------------ chrome
async function refreshStats() {
  try {
    const s = await api("/api/stats");
    state.llm = s.llm_configured;
    $("#stats").textContent = `${s.datasets} datasets · ${s.conditions} conditions · ${s.files} files (${fmtBytes(s.bytes)}) · ${s.papers.toLocaleString()} papers · ${s.fda_submissions.toLocaleString()} FDA submissions` +
      (s.active_crawls.length ? ` · ${s.active_crawls.length} crawl running` : "");
    $("#broad-btn").disabled = !s.llm_configured;
    if (s.storage && s.storage.persistent === false)
      banner(`Storage is NOT persistent: the catalog at ${s.storage.data_dir} is on the container's disk and will be erased on the next deploy. Attach a Railway volume to this service.`);
    else banner(s.llm_configured ? "" : "Crawling is disabled: set ANTHROPIC_API_KEY on the server. Search still works over the indexed catalog.");
  } catch (e) { banner(`API unreachable: ${e.message}`); }
}

function show(view, clearHash = true) {
  if (clearHash && location.hash) history.pushState(null, "", location.pathname + location.search);
  const tabFor = { device: "devices", dataset: "search", crawl: "crawls", cond: "directory", explore: "search" }[view] || view;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === tabFor));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("hidden", v.id !== `view-${view}`));
  if (view === "directory" && !location.hash.startsWith("#/browse")) { setDirMode("conditions"); loadDirectory(); }
  if (view === "crawls") loadCrawls();
}

document.querySelectorAll(".tab").forEach(t => (t.onclick = () => {
  if (t.dataset.view === "devices") location.hash = "#/devices";
  else if (t.dataset.view === "papers") location.hash = "#/papers";
  else show(t.dataset.view);
}));
$("#only-with").onchange = loadDirectory;
$("#dir-sw").onchange = loadDirectory;
try { $("#dir-sw").checked = !!localStorage.getItem("dirSw"); } catch {}
$("#search-form").onsubmit = e => {
  e.preventDefault();
  if (location.hash) history.pushState(null, "", location.pathname + location.search);
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
  if (location.hash) route();
})();
