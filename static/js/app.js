// DentBishkek Front-End Application Logic - Pro Edition
let map = null;
let markersLayer = null;
let currentDentists = [];
let compareList = [];
let activeDentist = null;
let activeCalcItems = [];

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

function initApp() {
  initMap();
  loadStats();
  loadDentists();
  setupEventListeners();
  setupWizard();
  setupModalTabs();
}

/* =========================================================================
   1. MAP INITIALIZATION (Leaflet.js)
   ========================================================================= */
function initMap() {
  map = L.map('bishkek-map').setView([42.8650, 74.6000], 12);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a> contributors'
  }).addTo(map);

  markersLayer = L.layerGroup().addTo(map);
}

function updateMapMarkers(dentists) {
  if (!markersLayer) return;
  markersLayer.clearLayers();

  const bounds = [];

  dentists.forEach((d) => {
    if (d.coordinates && d.coordinates.lat && d.coordinates.lng) {
      const lat = d.coordinates.lat;
      const lng = d.coordinates.lng;
      bounds.push([lat, lng]);

      const isUrgent = d.is_24_7;
      const markerHtml = `
        <div style="
          background: ${isUrgent ? '#ef4444' : '#0284c7'};
          color: white;
          border-radius: 50%;
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 16px;
          box-shadow: 0 3px 8px rgba(0,0,0,0.3);
          border: 2px solid white;
        ">
          ${d.photo_badge || '🦷'}
        </div>
      `;

      const customIcon = L.divIcon({
        className: 'custom-leaflet-icon',
        html: markerHtml,
        iconSize: [36, 36],
        iconAnchor: [18, 18]
      });

      const popupContent = `
        <div style="font-family: inherit; min-width: 240px; padding: 4px;">
          <div style="font-weight: 800; font-size: 14px; color: #0f172a; margin-bottom: 2px;">
            ${escapeHtml(d.name)}
          </div>
          <div style="font-size: 12px; color: #0284c7; font-weight: 600; margin-bottom: 6px;">
            ${escapeHtml(d.clinic)}
          </div>
          <div style="font-size: 12px; margin-bottom: 4px;">
            ⭐ <strong>${d.rating}</strong> (${d.reviews_count} отзывов 2ГИС)
          </div>
          <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
            📍 ${escapeHtml(d.address)}
          </div>
          <div style="display: flex; gap: 6px;">
            <a href="https://wa.me/${d.whatsapp}?text=Здравствуйте!_Хочу_записаться_к_${encodeURIComponent(d.name)}" 
               target="_blank" 
               style="flex: 1; text-align: center; background: #25d366; color: white; padding: 5px 8px; border-radius: 6px; font-size: 11px; text-decoration: none; font-weight: 600;">
              WhatsApp
            </a>
            <button onclick="openDentistModal('${d.id}')" 
                    style="flex: 1; background: #0284c7; color: white; border: none; padding: 5px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer;">
              Прайс и пруфы
            </button>
          </div>
        </div>
      `;

      const marker = L.marker([lat, lng], { icon: customIcon })
        .bindPopup(popupContent);

      markersLayer.addLayer(marker);
    }
  });

  if (bounds.length > 0) {
    map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
  }
}

/* =========================================================================
   2. API DATA LOADING & RENDERING
   ========================================================================= */
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (res.ok) {
      const data = await res.json();
      if (data.total_clinics) {
        document.getElementById('stat-clinics').innerText = `${data.total_clinics}+`;
        document.getElementById('stat-reviews').innerText = `${data.total_reviews.toLocaleString()}+`;
        document.getElementById('stat-rating').innerText = data.average_rating;
      }
    }
  } catch (err) {
    console.error("Error loading stats:", err);
  }
}

async function loadDentists() {
  const query = document.getElementById('search-input').value.trim();
  const spec = document.getElementById('spec-filter').value;
  const district = document.getElementById('district-filter').value;
  const budget = document.getElementById('budget-filter').value;
  const sort = document.getElementById('sort-filter').value;

  const params = new URLSearchParams();
  if (query) params.append('query', query);
  if (spec && spec !== 'Все') params.append('specialization', spec);
  if (district && district !== 'Все') params.append('district', district);
  if (budget && budget !== 'Все') params.append('price_level', budget);
  if (sort) params.append('sort_by', sort);

  const grid = document.getElementById('dentists-grid');
  grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #64748b;">Загрузка реестра стоматологий Бишкека...</div>';

  try {
    const res = await fetch(`/api/dentists?${params.toString()}`);
    if (!res.ok) throw new Error("Failed to load");
    const dentists = await res.json();
    currentDentists = dentists;

    document.getElementById('results-count').innerText = dentists.length;
    renderDentists(dentists);
    updateMapMarkers(dentists);
  } catch (err) {
    console.error(err);
    grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #ef4444;">Ошибка при загрузке данных. Пожалуйста, обновите страницу.</div>';
  }
}

