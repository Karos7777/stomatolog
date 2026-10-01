"use strict";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n === null || n === undefined ? "—" : Number(n).toFixed(d));

const ICON = { ok: "✅", warn: "⚠️", bad: "❌", unknown: "❔" };
const LEVEL = { good: { icon: "✅", cls: "good" }, ok: { icon: "⚠️", cls: "mid" }, bad: { icon: "❌", cls: "low" } };
const COMPONENT_LABELS = {
  rating: "Рейтинг с поправкой на объём",
  authenticity: "Подлинность отзывов",
  credentials: "Лицензия и квалификация",
  transparency: "Прозрачность",
};
const VIA_LABELS = {
  official_registry: "госреестр", platform_api: "API площадки", manual_check: "проверено вручную",
  platform_page: "страница площадки", web_search_snippet: "поисковая выдача", clinic_claim: "заявление клиники", media: "СМИ",
};
const SEVERITY = { ok: "ok", info: "info", warning: "warn", critical: "bad" };

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) { /* не JSON */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
const telLink = (p) => `tel:${String(p).replace(/[^+\d]/g, "")}`;
function scoreClass(v) { return v === null || v === undefined ? "na" : v >= 65 ? "good" : v >= 50 ? "mid" : "low"; }

/* ============================================================ общие блоки */

function checksList(checks) {
  return `<ul class="checks">${checks.map((c) => `<li class="${esc(c.status)}"><span class="ci">${ICON[c.status] || "•"}</span>
    <div><b>${esc(c.title)}</b>${c.detail ? `<div class="small">${esc(c.detail)}</div>` : ""}</div></li>`).join("")}</ul>`;
}

function verdictBadge(v) {
  const l = LEVEL[v.level];
  return `<span class="badge ${l.cls}">${l.icon} ${esc(v.title)}</span>`;
}

function clinicActions(r) {
  const phone = (r.phones || [])[0];
  return `<div class="actions">
    ${phone ? `<a class="btn primary sm" href="${telLink(phone)}">📞 ${esc(phone)}</a>` : ""}
    ${r.gis_url ? `<a class="btn ghost sm" href="${esc(r.gis_url)}" target="_blank" rel="noopener">🗺 Открыть в 2ГИС</a>` : ""}
    <button class="btn ghost sm" data-open="${esc(r.id)}">Подробнее</button>
    <button class="btn ghost sm" data-revcheck="${esc(r.id)}" data-name="${esc(r.name)}">Проверить отзывы</button>
  </div>`;
}

function recCard(r, n) {
  const dist = r.distance_km !== undefined ? ` · ${fmt(r.distance_km, 1)} км` : "";
  return `<article class="rec level-${esc(r.verdict.level)}">
    <div class="rec-head">
      <div class="rec-num">${n}</div>
      <div class="rec-title"><h3>${esc(r.name)} ${r.is_24_7 ? '<span class="chip info">24/7</span>' : ""}</h3>
        <div class="muted">${esc(r.address)}${dist}</div></div>
      ${verdictBadge(r.verdict)}
    </div>
    ${checksList(r.verdict.checks)}
    ${clinicActions(r)}
  </article>`;
}

/* ============================================================ вкладки */

function setTab(name) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name === "doctors" && !doctorsLoaded) loadDoctors();
  if (name === "clinics" && !clinicsLoaded) loadList();
  if (name === "how") loadHow();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ============================================================ ПОДОБРАТЬ */

let pickState = { need: null, limit: 5 };

async function getPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => resolve(null), { timeout: 8000 });
  });
}

