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
    if (r.items.length === 20) list.append(more);
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

// ------------------------------------------------------------------ directory
let dirSelected = null;
async function loadDirectory() {
  const only = $("#only-with").checked;
  const rows = await api(`/api/conditions?with_datasets=${only}`);
  $("#dir-body").replaceChildren(...rows.map((r, i) => {
    const tr = el("tr");
    if (r.name === dirSelected) tr.classList.add("sel");
    const q = encodeURIComponent(r.name);
    const k510 = el("td", { class: "num" }), kden = el("td", { class: "num" });
    k510.append(countLink(r.fda_510k_count, `#/devices?condition=${q}&type=510k`));
    kden.append(countLink(r.fda_denovo_count, `#/devices?condition=${q}&type=denovo`));
    tr.append(el("td", { class: "num" }, i + 1), el("td", {}, r.display), k510, kden,
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

// ------------------------------------------------------------------ FDA devices
function countLink(n, href) {
  if (n == null) return el("span", { class: "muted" }, "—");
  if (!n) return el("span", {}, "0");
  const a = el("a", { class: "count", href }, n.toLocaleString());
  a.onclick = e => e.stopPropagation();
  return a;
}

const TYPE_LABEL = { "510k": "510(k)", denovo: "De Novo" };
const typeBadge = t => el("span", { class: `type type-${t}` }, TYPE_LABEL[t] || t);
const DEV_DEFAULTS = { condition: "", type: "", q: "", linked: "", dataset: "", sort: "decision_date", dir: "desc", offset: "0" };
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
  for (const k of ["condition", "type", "q", "dataset"]) if (dev[k]) params.set(k, dev[k]);
  if (dev.linked) params.set("linked", "true");
  const res = await api(`/api/devices?${params}`);
  const cond = res.condition;
  $("#dev-title").textContent = cond ? `${cond.display}: FDA submissions` : "FDA submissions";
  $("#dev-sub").textContent = cond
    ? `${cond.fda_510k_count ?? 0} 510(k) · ${cond.fda_denovo_count ?? 0} De Novo, matched on device names containing: ${[...new Set([cond.name, ...cond.fda_terms])].join(", ")}.`
      + (cond.fda_devices_capped ? " Showing the most recent submissions only." : "")
    : "All submissions stored so far (from conditions in the directory, plus any opened directly).";
  document.querySelectorAll("#dev-type button").forEach(b => b.classList.toggle("on", b.dataset.type === dev.type));
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
    tr.append(num, typ, el("td", {}, d.device_name || ""), el("td", {}, d.applicant || ""),
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
  sub.append(el("b", {}, d.k_number), " ", typeBadge(d.submission_type),
             ` · ${d.applicant || ""} · ${d.decision_description || ""} ${d.decision_date || ""}`);
  head.append(sub);
  const links = el("div", { class: "dev-links" });
  links.append(el("a", { href: d.fda_url, target: "_blank", rel: "noopener" }, "FDA database record ↗"));
  if (doc.status !== "none") links.append(el("a", { href: d.pdf_url, target: "_blank", rel: "noopener" },
    d.submission_type === "denovo" ? "Decision summary (PDF) ↗" : "510(k) summary (PDF) ↗"));
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
    ["Expedited", d.expedited_review_flag]];
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
    d.conditions.forEach(c => cl.append(el("a", { href: `#/devices?condition=${encodeURIComponent(c)}` }, c)));
    p.append(cl);
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
  box.replaceChildren(...parts);
}

// ------------------------------------------------------------------ routing
function route() {
  const h = location.hash;
  if (h.startsWith("#/devices")) {
    const params = new URLSearchParams(h.split("?")[1] || "");
    Object.assign(dev, DEV_DEFAULTS);
    for (const k of Object.keys(DEV_DEFAULTS)) if (params.has(k)) dev[k] = params.get(k);
    show("devices", false);
    loadDevices().catch(e => banner(e.message));
  } else if (h.startsWith("#/device/")) {
    show("device", false);
    loadDevice(decodeURIComponent(h.slice(9))).catch(e => banner(e.message));
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
    $("#stats").textContent = `${s.datasets} datasets · ${s.conditions} conditions · ${s.files} files (${fmtBytes(s.bytes)}) · ${s.papers.toLocaleString()} papers · ${s.fda_submissions.toLocaleString()} FDA submissions` +
      (s.active_crawls.length ? ` · ${s.active_crawls.length} crawl running` : "");
    $("#broad-btn").disabled = !s.llm_configured;
    banner(s.llm_configured ? "" : "Crawling is disabled: set ANTHROPIC_API_KEY on the server. Search still works over the indexed catalog.");
  } catch (e) { banner(`API unreachable: ${e.message}`); }
}

function show(view, clearHash = true) {
  if (clearHash && location.hash) history.pushState(null, "", location.pathname + location.search);
  const tabFor = { device: "devices", dataset: "search" }[view] || view;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === tabFor));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("hidden", v.id !== `view-${view}`));
  if (view === "directory") loadDirectory();
  if (view === "crawls") loadCrawls();
}

document.querySelectorAll(".tab").forEach(t => (t.onclick = () => {
  if (t.dataset.view === "devices") location.hash = "#/devices";
  else show(t.dataset.view);
}));
$("#only-with").onchange = loadDirectory;
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