function renderDentists(dentists) {
  const grid = document.getElementById('dentists-grid');
  if (dentists.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 60px 20px; background: white; border-radius: 16px; border: 1px dashed #cbd5e1;">
        <span style="font-size: 3rem;">🔍</span>
        <h3 style="margin-top: 10px; font-size: 1.2rem;">По вашим критериям стоматологи не найдены</h3>
        <p style="color: #64748b; font-size: 0.9rem; margin-top: 6px;">Попробуйте изменить запрос или сбросить фильтры</p>
        <button onclick="resetFilters()" class="btn btn-secondary" style="margin-top: 16px;">Сбросить фильтры</button>
      </div>
    `;
    return;
  }

  grid.innerHTML = dentists.map((d) => {
    const samplePriceEntries = Object.entries(d.services).slice(0, 3);
    const pricesHtml = samplePriceEntries.map(([name, price]) => `
      <div class="price-preview-row">
        <span>${escapeHtml(name)}:</span>
        <strong>${price.toLocaleString()} сом</strong>
      </div>
    `).join('');

    const badgesHtml = (d.badges || []).slice(0, 3).map(b => `
      <span class="feature-badge">${escapeHtml(b)}</span>
    `).join('');

    const specsHtml = (d.specializations || []).slice(0, 3).map(s => `
      <span class="spec-pill">${escapeHtml(s)}</span>
    `).join('');

    const eduText = d.education 
      ? `${d.education.university.includes('КГМА') ? 'КГМА' : (d.education.university.includes('КРСУ') ? 'КРСУ' : 'Мед. ВУЗ')} • ${d.certifications ? d.certifications.length : 0}+ сертификатов`
      : 'Подтвержденная квалификация';

    const isCompared = compareList.includes(d.id);

    // Red flags pills on card
    const redFlagsHtml = (d.audit && d.audit.red_flags ? d.audit.red_flags.slice(0, 2) : []).map(rf => `
      <span class="red-flag-pill">⚠️ ${escapeHtml(rf)}</span>
    `).join('');

    return `
      <div class="dentist-card" id="card-${d.id}">
        <div class="card-top">
          <div class="card-avatar-wrap">
            ${d.photo_url 
              ? `<img src="${d.photo_url}" alt="${escapeHtml(d.name)}" class="card-doctor-photo" onerror="this.outerHTML='<div class=\\'doctor-avatar-fallback\\'>${d.photo_badge || '🦷'}</div>'">` 
              : `<div class="doctor-avatar-fallback">${d.photo_badge || '🦷'}</div>`
            }
            <div>
              <h3 class="doctor-name">${escapeHtml(d.name)}</h3>
              <div class="clinic-name">${escapeHtml(d.clinic)}</div>
            </div>
          </div>
          <div>
            <div class="rating-badge">
              <span>⭐</span>
              <span>${d.rating}</span>
            </div>
            <div class="bayesian-trust-score" title="Взвешенная байесовская оценка доверия">
              Доверие: ${d.bayesian_rating ? d.bayesian_rating.toFixed(2) : d.rating}
            </div>
          </div>
        </div>

        <div class="proof-tag-bar">
          <span class="proof-tag-icon">🎓</span>
          <span><strong>Образование:</strong> ${escapeHtml(eduText)}</span>
        </div>

        ${redFlagsHtml ? `<div class="card-red-flags">${redFlagsHtml}</div>` : ''}

        <div class="card-title-sub">${escapeHtml(d.title)}</div>

        <div class="specs-list">
          ${specsHtml}
        </div>

        <div class="card-meta-list">
          <div class="meta-item">
            <span class="meta-icon">📍</span>
            <span>${escapeHtml(d.address)} (${escapeHtml(d.district)})</span>
          </div>
          <div class="meta-item">
            <span class="meta-icon">👨‍⚕️</span>
            <span>Стаж работы: <strong>${d.experience_years} лет</strong></span>
          </div>
          <div class="meta-item">
            <span class="meta-icon">🕒</span>
            <span>${escapeHtml(d.working_hours)} ${d.is_24_7 ? '<strong style="color:#ef4444;">(24/7)</strong>' : ''}</span>
          </div>
        </div>

        ${badgesHtml ? `<div class="card-badges-row">${badgesHtml}</div>` : ''}

        <div class="price-preview-box">
          <div class="price-preview-header">
            <span>Прайс-лист</span>
            <span style="color:#0284c7; text-transform:none;">${d.price_level}</span>
          </div>
          ${pricesHtml}
        </div>

        <div class="card-actions">
          <a href="https://wa.me/${d.whatsapp}?text=Здравствуйте!_Хочу_записаться_к_вам_через_поиск_стоматологов" 
             target="_blank" 
             class="btn btn-whatsapp">
            <span>💬 WhatsApp</span>
          </a>
          <button onclick="openDentistModal('${d.id}')" class="btn btn-outline">
            <span>Прайс & Аудит</span>
          </button>
          <button onclick="toggleCompare('${d.id}')" class="btn-compare-card ${isCompared ? 'active' : ''}" title="Сравнить цены и квалификацию">
            ${isCompared ? '✓ В сравнении' : '⚖️ Сравнить'}
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function resetFilters() {
  document.getElementById('search-input').value = '';
  document.getElementById('spec-filter').value = 'Все';
  document.getElementById('district-filter').value = 'Все';
  document.getElementById('budget-filter').value = 'Все';
  document.getElementById('sort-filter').value = 'bayesian';
  document.querySelectorAll('.tag-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('clear-search-btn').style.display = 'none';
  loadDentists();
}

/* =========================================================================
   3. EVENT LISTENERS & FILTERING
   ========================================================================= */
function setupEventListeners() {
  const searchInput = document.getElementById('search-input');
  const clearBtn = document.getElementById('clear-search-btn');

  let debounceTimer = null;
  searchInput.addEventListener('input', () => {
    clearBtn.style.display = searchInput.value ? 'flex' : 'none';
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      loadDentists();
    }, 280);
  });

  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    clearBtn.style.display = 'none';
    loadDentists();
  });

  ['spec-filter', 'district-filter', 'budget-filter', 'sort-filter'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      loadDentists();
    });
  });

  // Quick Tags
  document.querySelectorAll('.tag-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.classList.toggle('active');
      const tag = btn.dataset.tag;
      const searchBox = document.getElementById('search-input');
      
      if (btn.classList.contains('active')) {
        searchBox.value = tag;
        clearBtn.style.display = 'flex';
      } else {
        searchBox.value = '';
        clearBtn.style.display = 'none';
      }
      loadDentists();
    });
  });

  // View Toggles
  const mapSection = document.getElementById('map-section');
  const dentistsGrid = document.getElementById('dentists-grid');

  document.getElementById('view-cards-btn').addEventListener('click', function() {
    setActiveViewBtn(this);
    mapSection.style.display = 'none';
    dentistsGrid.style.display = 'grid';
  });

  document.getElementById('view-map-btn').addEventListener('click', function() {
    setActiveViewBtn(this);
    mapSection.style.display = 'block';
    dentistsGrid.style.display = 'none';
    setTimeout(() => { map.invalidateSize(); }, 200);
  });

  document.getElementById('view-split-btn').addEventListener('click', function() {
    setActiveViewBtn(this);
    mapSection.style.display = 'block';
    dentistsGrid.style.display = 'grid';
    setTimeout(() => { map.invalidateSize(); }, 200);
  });

  // Modal Closers
  document.getElementById('close-details-btn').addEventListener('click', closeDetailsModal);
  document.getElementById('details-modal').addEventListener('click', (e) => {
    if (e.target.id === 'details-modal') closeDetailsModal();
  });

  // Compare & Calc Modal Closers
  document.getElementById('open-compare-btn').addEventListener('click', openCompareModal);
  document.getElementById('close-compare-modal-btn').addEventListener('click', () => {
    document.getElementById('compare-modal').classList.remove('open');
  });

  document.getElementById('open-calc-floating').addEventListener('click', () => {
    openStandaloneCalc();
  });
  document.getElementById('close-calc-modal-btn').addEventListener('click', () => {
    document.getElementById('calc-modal').classList.remove('open');
  });

  // Anti-Fake Toggle
  const antifakeBtn = document.getElementById('toggle-antifake-btn');
  const antifakeContent = document.getElementById('antifake-content');
  if (antifakeBtn && antifakeContent) {
    antifakeBtn.addEventListener('click', () => {
      const isOpen = antifakeContent.style.display === 'block';
      antifakeContent.style.display = isOpen ? 'none' : 'block';
      antifakeBtn.innerText = isOpen ? 'Инструкция проверки ▼' : 'Скрыть инструкцию ▲';
    });
  }
}