async function runPick() {
  if (!pickState.need) return;
  $$(".need").forEach((b) => b.classList.toggle("active", b.dataset.need === pickState.need));
  const out = $("#pick-out");
  out.innerHTML = '<div class="placeholder">Подбираем…</div>';
  const body = { need: pickState.need, limit: pickState.limit, verified_doctors: $("#verified-docs").checked };
  if ($("#near").checked) {
    const pos = await getPosition();
    if (pos) Object.assign(body, pos, { radius_km: 5 });
    else out.insertAdjacentHTML("afterbegin", '<div class="error">Не удалось узнать местоположение — показываем весь город.</div>');
  }
  try {
    const res = await api("/api/recommend", { method: "POST", body: JSON.stringify(body) });
    const c = res.counts;
    out.innerHTML = res.results.length ? `
      <div class="summary">
        <b>${esc(res.need_label || "Стоматология")}: нашли ${res.total} клиник.</b>
        <span>✅ ${c.good} можно доверять</span><span>⚠️ ${c.ok} — проверьте</span><span>❌ ${c.bad} — не рекомендуем без проверки</span>
      </div>
      ${res.results.map((r, i) => recCard(r, i + 1)).join("")}
      ${res.total > res.results.length && pickState.limit < 20 ? '<div class="more-row"><span></span><button class="btn ghost" id="pick-more">Показать ещё 5</button></div>' : ""}
      <p class="hint">Порядок: сначала «можно доверять», внутри — по индексу доверия и тому, насколько клиника подходит под задачу.
        Красный значок не означает, что клиника плохая, — значит, что есть вопрос, который нужно задать до лечения.</p>`
      : '<div class="placeholder">Ничего не нашлось. Снимите галочки или выберите другую задачу.</div>';
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

/* ============================================================ ВРАЧИ */

let doctorsLoaded = false;
let docOffset = 0;

function eduList(d) {
  if (!d.education.length) return '<p class="small muted">Образование в анкете не указано.</p>';
  return `<ul class="edu">${d.education.map((e) => `<li>
    <b>${esc(e.kind || "Образование")}</b>: ${esc(e.institution || "—")}${e.year ? `, ${e.year}` : ""}${e.specialty ? ` — ${esc(e.specialty)}` : ""}
    ${e.foreign ? `<span class="chip info">🌍 ${esc(e.country_label)}</span>` : ""}
    ${e.confirmed ? '<span class="chip green">✓ документ проверен YDoc</span>' : e.foreign ? '<span class="chip">документ не проверен</span>' : ""}
    ${e.how_to_verify && e.how_to_verify.length ? `<div class="small muted">${esc(e.how_to_verify[0])}</div>` : ""}</li>`).join("")}</ul>`;
}

function doctorCard(d, compact = false) {
  const badges = [
    d.documents_verified ? '<span class="badge good">✅ Документы проверены (YDoc)</span>' : '<span class="badge na">Документы не проверены</span>',
    d.foreign ? `<span class="badge info">🌍 Учёба за рубежом: ${esc(d.foreign_countries.join(", "))}</span>` : "",
    d.red_flags.length ? '<span class="badge low">❌ Противоречия в анкете</span>' : "",
  ].join(" ");
  const clinics = (d.clinics || []).map((c) => `<a href="#" data-open="${esc(c.clinic_id)}">${esc(c.clinic_name)}</a>${c.clinic_address ? ` <span class="muted">(${esc(c.clinic_address)})</span>` : ""}`).join(", ")
    || esc((d.workplaces || []).map((w) => w.name).filter(Boolean).join(", ") || "—");
  const rv = d.reviews;
  return `<article class="card doctor-card">
    <div class="doc-head"><h3>${esc(d.name)}</h3><div class="badges">${badges}</div></div>
    <div class="muted">${esc(d.specialties.join(", ") || "Стоматолог")}${d.experience_years ? ` · стаж ${d.experience_years} лет` : ""}</div>
    ${eduList(d)}
    ${d.checked_documents.length ? `<div class="small">YDoc сверил сканы: ${esc(d.checked_documents.join(", "))}</div>` : ""}
    ${d.red_flags.length ? `<ul class="flags bad">${d.red_flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${!compact && d.warnings.length ? `<ul class="flags warn">${d.warnings.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <div class="small">Работает: ${clinics}${rv.count ? ` · отзывы YDoc: ${fmt(rv.mean, 1)}★ (${rv.count}, подтверждены ${rv.verified})` : ""}</div>
    <div class="small"><a href="${esc(d.url)}" target="_blank" rel="noopener">Анкета и документы на YDoc ↗</a>${d.profile_updated ? ` <span class="muted">· обновлена ${esc(d.profile_updated)}</span>` : ""}</div>
  </article>`;
}

async function loadDoctors(append = false) {
  if (!append) docOffset = 0;
  const params = new URLSearchParams({ limit: 30, offset: docOffset });
  if ($("#doc-q").value.trim()) params.set("q", $("#doc-q").value.trim());
  if ($("#doc-spec").value) params.set("specialty", $("#doc-spec").value);
  if ($("#doc-verified").checked) params.set("verified", "true");
  if ($("#doc-foreign").checked) params.set("foreign", "true");
  const res = await api(`/api/doctors?${params}`);
  const s = res.stats;
  $("#doc-stats").innerHTML = s.total
    ? `В базе <b>${s.total}</b> стоматологов с YDoc: у <b>${s.verified}</b> площадка сверила сканы дипломов, <b>${s.foreign}</b> указали учёбу за рубежом
       (${s.foreign_verified ? `у ${s.foreign_verified} зарубежный документ проверен` : "ни у кого из них зарубежный документ не проверен — это пока только слова анкеты"}).
       ${s.linked} привязаны к клиникам из 2ГИС. Данные на ${esc(s.fetched || "—")}.`
    : "Анкеты врачей ещё не загружены: запустите <code>python -m tools.crawl_ydoc</code>.";
  if (!doctorsLoaded) {
    $("#doc-spec").insertAdjacentHTML("beforeend", res.specialties.map((x) => `<option>${esc(x)}</option>`).join(""));
    doctorsLoaded = true;
  }
  const html = res.items.map((d) => doctorCard(d)).join("");
  if (append) $("#doc-list").insertAdjacentHTML("beforeend", html);
  else $("#doc-list").innerHTML = html || '<div class="placeholder">Никого не нашли.</div>';
  docOffset += res.items.length;
  $("#doc-count").textContent = res.total ? `Показано ${docOffset} из ${res.total}` : "";
  $("#doc-more").hidden = docOffset >= res.total;
}

/* ============================================================ ВСЕ КЛИНИКИ */

let clinicsLoaded = false;
let listOffset = 0;

function clinicCard(r) {
  const rating = r.rating !== null ? `★ ${fmt(r.rating, 1)} <small>${r.volume} оц.</small>` : "нет рейтинга";
  return `<article class="card clinic">
    <div class="rec-head">
      <div class="rec-num">${r.position ?? "—"}</div>
      <div class="rec-title"><h3>${esc(r.name)} ${r.is_24_7 ? '<span class="chip info">24/7</span>' : ""}</h3>
        <div class="muted">${esc(r.address)}</div></div>
      <div class="score-side">${verdictBadge(r.verdict)}<div class="rating">${rating}</div>
        <div class="muted small">индекс доверия ${fmt(r.trust_index, 0)}</div></div>
    </div>
    ${checksList(r.verdict.checks)}
    ${clinicActions(r)}
  </article>`;
}

function listParams() {
  const params = new URLSearchParams({ sort: $("#sort").value, limit: 30, offset: listOffset });
  if ($("#q").value.trim()) params.set("q", $("#q").value.trim());
  if ($("#topic").value) params.set("topic", $("#topic").value);
  if ($("#license").value) params.set("license", $("#license").value);
  if ($("#minvol").value) params.set("min_volume", $("#minvol").value);
  if ($("#only247").checked) params.set("only_24_7", "true");
  if ($("#withmulti").checked) params.set("dental_only", "false");
  return params;
}

async function loadList(append = false) {
  if (!append) listOffset = 0;
  clinicsLoaded = true;
  const res = await api(`/api/clinics?${listParams()}`);
  const html = res.items.map(clinicCard).join("");
  if (append) $("#list").insertAdjacentHTML("beforeend", html);
  else $("#list").innerHTML = html || '<div class="placeholder">Ничего не найдено.</div>';
  listOffset += res.items.length;
  $("#list-count").textContent = `Показано ${listOffset} из ${res.total}`;
  $("#more").hidden = listOffset >= res.total;
}

/* ============================================================ ПРОВЕРИТЬ */

const clinicIds = new Map();
const doctorIds = new Map();

async function fillSuggestions(q, kind) {
  if (q.trim().length < 2) return;
  const res = await api(`/api/search?q=${encodeURIComponent(q.trim())}`);
  if (kind === "clinic") {
    res.clinics.forEach((c) => clinicIds.set(`${c.name} — ${c.address}`, c.id));
    $("#clinic-list").innerHTML = res.clinics.map((c) => `<option value="${esc(`${c.name} — ${c.address}`)}">`).join("");
  } else {
    res.doctors.forEach((d) => doctorIds.set(`${d.name}${d.clinic ? " — " + d.clinic : ""}`, d.id));
    $("#doctor-list").innerHTML = res.doctors.map((d) => `<option value="${esc(`${d.name}${d.clinic ? " — " + d.clinic : ""}`)}">`).join("");
  }
}

async function runReviewCheck(clinicId) {
  const out = $("#rev-out");
  out.innerHTML = '<div class="placeholder">Проверяем…</div>';
  try {
    const r = await api(`/api/check/reviews/${encodeURIComponent(clinicId)}`);
    out.innerHTML = `<div class="card verdict-card ${esc(r.status)}">
      <div class="big-line">${ICON[r.status] || "•"} <b>${esc(r.title)}</b></div>
      <div class="muted">${esc(r.clinic.name)} · ${esc(r.clinic.address)}</div>
      <ul>${r.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
      <div class="links">${r.clinic.gis_reviews_url ? `<a href="${esc(r.clinic.gis_reviews_url)}" target="_blank" rel="noopener">Открыть отзывы в 2ГИС ↗</a>` : ""}
        <a href="#" data-open="${esc(r.clinic.id)}">Всё о клинике</a></div>
      <p class="hint">Что сделать самому за 2 минуты: отсортируйте отзывы в 2ГИС по дате и посмотрите, не пришло ли много пятёрок за пару дней;
        прочитайте все отзывы на 1–3★; загляните в раздел «Неподтверждённые» внизу.</p></div>`;
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

async function runDoctorFind(doctorId) {
  const out = $("#doc-find-out");
  try {
    out.innerHTML = doctorCard(await api(`/api/doctors/${encodeURIComponent(doctorId)}`));
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

async function runCertText() {
  const out = $("#cert-text-out");
  const text = $("#cert-text").value;
  if (!text.trim()) { out.innerHTML = '<div class="error">Вставьте текст.</div>'; return; }
  try {
    const r = await api("/api/check/text", { method: "POST", body: JSON.stringify({ text }) });
    const cls = r.red_flags.length ? "bad" : r.claims.some((c) => c.verdict === "сомнительно") ? "warn" : "ok";
    out.innerHTML = `<div class="card verdict-card ${cls}">
      <div class="big-line">${ICON[cls]} <b>${esc(r.verdict)}</b></div>
      ${r.red_flags.length ? `<ul class="flags bad">${[...new Set(r.red_flags)].map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <table><thead><tr><th>Утверждение</th><th>Что это</th><th>Вывод</th></tr></thead><tbody>
      ${r.claims.map((c) => `<tr><td>${esc(c.text)}${c.foreign ? ` <span class="chip info">🌍 ${esc(c.country)}</span>` : ""}</td>
        <td>${esc(c.claim_type_label)}<div class="small muted">Не доказывает: ${esc(c.does_not_prove)}</div></td>
        <td><span class="chip ${verdictChip(c.verdict)}">${esc(c.verdict)}</span>
          ${c.how_to_verify[0] ? `<div class="small">${esc(c.how_to_verify[0])}</div>` : ""}</td></tr>`).join("")}
      </tbody></table></div>`;
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

function verdictChip(v) {
  return { "подтверждено": "green", "правдоподобно, но не проверено": "yellow", "сомнительно": "red",
    "признаки подделки": "red", "не является квалификацией": "yellow" }[v] || "yellow";
}

/* --- анализ текстов отзывов --- */
function distributionBars(dist) {
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
  return ["5", "4", "3", "2", "1"].map((s) => `<div class="dist-row"><span>${s}★</span>
    <span class="bar-track"><span class="bar-fill ${s >= 4 ? "good" : s == 3 ? "mid" : "low"}" style="width:${(dist[s] / total) * 100}%"></span></span>
    <span class="bar-val">${dist[s]}</span></div>`).join("");
}

async function runReviews() {
  const out = $("#reviews-out");
  const raw = $("#reviews-raw").value;
  if (!raw.trim()) { out.innerHTML = '<div class="error">Вставьте отзывы или загрузите файл.</div>'; return; }
  out.innerHTML = '<div class="placeholder">Анализируем…</div>';
  try {
    const a = await api("/api/analyze/reviews", { method: "POST", body: JSON.stringify({ raw }) });
    const cls = { organic: "good", some_signals: "mid", strong_signals: "low", insufficient_data: "na" }[a.verdict];
    out.innerHTML = `<div class="card">
      <div class="big-score"><div class="score ${cls}">${fmt(a.authenticity_index, 0)}</div>
        <div><div class="verdict">${esc(a.verdict_text)}</div>
        <div class="muted small">Индекс подлинности (100 — признаков накрутки нет) · отзывов: ${a.total} · подозрительных: ${a.suspicious_count}</div></div></div>
      <div class="two-col"><div><b>Оценки</b>${distributionBars(a.rating_distribution)}</div>
        <div><b>Рейтинг без подозрительных</b><div class="cleaned">${fmt(a.raw_mean_rating, 2)}★ → ${fmt(a.cleaned_mean_rating, 2)}★</div></div></div></div>
      ${a.signals.filter((s) => s.severity !== "info").map((s) => `<div class="signal ${SEVERITY[s.severity]}">
        <div class="signal-head"><b>${esc(s.title)}</b>${s.penalty ? `<span class="penalty">−${fmt(s.penalty, 0)}</span>` : ""}</div>
        <p>${esc(s.explanation)}</p>${s.evidence.length ? `<ul class="small">${s.evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`).join("")}`;
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

/* ============================================================ карточка клиники */

function sourceLink(src) {
  if (!src) return "—";
  const host = (() => { try { return new URL(src.url).hostname.replace("www.", ""); } catch (_) { return "ссылка"; } })();
  return `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.title || host)}</a> <small class="muted">${esc(VIA_LABELS[src.via] || src.via)}, ${esc(src.observed)}</small>`;
}

async function openClinic(id) {
  const d = await api(`/api/clinics/${encodeURIComponent(id)}`);
  const c = d.clinic;
  const comp = d.components;
  const L = c.license;
  const licMatches = L.matches.map((m) => `<div class="lic">
      <div><b>${esc(m.number)}</b> — ${esc(m.holder)}</div>
      <div class="small muted">${esc(m.address)} · выдана ${esc(m.issued || "—")}${m.chairs ? ` · кресел: ${m.chairs}` : ""}</div>
      <div class="small">Виды помощи: ${esc(m.scope.join(", ") || "—")}</div>
      <details class="small"><summary>Текст лицензии</summary>${esc(m.activity)}</details></div>`).join("");
  const ratingRows = c.ratings.map((o) => `<tr><td>${esc(o.platform)}</td><td>★ ${fmt(o.rating, 1)}</td>
      <td>${o.ratings_count ?? "—"}</td><td>${o.reviews_count ?? "—"}</td>
      <td>${sourceLink(o.source)}${o.note ? `<div class="muted small">${esc(o.note)}</div>` : ""}</td></tr>`).join("");
  const ydocDoctors = d.doctors || [];
  const otherDoctors = c.doctors.filter((doc) => !doc.profile || !Object.keys(doc.profile).length);
  $("#modal-body").innerHTML = `
    <h2>${esc(c.name)}</h2>
    <div class="muted">${esc(c.address)}${c.legal_name ? " · " + esc(c.legal_name) : ""}${c.inn ? " · ИНН " + esc(c.inn) : ""}</div>
    <div class="verdict-top">${verdictBadge(d.verdict)}</div>
    ${checksList(d.verdict.checks)}
    ${clinicActions(d)}

    <h3>Врачи</h3>
    ${ydocDoctors.length ? ydocDoctors.map((x) => doctorCard(x, true)).join("") : ""}
    ${otherDoctors.map((doc) => `<div class="doctor"><b>${esc(doc.name)}</b> — ${esc(doc.role || "")}
      <div class="small muted">Источник: ${doc.sources.map(sourceLink).join(" · ")}. Документы не проверены.</div></div>`).join("")}
    ${!ydocDoctors.length && !otherDoctors.length ? '<p class="muted">Врачи этой клиники в открытых источниках не найдены. Спросите ФИО врача и найдите его во вкладке «Врачи».</p>' : ""}

    <h3>Лицензия Минздрава</h3>
    <p><span class="chip">${esc(L.label)}</span> <span class="muted small">реестр МЗ КР на ${esc(L.registry.as_of || "—")}</span></p>
    ${licMatches}
    ${L.unlicensed_at_address.length ? `<ul class="flags bad"><li>Минздрав включил в список работающих <b>без лицензии</b> стоматологов по этому адресу: ${esc(L.unlicensed_at_address.map((u) => u.name).join(", "))}.</li></ul>` : ""}
    <div class="links">
      ${L.registry.source_file ? `<a href="${esc(L.registry.source_file)}" target="_blank" rel="noopener">Реестр лицензий МЗ КР ↗</a>` : ""}
      ${L.registry.unlicensed_file ? `<a href="${esc(L.registry.unlicensed_file)}" target="_blank" rel="noopener">Список «без лицензии» ↗</a>` : ""}
    </div>

    <h3>Откуда рейтинг</h3>
    ${c.ratings.length ? `<div class="table-wrap"><table><thead><tr><th>Площадка</th><th>Рейтинг</th><th>Оценок</th><th>Отзывов</th><th>Источник</th></tr></thead><tbody>${ratingRows}</tbody></table></div>` : '<p class="muted">Нет данных.</p>'}

    <details class="howto"><summary>Как посчитан индекс доверия (${fmt(d.trust_index, 0)})</summary>
      <div class="components">${Object.entries(COMPONENT_LABELS).map(([k, label]) => `
        <div class="component"><div class="component-head"><span>${esc(label)}</span><b class="${scoreClass(comp[k].score)}">${fmt(comp[k].score, 0)}</b></div>
        <ul>${comp[k].reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")}</div>
    </details>
    ${c.notes.length ? `<h3>Заметки</h3><ul>${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    <h3>Перед визитом</h3>
    <ol class="checklist">
      <li>Попросите показать лицензию: номер, адрес и нужный вам вид помощи (наркоз/седация — отдельно).</li>
      <li>Спросите ФИО врача и найдите его во вкладке «Врачи»: есть ли ординатура по нужной специальности.</li>
      <li>Курсы производителей (Straumann, Osstem, Ormco…) — 1–5 дней обучения, а не специализация.</li>
      <li>Прочитайте отзывы на 1–3★ и раздел «Неподтверждённые» в 2ГИС.</li>
      <li>Возьмите письменный план лечения с ценой каждого этапа и гарантией.</li>
    </ol>`;
  $("#modal").hidden = false;
}

/* ============================================================ КАК ЭТО РАБОТАЕТ */

let howLoaded = false;
async function loadHow() {
  if (howLoaded) return;
  howLoaded = true;
  const [m, method, audit] = await Promise.all([api("/api/meta"), api("/api/methodology"), api("/api/legacy-audit")]);
  $("#stats").innerHTML = [
    [m.clinics_total, "стоматологий из 2ГИС"], [m.licenses_found, "с найденной лицензией"],
    [m.license_statuses?.not_found || 0, "нет в реестре МЗ"], [m.unlicensed_at_address, "по адресу работали без лицензии"],
    [m.doctors?.total ?? "—", "врачей с YDoc"], [m.doctors?.verified ?? "—", "с проверенным дипломом"],
  ].map(([v, l]) => `<div class="stat"><span>${esc(v)}</span><small>${esc(l)}</small></div>`).join("");
  $("#method-out").innerHTML = `
    <h2>Как мы решаем, можно ли доверять</h2>
    <p>Для каждой клиники — четыре проверки простыми словами:</p>
    <ol>
      <li><b>Лицензия.</b> Ищем клинику в <a href="https://med.kg/lisenzirovanie?locale=ru" target="_blank" rel="noopener">реестре лицензий Минздрава КР</a> (на ${esc(m.registry?.as_of || "—")}) по адресу и названию.
        Проверяем, есть ли в лицензии нужный вид помощи (хирургия для имплантов, анестезия для лечения во сне), и нет ли этого адреса в списке Минздрава «работают без лицензии».
        Госполиклиник в реестре нет и быть не должно: Минздрав лицензирует только частные клиники и ИП (приказ №212).</li>
      <li><b>Отзывы.</b> Рейтинг и число оценок из официального API 2ГИС. Подозрительно: почти одни пятёрки при сотнях оценок,
        резкий скачок числа оценок между обновлениями, расхождение с YDoc, где отзывы подтверждаются записью на приём или звонком.</li>
      <li><b>Врачи.</b> Анкеты врачей YDoc: вуз, год, ординатура и отметка «Документы проверены» со списком сверенных документов.
        Проверенной считаем только ту строку образования, для которой YDoc сверил документ. Ищем нестыковки: стаж больше, чем лет с выпуска; специальности без подготовки.</li>
      <li><b>Подходит ли под задачу.</b> Указывает ли клиника нужную услугу.</li>
    </ol>
    <p>✅ <b>Можно доверять</b> — лицензия найдена и отзывы в порядке, красных флагов нет. ⚠️ <b>Проверьте</b> — что-то не подтверждено.
      ❌ <b>Не рекомендуем без проверки</b> — есть красный флаг (нет лицензии в реестре, по адресу работали без лицензии, низкий рейтинг, противоречия в документах).</p>
    <h3>Честно об ограничениях</h3>
    <ul>
      <li>2ГИС не отдаёт тексты отзывов, поэтому накрутку по текстам можно проверить, только вставив отзывы вручную (вкладка «Проверить»).</li>
      <li>«Документы проверены» на YDoc — проверка площадкой скана, а не ответ вуза. Зарубежные дипломы публично проверить почти негде;
        российский можно проверить самому по номеру в госреестре ФРДО на obrnadzor.gov.ru.</li>
      <li>«Нет в реестре» — повод спросить номер лицензии, а не доказательство нарушения: реестр может не учитывать старые лицензии.</li>
    </ul>
    <h3>Исследования, на которых основан детектор накрутки</h3>
    <ul>${Object.values(method.review_references).map((v) => `<li>${esc(v)}</li>`).join("")}</ul>`;
  const cls = { inflated: "red", partially_true: "yellow", not_found: "red" };
  $("#audit-out").innerHTML = `<h2>Что было не так в прошлой версии сайта</h2><p>${esc(audit.summary)}</p>
    <div class="table-wrap"><table class="audit"><thead><tr><th>Клиника</th><th>Проблемы</th></tr></thead><tbody>
    ${audit.entries.map((e) => `<tr><td><b>${esc(e.name)}</b><br><span class="chip ${cls[e.verdict]}">${esc(audit.verdict_labels[e.verdict])}</span></td>
      <td class="small"><ul>${e.issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></td></tr>`).join("")}
    </tbody></table></div>`;
}

async function loadDataLine() {
  try {
    const m = await api("/api/meta");
    $("#data-line").innerHTML = `Проверено: ${m.clinics_total} стоматологий из 2ГИС · реестр лицензий Минздрава на ${esc(m.registry?.as_of || "—")}
      · ${m.doctors?.total ?? 0} анкет врачей YDoc (у ${m.doctors?.verified ?? 0} проверен диплом). <a href="#" data-tab-link="how">Как это работает</a>`;
  } catch (_) { /* не критично */ }
}

/* ============================================================ запуск */

document.addEventListener("DOMContentLoaded", () => {
  $$(".tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  loadDataLine();

  $$(".need").forEach((b) => b.addEventListener("click", () => { pickState = { need: b.dataset.need, limit: 5 }; runPick(); }));
  ["#near", "#verified-docs"].forEach((s) => $(s).addEventListener("change", () => runPick()));

  $("#doc-q").addEventListener("input", debounce(() => loadDoctors(), 300));
  ["#doc-spec", "#doc-verified", "#doc-foreign"].forEach((s) => $(s).addEventListener("change", () => loadDoctors()));
  $("#doc-more").addEventListener("click", () => loadDoctors(true));

  $("#q").addEventListener("input", debounce(() => loadList(), 250));
  ["#topic", "#sort", "#only247", "#license", "#minvol", "#withmulti"].forEach((s) => $(s).addEventListener("change", () => loadList()));
  $("#more").addEventListener("click", () => loadList(true));

  $("#rev-q").addEventListener("input", debounce((e) => {
    const id = clinicIds.get(e.target.value);
    if (id) runReviewCheck(id); else fillSuggestions(e.target.value, "clinic");
  }, 250));
  $("#doc-find").addEventListener("input", debounce((e) => {
    const id = doctorIds.get(e.target.value);
    if (id) runDoctorFind(id); else fillSuggestions(e.target.value, "doctor");
  }, 250));
  $("#cert-text-btn").addEventListener("click", runCertText);
  $("#reviews-btn").addEventListener("click", runReviews);
  $("#reviews-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (f) { $("#reviews-raw").value = await f.text(); runReviews(); }
  });

  document.addEventListener("click", (e) => {
    const more = e.target.closest("#pick-more");
    if (more) { pickState.limit += 5; runPick(); return; }
    const open = e.target.closest("[data-open]");
    if (open) { e.preventDefault(); openClinic(open.dataset.open); return; }
    const rev = e.target.closest("[data-revcheck]");
    if (rev) {
      $("#modal").hidden = true;
      setTab("check");
      $("#rev-q").value = rev.dataset.name;
      runReviewCheck(rev.dataset.revcheck);
      return;
    }
    const tabLink = e.target.closest("[data-tab-link]");
    if (tabLink) { e.preventDefault(); setTab(tabLink.dataset.tabLink); return; }
    const ex = e.target.closest("[data-example]");
    if (ex) api(`/api/examples/${ex.dataset.example}`).then((t) => { $("#reviews-raw").value = t; runReviews(); });
  });
  $("#modal-close").addEventListener("click", () => { $("#modal").hidden = true; });
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").hidden = true; });
});
