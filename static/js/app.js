"use strict";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n === null || n === undefined ? "—" : Number(n).toFixed(d));

const COMPONENT_LABELS = {
  rating: "Рейтинг с поправкой на объём",
  authenticity: "Подлинность отзывов",
  credentials: "Подтверждённая квалификация",
  transparency: "Прозрачность",
};
const VIA_LABELS = {
  official_registry: "госреестр",
  platform_api: "API площадки",
  manual_check: "проверено вручную",
  web_search_snippet: "поисковая выдача",
  clinic_claim: "заявление клиники",
  media: "СМИ",
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

function scoreClass(v) {
  if (v === null || v === undefined) return "na";
  if (v >= 65) return "good";
  if (v >= 50) return "mid";
  return "low";
}

function flagChips(flags) {
  return (flags || []).map((f) => `<span class="chip ${esc(f.level)}">${esc(f.text)}</span>`).join("");
}

function bars(components) {
  return Object.entries(COMPONENT_LABELS).map(([k, label]) => {
    const v = components[k]?.score;
    return `<div class="bar" title="${esc(label)}: ${fmt(v, 0)}">
      <span class="bar-label">${esc(label)}</span>
      <span class="bar-track"><span class="bar-fill ${scoreClass(v)}" style="width:${v ?? 0}%"></span></span>
      <span class="bar-val">${fmt(v, 0)}</span></div>`;
  }).join("");
}

/* ------------------------------------------------------------ вкладки */
function setupTabs() {
  $$(".tab").forEach((btn) => btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
    if (btn.dataset.tab === "method") loadMethod();
    if (btn.dataset.tab === "audit") loadAudit();
  }));
}

/* ------------------------------------------------------------ шапка */
async function loadMeta() {
  const m = await api("/api/meta");
  $("#notice-text").innerHTML = `Каждая цифра — со ссылкой на источник. Рейтинги взяты из открытой поисковой выдачи
    на ${esc(m.collected_at)} (прямой доступ к 2ГИС был закрыт) — сверяйте по ссылке «Открыть в 2ГИС».
    <strong>Лицензии МЗ КР пока не сверены ни у одной клиники</strong> — статус «не проверено», а не «есть».
    Отзывы по текстам не анализировались: загрузите их на вкладке «Проверить отзывы».`;
  $("#stats").innerHTML = [
    [m.clinics_total, "клиник с источниками"],
    [m.clinics_ranked, "с рейтингом"],
    [m.rating_observations, "наблюдений рейтинга"],
    [m.licenses_verified, "лицензий сверено"],
    [m.with_review_analysis, "клиник с разбором отзывов"],
    [m.collected_at, "дата сбора"],
  ].map(([v, l]) => `<div class="stat"><span>${esc(v)}</span><small>${esc(l)}</small></div>`).join("");
}