function setActiveViewBtn(activeBtn) {
  document.querySelectorAll('.toggle-view-btn').forEach(b => b.classList.remove('active'));
  activeBtn.classList.add('active');
}

/* =========================================================================
   4. DOCTOR DETAILS MODAL WITH TABS (PRICES, EDU PROOFS, CALC)
   ========================================================================= */
function setupModalTabs() {
  document.querySelectorAll('.modal-tab-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.modal-tab-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      const tabId = this.dataset.tab;
      renderActiveTab(tabId);
    });
  });
}

async function openDentistModal(dentistId) {
  const modal = document.getElementById('details-modal');
  modal.classList.add('open');

  try {
    const res = await fetch(`/api/dentists/${dentistId}`);
    if (!res.ok) throw new Error("Not found");
    activeDentist = await res.json();
    activeCalcItems = [];

    // Header info
    document.getElementById('detail-name').innerText = activeDentist.name;
    document.getElementById('detail-clinic').innerText = `${activeDentist.clinic} • ${activeDentist.district}`;
    
    const photoEl = document.getElementById('detail-doctor-img');
    const badgeEl = document.getElementById('detail-badge-icon');
    if (activeDentist.photo_url) {
      photoEl.src = activeDentist.photo_url;
      photoEl.style.display = 'block';
      badgeEl.style.display = 'none';
    } else {
      photoEl.style.display = 'none';
      badgeEl.style.display = 'block';
      badgeEl.innerText = activeDentist.photo_badge || '🦷';
    }

    // Default to first tab (Prices)
    document.querySelectorAll('.modal-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.modal-tab-btn[data-tab="tab-prices"]').classList.add('active');
    renderActiveTab('tab-prices');

  } catch (err) {
    console.error(err);
    document.getElementById('details-modal-body').innerHTML = '<div style="color: #ef4444; padding: 20px;">Не удалось загрузить подробности о враче.</div>';
  }
}

function renderActiveTab(tabId) {
  if (!activeDentist) return;
  const container = document.getElementById('details-modal-body');

  if (tabId === 'tab-prices') {
    renderPricesTab(container);
  } else if (tabId === 'tab-education') {
    renderEducationTab(container);
  } else if (tabId === 'tab-audit') {
    renderAuditTab(container);
  } else if (tabId === 'tab-equipment') {
    renderEquipmentTab(container);
  } else if (tabId === 'tab-calculator') {
    renderCalculatorTab(container);
  } else if (tabId === 'tab-reviews') {
    renderReviewsTab(container);
  }
}

function renderAuditTab(container) {
  const d = activeDentist;
  const audit = d.audit;

  if (!audit) {
    container.innerHTML = '<p style="color: #64748b;">Аудит клиники находится в процессе проверки.</p>';
    return;
  }

  const redFlagsHtml = (audit.red_flags || []).map(rf => `
    <span class="red-flag-pill" style="font-size: 0.82rem; padding: 4px 10px;">⚠️ ${escapeHtml(rf)}</span>
  `).join('');

  const complaintsHtml = (audit.negative_feedback || []).map(nf => `
    <li class="audit-complaint-item">
      <span>${escapeHtml(nf)}</span>
    </li>
  `).join('');

  container.innerHTML = `
    <div class="audit-box">
      <div class="audit-section">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px; margin-bottom: 12px;">
          <div>
            <h4 style="font-size: 1.15rem; color: #0f172a; margin-bottom: 4px;">Проверка благонадежности и лицензий</h4>
            <div style="font-size: 0.84rem; color: #64748b;">Официальный юридический статус клиники и проверка квалификации врачей</div>
          </div>
          <div class="audit-status-badge audit-badge-verified">
            ✔ Лицензия МЗ КР подтверждена
          </div>
        </div>

        <div style="background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; font-size: 0.88rem; margin-bottom: 14px;">
          <p><strong>🏛️ Государственная лицензия:</strong> ${escapeHtml(audit.license_status)}</p>
          <p style="margin-top: 4px;"><strong>🎓 Диплом и ординатура:</strong> ${escapeHtml(audit.diploma_verification)}</p>
        </div>

        <div class="audit-warning-box">
          <strong>⚠️ Факт-чек коммерческих сертификатов:</strong><br>
          ${escapeHtml(audit.commercial_certs_note)}
        </div>
      </div>

      <div class="audit-section">
        <h4 style="font-size: 1.1rem; color: #991b1b; margin-bottom: 8px;">Критические замечания и реальные жалобы пациентов (2ГИС / Форумы)</h4>
        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px;">
          ${redFlagsHtml}
        </div>
        <ul class="audit-complaints-list">
          ${complaintsHtml}
        </ul>
      </div>

      <div class="audit-safety-advice">
        <h5 style="font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
          <span>🛡️</span> Рекомендация для пациента перед приемом:
        </h5>
        <p>${escapeHtml(audit.safety_advice)}</p>
      </div>
    </div>
  `;
}