/* ------------------------------------------------------------ рейтинг */
function clinicCard(r, compact = false, place = null) {
  const rating = r.rating !== null ? `★ ${fmt(r.rating, 1)} <small>${r.volume} оц.</small>` : "нет рейтинга";
  const main = r.fit !== undefined ? r.fit : r.trust_index;
  return `<article class="card clinic ${compact ? "compact" : ""}">
    <div class="clinic-main">
      <div class="pos">${place ?? r.position ?? "—"}</div>
      <div class="clinic-info">
        <h3>${esc(r.name)} ${r.is_24_7 ? '<span class="chip info">24/7</span>' : ""}</h3>
        <div class="muted">${esc(r.address)}${r.district ? " · " + esc(r.district) : ""}</div>
        <div class="chips">${flagChips(r.flags)}</div>
        ${r.reasons ? `<ul class="reasons">${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      </div>
      <div class="score-box">
        <div class="score ${scoreClass(main)}">${main !== null ? fmt(main, 0) : "?"}</div>
        <div class="score-cap">${r.fit !== undefined ? `соответствие (доверие ${fmt(r.trust_index, 0)})` : "индекс доверия"}</div>
        <div class="rating">${rating}</div>
        <div class="conf">данные: ${esc(r.confidence)} достоверность</div>
      </div>
    </div>
    ${compact ? "" : `<div class="bars">${bars(r.components)}</div>`}
    <div class="actions">
      <button class="btn primary sm" data-open="${esc(r.id)}">Доказательства</button>
      ${r.gis_url ? `<a class="btn ghost sm" href="${esc(r.gis_url)}" target="_blank" rel="noopener">Открыть в 2ГИС</a>` : ""}
      ${r.website ? `<a class="btn ghost sm" href="${esc(r.website)}" target="_blank" rel="noopener">Сайт</a>` : ""}
    </div>
  </article>`;
}

async function loadList() {
  const params = new URLSearchParams({ sort: $("#sort").value });
  if ($("#q").value.trim()) params.set("q", $("#q").value.trim());
  if ($("#topic").value) params.set("topic", $("#topic").value);
  if ($("#only247").checked) params.set("only_24_7", "true");
  const rows = await api(`/api/clinics?${params}`);
  const ranked = rows.filter((r) => r.trust_index !== null);
  const unranked = rows.filter((r) => r.trust_index === null);
  $("#list").innerHTML = ranked.length ? ranked.map((r) => clinicCard(r)).join("") : '<div class="placeholder">Ничего не найдено.</div>';
  $("#unranked").innerHTML = unranked.map((r) => clinicCard(r, true)).join("");
  $("#unranked-title").hidden = $("#unranked-hint").hidden = !unranked.length;
}

/* ------------------------------------------------------------ доказательства */
function sourceLink(src) {
  if (!src) return "—";
  const host = (() => { try { return new URL(src.url).hostname.replace("www.", ""); } catch (_) { return "ссылка"; } })();
  return `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.title || host)}</a> <small class="muted">${esc(VIA_LABELS[src.via] || src.via)}, ${esc(src.observed)}</small>`;
}

function credentialBlock(v) {
  return `<div class="verdict-line"><span class="chip ${verdictClass(v.verdict)}">${esc(v.verdict)}</span>
      <span class="muted">${esc(v.claim_type_label)} · ${esc(v.evidence_label)}</span></div>
    <div class="two-col">
      <div><b>Доказывает:</b> ${esc(v.proves)}</div>
      <div><b>Не доказывает:</b> ${esc(v.does_not_prove)}</div>
    </div>
    ${v.red_flags.length ? `<ul class="flags bad">${v.red_flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${v.warnings.length ? `<ul class="flags warn">${v.warnings.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${v.how_to_verify.length ? `<div><b>Как проверить:</b><ul>${v.how_to_verify.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
    ${v.verify_links.length ? `<div class="links">${v.verify_links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)} ↗</a>`).join("")}</div>` : ""}`;
}

function verdictClass(v) {
  return { "подтверждено": "green", "правдоподобно, но не проверено": "yellow", "сомнительно": "red",
    "признаки подделки": "red", "не является квалификацией": "yellow" }[v] || "yellow";
}

async function openClinic(id) {
  const d = await api(`/api/clinics/${encodeURIComponent(id)}`);
  const c = d.clinic;
  const comp = d.components;
  const ratingRows = c.ratings.map((o) => `<tr>
      <td>${esc(o.platform)}</td><td>★ ${fmt(o.rating, 1)}</td>
      <td>${o.ratings_count ?? "—"}</td><td>${o.reviews_count ?? "—"}</td>
      <td>${sourceLink(o.source)}${o.note ? `<div class="muted small">${esc(o.note)}</div>` : ""}</td></tr>`).join("");
  const doctors = c.doctors.map((doc, i) => {
    const checks = comp.credentials.checks.filter((ch) => ch.doctor === doc.name);
    return `<div class="doctor"><h4>${esc(doc.name)}</h4><div class="muted">${esc(doc.role || "")}</div>
      ${checks.map((ch) => `<div class="claim"><div class="claim-title">«${esc(ch.claim)}»</div>${credentialBlock(ch.verdict)}</div>`).join("")}
      <div class="small">Источники: ${doc.sources.map(sourceLink).join(" · ")}</div></div>`;
  }).join("") || '<p class="muted">В найденных источниках врачи не названы. Спросите в клинике ФИО врача и документы об ординатуре по нужной специальности.</p>';

  const licenseLinks = [
    ["Реестр лицензий МЗ КР", "https://license.med.kg/ru/"],
    ["Түндүк: лицензия по ИНН", "https://portal.tunduk.kg/public_services/opisanie/6323917"],
    ["Поиск юрлица (osoo.kg)", "https://www.osoo.kg/"],
  ].map(([t, u]) => `<a href="${u}" target="_blank" rel="noopener">${t} ↗</a>`).join("");
  const licStatus = { verified: "подтверждена в реестре", not_found: "НЕ найдена в реестре", not_checked: "не проверена" }[c.license.status];

  $("#modal-body").innerHTML = `
    <h2>${esc(c.name)}</h2>
    <div class="muted">${esc(c.address)}${c.legal_name ? " · " + esc(c.legal_name) : ""}${c.inn ? " · ИНН " + esc(c.inn) : ""}</div>
    <div class="chips">${flagChips(d.flags)}</div>
    <div class="contact">${c.phones.map((p) => `<a href="tel:${esc(p.replace(/[^+\d]/g, ""))}">${esc(p)}</a>`).join(" · ")}
      ${c.hours ? ` · ${esc(c.hours)}` : ""}</div>

    <h3>Индекс доверия: ${d.trust_index !== null ? fmt(d.trust_index, 0) : "не рассчитан"} <small class="muted">достоверность данных — ${esc(d.confidence)}</small></h3>
    <div class="components">${Object.entries(COMPONENT_LABELS).map(([k, label]) => `
      <div class="component"><div class="component-head"><span>${esc(label)}</span><b class="${scoreClass(comp[k].score)}">${fmt(comp[k].score, 0)}</b></div>
      <ul>${comp[k].reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")}</div>

    <h3>Откуда рейтинг</h3>
    ${c.ratings.length ? `<div class="table-wrap"><table><thead><tr><th>Площадка</th><th>Рейтинг</th><th>Оценок</th><th>Отзывов</th><th>Источник</th></tr></thead><tbody>${ratingRows}</tbody></table></div>
      <p class="hint">Если сводки расходятся, берём меньшие значения. Цифры из поисковой выдачи могут отставать от живой карточки — откройте её и сверьте.</p>`
      : '<p class="muted">Рейтинг найти не удалось.</p>'}

    <h3>Лицензия МЗ КР: ${esc(licStatus)}</h3>
    <p>${c.inn ? `ИНН юрлица известен (${esc(c.inn)}) — введите его в Түндүк, чтобы увидеть лицензию и разрешённые виды помощи.` : "ИНН неизвестен: попросите его в клинике (он есть в договоре и на чеке) и проверьте лицензию."}
    В 2025 году Минздрав нашёл 138 частных кабинетов без лицензии из 250 проверенных — проверка не формальность.</p>
    <div class="links">${licenseLinks}</div>

    <h3>Врачи и их квалификация</h3>${doctors}

    ${c.awards.length ? `<h3>Награды</h3><ul>${c.awards.map((a) => `<li>${esc(a.title)} <span class="muted">(${esc(a.note || "")}; в индексе не учитывается)</span></li>`).join("")}</ul>` : ""}
    ${c.notes.length ? `<h3>Заметки</h3><ul>${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    ${c.services.length ? `<h3>Услуги</h3><p>${c.services.map(esc).join(", ")}</p><p class="small">Источник: ${sourceLink(c.services_source)}</p>` : ""}

    <h3>Все источники</h3>
    <ul class="small">${[...c.all_sources.map(sourceLink), ...Object.entries(c.links)
      .filter(([, u]) => !c.all_sources.some((s) => s.url === u))
      .map(([k, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(k)}</a>`)].map((x) => `<li>${x}</li>`).join("")}</ul>

    <h3>Перед визитом</h3>
    <ol class="checklist">
      <li>Проверьте лицензию по ИНН и что в ней есть нужный вам вид помощи (наркоз/седация — отдельно).</li>
      <li>Спросите ФИО врача и покажите ему: «покажите диплом ординатуры/сертификат специалиста по этой специальности».</li>
      <li>Курсы производителей (Straumann, Osstem, Ormco…) — это 1–5 дней обучения, а не специализация.</li>
      <li>Прочитайте 10 последних отзывов с оценкой 1–3★ и раздел «Неподтверждённые» в 2ГИС.</li>
      <li>Возьмите письменный план лечения с ценой каждого этапа и гарантией.</li>
    </ol>`;
  $("#modal").hidden = false;
}

/* ------------------------------------------------------------ подбор */
async function runMatch() {
  const out = $("#match-out");
  out.innerHTML = '<div class="placeholder">Считаем…</div>';
  try {
    const res = await api("/api/match", { method: "POST", body: JSON.stringify({ problem: $("#problem").value, need_24_7: $("#m247").checked }) });
    const head = res.topics.length ? `Распознано: <b>${res.topics.map(esc).join(", ")}</b>${res.need_24_7 ? " · только круглосуточные" : ""}` : "Направление не распознано — показываем общий рейтинг доверия.";
    out.innerHTML = `<p class="hint">${head}. Соответствие = индекс доверия × (0.6 + 0.4 × доля нужных услуг, которые клиника указывает).</p>`
      + (res.results.length ? res.results.slice(0, 10).map((r, i) => clinicCard(r, false, i + 1)).join("") : '<div class="placeholder">Нет клиник с рейтингом под этот запрос.</div>');
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------ отзывы */
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
  const aggregate = {};
  if ($("#agg-rating").value) aggregate.rating = Number($("#agg-rating").value);
  if ($("#agg-count").value) aggregate.ratings_count = Number($("#agg-count").value);
  if ($("#agg-unconf").value) aggregate.unconfirmed_count = Number($("#agg-unconf").value);
  out.innerHTML = '<div class="placeholder">Анализируем…</div>';
  try {
    const a = await api("/api/analyze/reviews", { method: "POST", body: JSON.stringify({ raw, aggregate: Object.keys(aggregate).length ? aggregate : null }) });
    const verdictCls = { organic: "good", some_signals: "mid", strong_signals: "low", insufficient_data: "na" }[a.verdict];
    out.innerHTML = `<div class="card">
      <div class="big-score"><div class="score ${verdictCls}">${fmt(a.authenticity_index, 0)}</div>
        <div><div class="verdict">${esc(a.verdict_text)}</div>
        <div class="muted">Индекс подлинности (100 — признаков манипуляции нет) · отзывов: ${a.total}, с датами: ${a.analyzed_with_dates} · уверенность: ${esc(a.confidence)}</div></div></div>
      <div class="two-col">
        <div><b>Распределение оценок</b>${distributionBars(a.rating_distribution)}</div>
        <div><b>Рейтинг до и после очистки</b>
          <div class="cleaned"><span>${fmt(a.raw_mean_rating, 2)}★</span> → <span>${fmt(a.cleaned_mean_rating, 2)}★</span></div>
          <div class="muted small">Без ${a.suspicious_count} подозрительных отзывов (осталось ${a.cleaned_count}).</div></div>
      </div></div>
      ${a.signals.map((s) => `<div class="signal ${SEVERITY[s.severity]}">
        <div class="signal-head"><b>${esc(s.title)}</b>${s.penalty ? `<span class="penalty">−${fmt(s.penalty, 0)}</span>` : ""}</div>
        <p>${esc(s.explanation)}</p>
        ${s.evidence.length ? `<ul class="small">${s.evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${s.reference ? `<div class="ref">${esc(s.reference)}</div>` : ""}</div>`).join("")}
      ${a.suspicious_reviews.length ? `<h3>Отмеченные отзывы</h3><div class="table-wrap"><table><thead><tr><th>#</th><th>Дата</th><th>★</th><th>Текст</th><th>Почему</th></tr></thead><tbody>
        ${a.suspicious_reviews.slice(0, 40).map((f) => `<tr class="${f.suspicion >= 0.5 ? "row-bad" : ""}"><td>${f.index}</td><td>${esc(f.date || "")}</td><td>${f.rating ?? ""}</td>
          <td>${esc(f.excerpt)}</td><td class="small">${f.reasons.map(esc).join("; ")}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------ сертификат */
async function runCert() {
  const num = (id) => ($(id).value ? Number($(id).value) : null);
  const body = {
    title: $("#c-title").value.trim(), issuer: $("#c-issuer").value.trim() || null, year: num("#c-year"),
    document_id: $("#c-id").value.trim() || null, holder_graduation_year: num("#c-grad"),
    holder_experience_years: num("#c-exp"), holder_specialty: $("#c-spec").value.trim() || null,
    evidence_level: Number($("#c-level").value),
  };
  const out = $("#cert-out");
  if (!body.title) { out.innerHTML = '<div class="error">Укажите название документа.</div>'; return; }
  try {
    const v = await api("/api/analyze/credential", { method: "POST", body: JSON.stringify(body) });
    out.innerHTML = `<div class="card">${v.issuer_name ? `<div class="muted">Эмитент: ${esc(v.issuer_name)} ${v.issuer_known ? "(есть в справочнике)" : "(нет в справочнике)"}</div>` : ""}${credentialBlock(v)}</div>`;
  } catch (e) {
    out.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------ методика и аудит */
let methodLoaded = false;
async function loadMethod() {
  if (methodLoaded) return;
  const m = await api("/api/methodology");
  methodLoaded = true;
  $("#method-out").innerHTML = `
    <h2>Как считается индекс доверия</h2>
    <p><b>Индекс = ${Object.entries(m.weights).map(([k, w]) => `${Math.round(w * 100)}% ${esc(COMPONENT_LABELS[k].toLowerCase())}`).join(" + ")}</b></p>
    <h3>1. Рейтинг с поправкой на объём</h3>
    <p>Байесовское среднее: рейтинг «подтягивается» к среднему по городу тем сильнее, чем меньше оценок (25 виртуальных оценок на уровне среднего). Затем берём нижнюю границу 80%-го интервала: 5.0 при 14 оценках весит меньше, чем 4.9 при 500. Если сводки расходятся — берём меньшие значения.</p>
    <h3>2. Подлинность отзывов</h3>
    <p>Если отзывы загружены — считаем 8 независимых признаков (ниже). Если нет — ставим нейтральные 70 и снижаем только за очевидные аномалии (почти 100% пятёрок при сотне оценок, расхождение площадок, неподтверждённые отзывы 2ГИС). Уверенность в этом случае низкая.</p>
    <ul>${Object.entries(m.review_references).map(([k, v]) => `<li>${esc(v)}</li>`).join("")}</ul>
    <h3>3. Квалификация</h3>
    <p>Лицензия, подтверждённая в реестре, даёт больше всего. Каждое заявление о квалификации проверяется по типу документа и уровню доказанности:</p>
    <div class="table-wrap"><table><thead><tr><th>Уровень</th><th>Что это значит</th></tr></thead><tbody>
      ${Object.entries(m.evidence_levels).map(([k, v]) => `<tr><td>${k}</td><td>${esc(v)}</td></tr>`).join("")}</tbody></table></div>
    <div class="table-wrap"><table><thead><tr><th>Тип документа</th><th>Доказывает</th><th>Не доказывает</th><th>Вес</th></tr></thead><tbody>
      ${Object.values(m.claim_types).map((t) => `<tr><td>${esc(t.label)}</td><td>${esc(t.proves)}</td><td>${esc(t.does_not_prove)}</td><td>${t.weight}</td></tr>`).join("")}</tbody></table></div>
    <h3>4. Прозрачность</h3>
    <p>Сайт, названные врачи, юрлицо, присутствие на медицинских площадках, телефоны, часы, описание услуг. Отражает то, что удалось найти к дате сбора.</p>
    <h3>Ограничения — честно</h3>
    <ul>
      <li>Рейтинги взяты из поисковой выдачи, а не напрямую из 2ГИС: прямой доступ был закрыт сетевыми ограничениями. Запустите <code>python -m tools.refresh_2gis --key ВАШ_КЛЮЧ</code>, чтобы обновить их через официальный API 2ГИС.</li>
      <li>Ни одна лицензия ещё не сверена с реестром МЗ КР. Это надо сделать вручную по ИНН.</li>
      <li>Пороги детекторов накрутки откалиброваны на синтетических данных и исследованиях; на реальных данных их стоит уточнять.</li>
      <li>Ни один признак не доказывает накрутку в одиночку — мы показываем, на чём основан вывод, чтобы вы могли проверить сами.</li>
    </ul>
    <h3>Где проверять</h3>
    <ul>${Object.values(m.verify_links).flat().map((l) => `<li><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)} ↗</a></li>`).join("")}</ul>`;
}

let auditLoaded = false;
async function loadAudit() {
  if (auditLoaded) return;
  const a = await api("/api/legacy-audit");
  auditLoaded = true;
  const cls = { inflated: "red", partially_true: "yellow", not_confirmed: "red", not_found: "red" };
  const keyLabels = { rating: "рейтинг", reviews: "отзывов", address: "адрес", phone: "телефон", note: "" };
  const fmtObj = (o) => Object.entries(o).map(([k, v]) => `<div>${keyLabels[k] ? `<span class="muted">${esc(keyLabels[k])}:</span> ` : ""}${esc(v)}</div>`).join("");
  $("#audit-out").innerHTML = `<div class="card"><h2>Что было не так в прошлой версии</h2><p>${esc(a.summary)}</p>
    <div class="chips">${Object.entries(a.verdict_labels).map(([k, v]) => `<span class="chip ${cls[k]}">${esc(v)}</span>`).join("")}</div></div>
    <div class="table-wrap"><table class="audit"><thead><tr><th>Клиника</th><th>Было в базе</th><th>Нашли в источниках</th><th>Проблемы</th></tr></thead><tbody>
    ${a.entries.map((e) => `<tr><td><b>${esc(e.name)}</b><br><span class="chip ${cls[e.verdict]}">${esc(a.verdict_labels[e.verdict])}</span></td>
      <td class="small">${fmtObj(e.old)}</td><td class="small">${fmtObj(e.found)}</td>
      <td class="small"><ul>${e.issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        ${e.sources.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">источник ↗</a>`).join(" ")}</td></tr>`).join("")}
    </tbody></table></div>`;
}

/* ------------------------------------------------------------ запуск */
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  loadMeta().catch((e) => { $("#notice-text").textContent = e.message; });
  loadList();
  $("#q").addEventListener("input", debounce(loadList, 250));
  ["#topic", "#sort", "#only247"].forEach((s) => $(s).addEventListener("change", loadList));
  document.addEventListener("click", (e) => {
    const open = e.target.closest("[data-open]");
    if (open) openClinic(open.dataset.open);
    const ex = e.target.closest("[data-example]");
    if (ex) api(`/api/examples/${ex.dataset.example}`).then((t) => { $("#reviews-raw").value = t; runReviews(); });
  });
  $("#modal-close").addEventListener("click", () => { $("#modal").hidden = true; });
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").hidden = true; });
  $("#match-btn").addEventListener("click", runMatch);
  $("#reviews-btn").addEventListener("click", runReviews);
  $("#reviews-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (f) { $("#reviews-raw").value = await f.text(); runReviews(); }
  });
  $("#cert-btn").addEventListener("click", runCert);
  $("#cert-demo").addEventListener("click", () => {
    $("#c-title").value = "Master of Oral Implantology & Guided Surgery";
    $("#c-issuer").value = "Straumann Dental Implant System (Basel, Switzerland)";
    $("#c-year").value = 2021; $("#c-id").value = "CH-STR-84920-KG";
    $("#c-grad").value = 2008; $("#c-exp").value = ""; $("#c-spec").value = "челюстно-лицевой хирург";
    $("#c-level").value = "1";
    runCert();
  });
});