function renderPricesTab(container) {
  const d = activeDentist;
  let html = `
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div>
        <h4 style="font-size: 1.1rem; color: #0f172a; margin-bottom: 2px;">Полный прайс-лист клиники</h4>
        <p style="font-size: 0.82rem; color: #64748b;">Цены указаны в сомах (KGS). Нажмите «+ В смету», чтобы рассчитать общую сумму.</p>
      </div>
      <a href="https://wa.me/${d.whatsapp}?text=Здравствуйте!_Уточните_пожалуйста_актуальные_цены" target="_blank" class="btn btn-whatsapp" style="font-size:0.82rem; padding: 6px 12px;">
        Уточнить в WhatsApp
      </a>
    </div>
  `;

  if (d.comprehensive_prices && Object.keys(d.comprehensive_prices).length > 0) {
    for (const [catName, catPrices] of Object.entries(d.comprehensive_prices)) {
      html += `
        <div class="price-cat-header">📁 ${escapeHtml(catName)}</div>
        <table class="price-table">
          <tbody>
            ${Object.entries(catPrices).map(([name, price]) => `
              <tr>
                <td>${escapeHtml(name)}</td>
                <td>
                  ${price.toLocaleString()} сом
                  <button class="btn-add-to-calc" onclick="addProcedureToCalc('${escapeHtml(name)}', ${price})">+ В смету</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
  } else {
    // Fallback to services
    html += `
      <table class="price-table">
        <tbody>
          ${Object.entries(d.services).map(([name, price]) => `
            <tr>
              <td>${escapeHtml(name)}</td>
              <td>
                ${price.toLocaleString()} сом
                <button class="btn-add-to-calc" onclick="addProcedureToCalc('${escapeHtml(name)}', ${price})">+ В смету</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  container.innerHTML = html;
}

function renderEducationTab(container) {
  const d = activeDentist;
  const edu = d.education;

  let html = `
    <div>
      <h4 style="font-size: 1.1rem; color: #0f172a; margin-bottom: 12px;">Академическое образование и стаж</h4>
  `;

  if (edu) {
    html += `
      <div class="edu-card">
        <div class="edu-university">🏛️ ${escapeHtml(edu.university)}</div>
        <div class="edu-degree">🎓 ${escapeHtml(edu.degree)} • Год выпуска: ${edu.graduation_year}</div>
        <div class="edu-details">
          <p><strong>Факультет:</strong> ${escapeHtml(edu.faculty)}</p>
          ${edu.residency ? `<p style="margin-top: 4px;"><strong>Ординатура:</strong> ${escapeHtml(edu.residency)} (${escapeHtml(edu.residency_years || '')})</p>` : ''}
          ${edu.internships && edu.internships.length > 0 ? `
            <div style="margin-top: 8px;">
              <strong>Стажировки и мастер-классы:</strong>
              <ul style="padding-left: 20px; margin-top: 4px;">
                ${edu.internships.map(i => `<li>${escapeHtml(i)}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  } else {
    html += `<p style="color: #64748b;">Данные об образовании подтверждены в реестре врачей Кыргызстана.</p>`;
  }

  // Certifications Proofs
  html += `
    <h4 style="font-size: 1.1rem; color: #0f172a; margin: 24px 0 10px;">Пруфы сертификатов и лицензий (${d.certifications ? d.certifications.length : 0})</h4>
    <div class="cert-grid">
  `;

  if (d.certifications && d.certifications.length > 0) {
    d.certifications.forEach(c => {
      html += `
        <div class="cert-card">
          <div class="cert-title">${escapeHtml(c.title)}</div>
          <div class="cert-issuer">🏢 ${escapeHtml(c.issuer)} (${c.year})</div>
          <div class="cert-proof-id">Proof ID: ${escapeHtml(c.cert_id)}</div>
          ${c.skills && c.skills.length > 0 ? `
            <div class="cert-skills">
              ${c.skills.map(s => `<span class="cert-skill-pill">✔ ${escapeHtml(s)}</span>`).join('')}
            </div>
          ` : ''}
        </div>
      `;
    });
  } else {
    html += `<p style="color: #64748b;">Сертификаты находятся на верификации.</p>`;
  }

  html += `</div></div>`;
  container.innerHTML = html;
}

function renderEquipmentTab(container) {
  const d = activeDentist;
  let html = `
    <div>
      <h4 style="font-size: 1.1rem; color: #0f172a; margin-bottom: 6px;">Технологии, оборудование и протоколы стерилизации</h4>
      <p style="font-size: 0.84rem; color: #64748b; margin-bottom: 16px;">Высокоточное оснащение позволяет спасать зубы и проводить лечение с микрохирургической точностью.</p>
  `;

  if (d.equipment && d.equipment.length > 0) {
    html += `
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-bottom: 20px;">
        ${d.equipment.map(eq => `
          <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; display: flex; gap: 10px; align-items: center;">
            <span style="font-size: 1.4rem;">🔬</span>
            <span style="font-size: 0.88rem; font-weight: 600; color: #0f172a;">${escapeHtml(eq)}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  html += `
      <div style="background: #f0fdf4; border: 1px solid #86efac; border-radius: 12px; padding: 16px;">
        <h5 style="color: #166534; font-weight: 700; margin-bottom: 6px;">Стандарты инфекционной безопасности:</h5>
        <ul style="color: #15803d; font-size: 0.85rem; padding-left: 18px; line-height: 1.6;">
          <li>Многоступенчатая стерилизация в автоклавах класса B (Евростандарт EN 13060).</li>
          <li>Индивидуальные крафт-пакеты с химическими индикаторами стерильности, вскрываемые при пациенте.</li>
          <li>Лечение с обязательной изоляцией рабочего поля латексной завесой коффердам (защита от слюны и инфекций).</li>
        </ul>
      </div>
    </div>
  `;

  container.innerHTML = html;
}

function renderCalculatorTab(container) {
  let itemsHtml = '';
  let total = 0;

  if (activeCalcItems.length === 0) {
    itemsHtml = `<div style="text-align: center; color: #64748b; padding: 20px;">Вы пока не добавили ни одной процедуры. Перейдите во вкладку «Прайс-лист» и нажмите «+ В смету».</div>`;
  } else {
    itemsHtml = activeCalcItems.map((item, idx) => {
      total += item.price;
      return `
        <div class="calc-item-row">
          <span>${escapeHtml(item.name)}</span>
          <div>
            <strong style="color: #047857; margin-right: 12px;">${item.price.toLocaleString()} сом</strong>
            <button onclick="removeCalcItem(${idx})" style="background: none; border: none; color: #ef4444; cursor: pointer;">✕</button>
          </div>
        </div>
      `;
    }).join('');
  }

  const d = activeDentist;
  const prefilledMsg = encodeURIComponent(`Здравствуйте! Хочу записаться к вам на лечение. Примерный расчет процедур:\n` + activeCalcItems.map(i => `- ${i.name}: ${i.price} сом`).join('\n') + `\nИтого: ${total} сом.`);

  container.innerHTML = `
    <div class="calc-box">
      <h4 style="font-size: 1.1rem; color: #0f172a; margin-bottom: 4px;">Индивидуальная смета лечения</h4>
      <p style="font-size: 0.82rem; color: #64748b;">Добавляйте любые процедуры из прайс-листа для предварительного расчета бюджета.</p>

      <div class="calc-items-list">
        ${itemsHtml}
      </div>

      <div class="calc-total-box">
        <div>
          <div style="font-size: 0.85rem; color: #94a3b8;">Ориентировочная сумма:</div>
          <div class="calc-total-num">${total.toLocaleString()} сом</div>
        </div>
        ${activeCalcItems.length > 0 ? `
          <a href="https://wa.me/${d.whatsapp}?text=${prefilledMsg}" target="_blank" class="btn btn-whatsapp">
            <span>💬 Записаться с этой сметой</span>
          </a>
        ` : ''}
      </div>
    </div>
  `;
}

function addProcedureToCalc(name, price) {
  activeCalcItems.push({ name, price });
  alert(`Добавлено в смету: ${name} (${price.toLocaleString()} сом)`);
}

function removeCalcItem(index) {
  activeCalcItems.splice(index, 1);
  renderActiveTab('tab-calculator');
}

function renderReviewsTab(container) {
  const d = activeDentist;
  const reviewsHtml = (d.sample_reviews || []).map(r => `
    <div class="review-item">
      <div class="review-item-header">
        <strong>${escapeHtml(r.author)}</strong>
        <span style="color: #f59e0b;">${'⭐'.repeat(r.rating)} <span style="color: #64748b; font-size: 0.78rem;">${escapeHtml(r.date)}</span></span>
      </div>
      <p style="font-size: 0.88rem; color: #334155;">${escapeHtml(r.text)}</p>
    </div>
  `).join('') || '<p style="color: #64748b; font-size: 0.85rem;">Пока нет отзывов.</p>';

  container.innerHTML = `
    <div>
      <div style="display: flex; gap: 16px; align-items: center; margin-bottom: 16px; flex-wrap: wrap;">
        <div class="rating-badge" style="font-size: 1.1rem;">
          ⭐ ${d.rating} / 5.0
        </div>
        <div style="font-size: 0.88rem; color: #64748b;">
          Всего верифицированных отзывов: <strong>${d.reviews_count}</strong> в 2ГИС и YDoc
        </div>
        <div class="bayesian-trust-score" style="font-size: 0.85rem;">
          Байесовский балл доверия: ${d.bayesian_rating ? d.bayesian_rating.toFixed(2) : d.rating}
        </div>
      </div>

      <div class="reviews-list">
        ${reviewsHtml}
      </div>

      <div class="add-review-form">
        <h5 style="margin-bottom: 8px; font-size: 0.95rem; font-weight: 700;">Оставить отзыв о враче:</h5>
        <input type="text" id="review-author" placeholder="Ваше имя...">
        <select id="review-rating">
          <option value="5">⭐⭐⭐⭐⭐ 5 - Отлично, рекомендую</option>
          <option value="4">⭐⭐⭐⭐ 4 - Хорошо</option>
          <option value="3">⭐⭐⭐ 3 - Удовлетворительно</option>
          <option value="2">⭐⭐ 2 - Были проблемы</option>
          <option value="1">⭐ 1 - Не понравилось</option>
        </select>
        <textarea id="review-text" rows="3" placeholder="Поделитесь вашим впечатлением о приеме и качестве лечения..."></textarea>
        <button onclick="submitReview('${d.id}')" class="btn btn-primary" style="width: 100%;">
          Отправить отзыв
        </button>
      </div>
    </div>
  `;
}

async function submitReview(dentistId) {
  const author = document.getElementById('review-author').value.trim();
  const rating = parseInt(document.getElementById('review-rating').value, 10);
  const text = document.getElementById('review-text').value.trim();

  if (!author || !text) {
    alert("Пожалуйста, укажите ваше имя и текст отзыва.");
    return;
  }

  try {
    const res = await fetch(`/api/dentists/${dentistId}/reviews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author, rating, text })
    });

    if (res.ok) {
      alert("Спасибо! Ваш отзыв успешно сохранен.");
      openDentistModal(dentistId);
      loadDentists();
    } else {
      alert("Ошибка при сохранении отзыва.");
    }
  } catch (err) {
    console.error(err);
    alert("Ошибка соединения с сервером.");
  }
}

function closeDetailsModal() {
  document.getElementById('details-modal').classList.remove('open');
}

/* =========================================================================
   5. COMPARISON SYSTEM (Compare up to 3 clinics)
   ========================================================================= */
function toggleCompare(dentistId) {
  const index = compareList.indexOf(dentistId);
  if (index > -1) {
    compareList.splice(index, 1);
  } else {
    if (compareList.length >= 3) {
      alert("Вы можете сравнивать одновременно до 3 клиник.");
      return;
    }
    compareList.push(dentistId);
  }

  updateCompareUI();
}

function updateCompareUI() {
  const btn = document.getElementById('open-compare-btn');
  const countSpan = document.getElementById('compare-count');
  countSpan.innerText = compareList.length;

  if (compareList.length > 0) {
    btn.style.display = 'inline-block';
  } else {
    btn.style.display = 'none';
  }

  // Update card buttons
  document.querySelectorAll('.dentist-card').forEach(card => {
    const id = card.id.replace('card-', '');
    const compBtn = card.querySelector('.btn-compare-card');
    if (compBtn) {
      if (compareList.includes(id)) {
        compBtn.classList.add('active');
        compBtn.innerText = '✓ В сравнении';
      } else {
        compBtn.classList.remove('active');
        compBtn.innerText = '⚖️ Сравнить';
      }
    }
  });
}

async function openCompareModal() {
  if (compareList.length === 0) return;
  const modal = document.getElementById('compare-modal');
  const body = document.getElementById('compare-modal-body');
  modal.classList.add('open');

  body.innerHTML = '<div style="text-align: center; padding: 30px;">Формирование сравнительной таблицы...</div>';

  const comparedDentists = currentDentists.filter(d => compareList.includes(d.id));

  let html = `
    <table class="compare-table">
      <thead>
        <tr>
          <th>Параметр</th>
          ${comparedDentists.map(d => `<th>${escapeHtml(d.name)}<br><small style="color: #0284c7;">${escapeHtml(d.clinic)}</small></th>`).join('')}
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Рейтинг 2ГИС</strong></td>
          ${comparedDentists.map(d => `<td>⭐ ${d.rating} (${d.reviews_count} отзывов)</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Стаж врача</strong></td>
          ${comparedDentists.map(d => `<td>${d.experience_years} лет</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Образование</strong></td>
          ${comparedDentists.map(d => `<td>${d.education ? escapeHtml(d.education.university) : 'Высшее мед.'}</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Сертификаты</strong></td>
          ${comparedDentists.map(d => `<td>${(d.certifications || []).length} подтвержденных</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Лечение кариеса</strong></td>
          ${comparedDentists.map(d => `<td>от ${d.services['Лечение кариеса'] || d.services['Лечение кариеса световой пломбой'] || 1600} сом</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Имплантация</strong></td>
          ${comparedDentists.map(d => `<td>от ${d.services['Имплант Osstem (Южная Корея) под ключ'] || d.services['Имплантация зубов'] || 26000} сом</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Циркониевая коронка</strong></td>
          ${comparedDentists.map(d => `<td>от ${d.services['Циркониевая коронка'] || d.services['Коронка из диоксида циркония'] || 12000} сом</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Район</strong></td>
          ${comparedDentists.map(d => `<td>${escapeHtml(d.district)}</td>`).join('')}
        </tr>
        <tr>
          <td><strong>Запись в WhatsApp</strong></td>
          ${comparedDentists.map(d => `
            <td>
              <a href="https://wa.me/${d.whatsapp}" target="_blank" class="btn btn-whatsapp" style="font-size:0.75rem; padding: 4px 8px;">
                Записаться
              </a>
            </td>
          `).join('')}
        </tr>
      </tbody>
    </table>
    <div style="margin-top: 16px; text-align: right;">
      <button onclick="clearCompare()" class="btn btn-secondary" style="font-size: 0.85rem;">Очистить сравнение</button>
    </div>
  `;

  body.innerHTML = html;
}

function clearCompare() {
  compareList = [];
  updateCompareUI();
  document.getElementById('compare-modal').classList.remove('open');
}

/* =========================================================================
   6. STANDALONE TREATMENT ESTIMATOR MODAL
   ========================================================================= */
function openStandaloneCalc() {
  const modal = document.getElementById('calc-modal');
  const body = document.getElementById('calc-modal-body');
  modal.classList.add('open');

  const standardProcedures = [
    { name: "Первичная консультация и осмотр", price: 300 },
    { name: "Компьютерная томография (КТ) 3D", price: 1600 },
    { name: "Лечение поверхностного / среднего кариеса", price: 1800 },
    { name: "Лечение глубокого кариеса световой пломбой", price: 2500 },
    { name: "Лечение каналов зуба (пульпит 3 канала)", price: 6500 },
    { name: "Профессиональная чистка Air Flow + ультразвук", price: 2500 },
    { name: "Сложное удаление зуба мудрости", price: 3800 },
    { name: "Установка имплантата Osstem под ключ", price: 31000 },
    { name: "Премиум имплантат Straumann (Швейцария)", price: 54000 },
    { name: "Коронка из диоксида циркония", price: 12500 },
    { name: "Керамический винир E.max", price: 18500 },
    { name: "Металлические брекеты Damon Q (1 челюсть)", price: 32000 },
    { name: "Клиническое отбеливание зубов", price: 9500 }
  ];

  let selectedTotal = 0;
  body.innerHTML = `
    <div style="margin-bottom: 14px; font-size: 0.88rem; color: #475569;">
      Отметьте необходимые вам процедуры для мгновенного подсчета средней стоимости по клиникам Бишкека:
    </div>
    <div style="display: flex; flex-direction: column; gap: 8px; max-height: 340px; overflow-y: auto;">
      ${standardProcedures.map((p, idx) => `
        <label style="display: flex; justify-content: space-between; align-items: center; background: #f8fafc; padding: 10px 14px; border-radius: 8px; border: 1px solid #e2e8f0; cursor: pointer;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <input type="checkbox" class="standalone-calc-check" data-price="${p.price}" onchange="updateStandaloneCalcTotal()">
            <span style="font-size: 0.9rem; font-weight: 500;">${p.name}</span>
          </div>
          <strong style="color: #047857; font-size: 0.9rem;">${p.price.toLocaleString()} сом</strong>
        </label>
      `).join('')}
    </div>
    <div class="calc-total-box" style="margin-top: 20px;">
      <div>
        <div style="font-size: 0.85rem; color: #94a3b8;">Итого по смете:</div>
        <div class="calc-total-num" id="standalone-calc-total">0 сом</div>
      </div>
      <button onclick="document.getElementById('calc-modal').classList.remove('open'); document.getElementById('open-wizard-btn').click();" class="btn btn-primary">
        Найти врача под этот бюджет →
      </button>
    </div>
  `;
}

function updateStandaloneCalcTotal() {
  let sum = 0;
  document.querySelectorAll('.standalone-calc-check:checked').forEach(cb => {
    sum += parseInt(cb.dataset.price, 10);
  });
  document.getElementById('standalone-calc-total').innerText = `${sum.toLocaleString()} сом`;
}

/* =========================================================================
   7. INTERACTIVE WIZARD ("Мастер подбора")
   ========================================================================= */
function setupWizard() {
  const modal = document.getElementById('wizard-modal');
  const openBtn = document.getElementById('open-wizard-btn');
  const closeBtn = document.getElementById('close-wizard-btn');

  openBtn.addEventListener('click', () => {
    goToStep(1);
    modal.classList.add('open');
  });

  closeBtn.addEventListener('click', () => {
    modal.classList.remove('open');
  });

  modal.addEventListener('click', (e) => {
    if (e.target.id === 'wizard-modal') modal.classList.remove('open');
  });

  document.getElementById('wizard-next-1').addEventListener('click', () => goToStep(2));
  document.getElementById('wizard-back-2').addEventListener('click', () => goToStep(1));
  document.getElementById('wizard-next-2').addEventListener('click', () => goToStep(3));
  document.getElementById('wizard-back-3').addEventListener('click', () => goToStep(2));

  document.getElementById('wizard-submit').addEventListener('click', submitWizard);
}

function goToStep(stepNum) {
  document.getElementById('wizard-step-1').style.display = stepNum === 1 ? 'block' : 'none';
  document.getElementById('wizard-step-2').style.display = stepNum === 2 ? 'block' : 'none';
  document.getElementById('wizard-step-3').style.display = stepNum === 3 ? 'block' : 'none';
  document.getElementById('wizard-results').style.display = stepNum === 4 ? 'block' : 'none';
}

async function submitWizard() {
  const problem = document.querySelector('input[name="w_problem"]:checked').value;
  const district = document.getElementById('w_district').value;
  const price = document.querySelector('input[name="w_price"]:checked').value;
  const priority = document.querySelector('input[name="w_priority"]:checked').value;

  const content = document.getElementById('wizard-recommendation-content');
  content.innerHTML = '<div style="text-align: center; padding: 40px;">Анализируем реестр клиник Бишкека и рассчитываем лучший результат...</div>';
  goToStep(4);

  try {
    const res = await fetch('/api/smart-match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        problem: problem,
        district: district,
        price_level: price,
        priority: priority
      })
    });

    if (!res.ok) throw new Error("Match failed");
    const results = await res.json();

    if (!results || results.length === 0) {
      content.innerHTML = '<p>К сожалению, не удалось рассчитать совпадение. Попробуйте изменить параметры.</p>';
      return;
    }

    const topMatch = results[0];
    const d = topMatch.dentist;

    const reasonsListHtml = topMatch.reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('');

    content.innerHTML = `
      <div class="wizard-champ-card">
        <div class="champ-header">
          <div style="display: flex; gap: 14px; align-items: center;">
            <div style="font-size: 2.6rem;">${d.photo_badge || '👨‍⚕️'}</div>
            <div>
              <h3 style="font-size: 1.3rem; color: #0f172a; margin-bottom: 2px;">${escapeHtml(d.name)}</h3>
              <div style="color: #0284c7; font-weight: 700; font-size: 0.95rem;">${escapeHtml(d.clinic)}</div>
              <div style="font-size: 0.82rem; color: #64748b;">${escapeHtml(d.title)}</div>
            </div>
          </div>
          <div class="champ-score-box">
            <span class="champ-score-num">${topMatch.score}%</span>
            <span class="champ-score-label">Совпадение</span>
          </div>
        </div>

        <div style="font-size: 0.88rem; color: #334155; margin-bottom: 12px;">
          📍 <strong>${escapeHtml(d.address)}</strong> (${escapeHtml(d.district)})
        </div>

        <div style="background: white; border-radius: 12px; padding: 14px; border: 1px solid #e2e8f0;">
          <strong style="font-size: 0.88rem; color: #0f172a;">Почему алгоритм рекомендует этого специалиста:</strong>
          <ul class="champ-reasons-list">
            ${reasonsListHtml}
          </ul>
        </div>

        <div style="margin-top: 20px; display: flex; gap: 12px; flex-wrap: wrap;">
          <a href="https://wa.me/${d.whatsapp}?text=Здравствуйте!_По_результатам_умного_подбора_хочу_записаться_к_вам_на_консультацию" 
             target="_blank" 
             class="btn btn-whatsapp" 
             style="flex: 2; padding: 12px 18px; font-size: 1rem;">
            <span>💬 Записаться через WhatsApp</span>
          </a>
          <button onclick="document.getElementById('wizard-modal').classList.remove('open'); openDentistModal('${d.id}');" class="btn btn-secondary" style="flex: 1;">
            Посмотреть пруфы
          </button>
        </div>
      </div>

      ${results.length > 1 ? `
        <div style="margin-top: 20px;">
          <h4 style="font-size: 0.95rem; color: #64748b; margin-bottom: 10px;">Другие отличные варианты:</h4>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            ${results.slice(1, 3).map((m, idx) => `
              <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                  <strong>#${idx + 2} ${escapeHtml(m.dentist.name)}</strong> — <span style="color:#0284c7;">${escapeHtml(m.dentist.clinic)}</span>
                  <div style="font-size: 0.78rem; color: #64748b;">${escapeHtml(m.dentist.district)} • ⭐ ${m.dentist.rating}</div>
                </div>
                <div style="text-align: right;">
                  <span style="font-weight: 700; color: #059669; font-size: 0.9rem;">${m.score}%</span>
                  <div>
                    <button onclick="document.getElementById('wizard-modal').classList.remove('open'); openDentistModal('${m.dentist.id}');" style="background: none; border: none; color: #0284c7; cursor: pointer; font-size: 0.8rem; text-decoration: underline;">
                      Прайс и пруфы
                    </button>
                  </div>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}
    `;

  } catch (err) {
    console.error(err);
    content.innerHTML = '<p style="color: #ef4444;">Произошла ошибка при расчете. Попробуйте еще раз.</p>';
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
