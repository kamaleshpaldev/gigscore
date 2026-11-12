/**
 * GigScore Frontend Controller (Vanilla JS)
 * Prototype - synthetic data only. Not for real lending decisions.
 */

const STATE = {
  selectedDemoWorker: 'DEMO_W_STRONG',
  demoWorkers: [],
  demoLenders: [
    {
      lender_id: 'LENDER_SAMUNNATI_NBFC',
      name: 'Samunnati Micro-Mobility NBFC (Demo)',
      demo_api_key: 'gsk_demo_samunnati_2026_secret_key',
    },
    {
      lender_id: 'LENDER_PRAGATI_FINTECH',
      name: 'Pragati EV Fleet Finance (Demo)',
      demo_api_key: 'gsk_demo_pragati_2026_secret_key',
    },
  ],
  activeConsentByWorker: {
    DEMO_W_STRONG: 'consent_demo_demo_w_strong',
    DEMO_W_AVERAGE: 'consent_demo_demo_w_average',
    DEMO_W_VOLATILE: 'consent_demo_demo_w_volatile',
    DEMO_W_NEW: 'consent_demo_demo_w_new',
    DEMO_W_SUSPICIOUS: 'consent_demo_demo_w_suspicious',
  },
  isGrantingConsent: false,
  isApprovingConsent: false,
  isRevokingConsent: false,
  isScoringWorker: false,
  currentWorkerConsentStatus: 'NONE',
  currentWorkerActiveHandle: null,
};

const TRANSLATIONS = {
  en: {
    heroTitle:
      'Turning Multi-Platform Gig Work Into <span class="text-gold-400">Portable Credit Trust</span>',
    heroSubtitle:
      'GigScore computes a transparent 300–900 alternative credit score from consent-verified Swiggy, Zomato, Uber, Ola, and Urban Company payouts—complete with fraud authenticity screening and plain-English SHAP explanations.',
  },
  hi: {
    heroTitle:
      'गिग वर्कर्स की मेहनत और कमाई अब बनेगी <span class="text-gold-400">पोर्टेबल क्रेडिट स्कोर (UI प्रोटोटाइप)</span>',
    heroSubtitle:
      'GigScore स्विगी, ज़ोमैटो, उबर, ओला और अर्बन कंपनी की सत्यापित आय से 300–900 का पारदर्शी क्रेडिट स्कोर बनाता है (सिंथेटिक डेटा प्रोटोटाइप)।',
  },
  pa: {
    heroTitle:
      'ਗਿੱਗ ਵਰਕਰਾਂ ਦੀ ਕਮਾਈ ਹੁਣ ਬਣੇਗੀ <span class="text-gold-400">ਪੋਰਟੇਬਲ ਕ੍ਰੈਡਿਟ ਭਰੋਸਾ (UI ਪ੍ਰੋਟੋਟਾਈਪ)</span>',
    heroSubtitle:
      'GigScore ਸਵਿੱਗੀ, ਜ਼ੋਮੈਟੋ, ਉਬਰ ਅਤੇ ਓਲਾ ਦੀ ਪ੍ਰਮਾਣਿਤ ਕਮਾਈ ਤੋਂ 300–900 ਦਾ ਪਾਰਦਰਸ਼ੀ ਕ੍ਰੈਡਿਟ ਸਕੋਰ ਤਿਆਰ ਕਰਦਾ ਹੈ (ਸਿੰਥੈਟਿਕ ਡੇਟਾ ਪ੍ਰੋਟੋਟਾਈਪ)।',
  },
};

window.switchLanguage = function (lang) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  const titleEl = document.getElementById('hero-title');
  const subEl = document.getElementById('hero-subtitle');
  if (titleEl) titleEl.innerHTML = t.heroTitle;
  if (subEl) subEl.textContent = t.heroSubtitle;
};

window.showView = function (viewName) {
  const views = ['landing', 'demo', 'worker', 'lender', 'transparency'];
  views.forEach((v) => {
    const sec = document.getElementById(`view-${v}`);
    if (sec) {
      if (v === viewName) sec.classList.remove('hidden');
      else sec.classList.add('hidden');
    }
  });

  document.querySelectorAll('.nav-btn').forEach((btn) => {
    if (btn.getAttribute('data-nav') === viewName) {
      btn.classList.add('nav-active');
    } else {
      btn.classList.remove('nav-active');
    }
  });

  if (viewName === 'demo') window.loadDemoCatalog();
  if (viewName === 'worker') {
    const sel = document.getElementById('worker-select');
    window.loadWorkerDashboard(sel ? sel.value : 'DEMO_W_STRONG');
  }
  if (viewName === 'lender') window.loadLenderUsage();
  if (viewName === 'transparency') window.loadTransparencyData();
};

function appendDemoLog(stepTitle, status, dataObj) {
  const container = document.getElementById('demo-log-entries');
  if (!container) return;
  const color =
    status >= 200 && status < 300
      ? 'text-emerald-400'
      : status === 403 || status === 401
      ? 'text-amber-300'
      : 'text-rose-400';
  const entry = document.createElement('div');
  entry.className = 'p-2.5 rounded bg-forest-900/90 border border-gold-500/20';
  entry.innerHTML = `
    <div class="flex items-center justify-between">
      <span class="font-bold text-gold-400">${stepTitle}</span>
      <span class="${color} font-bold">HTTP ${status}</span>
    </div>
    <pre class="mt-1 text-[11px] text-ivory-100 whitespace-pre-wrap overflow-x-auto">${JSON.stringify(
      dataObj,
      null,
      2
    )}</pre>
  `;
  container.prepend(entry);
}

function renderDemoVisualOutcome(title, scoreData) {
  const card = document.getElementById('demo-visual-outcome');
  if (!card) return;

  if (scoreData.authenticity_status === 'NEEDS_REVIEW' || scoreData.needs_review) {
    const flagsHtml = (
      (scoreData.authenticity && scoreData.authenticity.flags) ||
      []
    )
      .map(
        (f) =>
          `<li class="p-1.5 rounded bg-amber-100 text-amber-950 border border-amber-300">${f}</li>`
      )
      .join('');
    card.innerHTML = `
      <div class="p-4 rounded-xl bg-amber-50 border-2 border-amber-400 space-y-2">
        <div class="flex items-center justify-between">
          <span class="px-2.5 py-0.5 rounded bg-amber-300 text-amber-950 font-extrabold text-xs">⚠️ AUTHENTICITY STATUS: NEEDS_REVIEW</span>
          <span class="font-mono text-xs font-bold text-emerald-900">Fee Billed: ₹0.00 (No Charge)</span>
        </div>
        <h4 class="font-extrabold text-forest-950 text-base">${title} — No Credit Score Generated (gig_score: null)</h4>
        <p class="text-xs text-slate-700">Request ID: <code>${scoreData.request_id}</code> • Model: <code>${scoreData.model_version}</code></p>
        <ul class="space-y-1 text-xs font-medium">${flagsHtml}</ul>
      </div>
    `;
    return;
  }

  if (scoreData.gig_score) {
    const factorsHtml = (scoreData.top_factors || [])
      .slice(0, 4)
      .map(
        (f) => `
        <div class="p-2 rounded border ${
          f.direction === 'POSITIVE'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-950'
            : 'bg-rose-50 border-rose-200 text-rose-950'
        } text-xs">
          <strong>${f.direction === 'POSITIVE' ? '+' : '−'} ${f.reason_code}:</strong> ${f.plain_english}
        </div>`
      )
      .join('');

    card.innerHTML = `
      <div class="p-4 rounded-xl bg-ivory-50 border-2 border-gold-500/60 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <span class="text-xs font-bold uppercase text-forest-700">${title}</span>
            <h4 class="text-2xl font-black text-forest-950">GigScore: ${scoreData.gig_score} / 900 <span class="text-sm font-bold text-emerald-800">(${scoreData.score_band})</span></h4>
          </div>
          <div class="text-right text-xs">
            <span class="px-2.5 py-1 rounded bg-emerald-100 text-emerald-900 font-bold">✓ ${scoreData.authenticity_status}</span>
            <div class="mt-1 font-mono font-bold text-forest-900">Fee Charged: ₹${Number(scoreData.fee_charged_inr).toFixed(2)}</div>
          </div>
        </div>
        <div class="text-xs text-slate-600 font-mono">
          Request ID: ${scoreData.request_id} • Engine: ${scoreData.scoring_engine} (${scoreData.model_version})
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">${factorsHtml}</div>
      </div>
    `;
  }
}

window.loadDemoCatalog = async function () {
  try {
    const res = await fetch('/api/demo/catalog');
    const data = await res.json();
    STATE.demoWorkers = data.demo_workers || [];
    if (data.demo_lenders && data.demo_lenders.length > 0) {
      STATE.demoLenders = data.demo_lenders;
    }
    const badge = document.getElementById('nav-model-badge');
    if (badge && data.active_model_version) {
      badge.textContent = `Model: ${data.active_model_version}`;
    }
    renderDemoWorkerCards();
  } catch (err) {
    console.error('Failed to load demo catalog:', err);
  }
};

function renderDemoWorkerCards() {
  const container = document.getElementById('demo-worker-cards');
  if (!container) return;
  container.innerHTML = STATE.demoWorkers
    .map((w) => {
      const active = w.worker_uid === STATE.selectedDemoWorker;
      return `
      <button type="button" onclick="window.selectDemoWorker('${w.worker_uid}')"
        class="w-full text-left p-3 rounded-xl border transition ${
          active
            ? 'bg-forest-900 text-ivory-50 border-gold-500 shadow'
            : 'bg-ivory-50 hover:bg-ivory-100 text-slate-900 border-slate-200'
        }">
        <div class="flex items-center justify-between">
          <span class="font-bold text-xs sm:text-sm">${w.profile_label}: ${w.name}</span>
          <span class="font-mono text-[11px] ${active ? 'text-gold-400' : 'text-forest-800'}">${w.worker_uid}</span>
        </div>
        <div class="text-[11px] mt-1 ${active ? 'text-ivory-200' : 'text-slate-600'}">
          ${w.summary_badge}
        </div>
      </button>
    `;
    })
    .join('');
}

window.selectDemoWorker = function (workerUid) {
  STATE.selectedDemoWorker = workerUid;
  const badge = document.getElementById('demo-selected-worker-badge');
  if (badge) badge.textContent = `Selected: ${workerUid}`;
  const input = document.getElementById('demo-active-consent-input');
  if (input) {
    input.value =
      STATE.activeConsentByWorker[workerUid] ||
      `consent_demo_${workerUid.toLowerCase()}`;
  }
  renderDemoWorkerCards();
};

window.demoStepCreateConsent = async function () {
  const workerUid = STATE.selectedDemoWorker;
  const lenderId = STATE.demoLenders[0].lender_id;
  const res = await fetch('/consent/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      worker_uid: workerUid,
      lender_id: lenderId,
      purpose: 'CREDIT_SCORING',
      requested_platforms: ['Swiggy', 'Zomato', 'Uber'],
      expiry_hours: 24,
    }),
  });
  const data = await res.json();
  if (res.ok && data.consent_handle) {
    STATE.activeConsentByWorker[workerUid] = data.consent_handle;
    document.getElementById('demo-active-consent-input').value =
      data.consent_handle;
  }
  appendDemoLog(`Step 1: POST /consent/request (${workerUid})`, res.status, data);
  return data;
};

window.demoStepApproveConsent = async function () {
  const workerUid = STATE.selectedDemoWorker;
  const handle = document.getElementById('demo-active-consent-input').value.trim();
  const res = await fetch('/consent/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      worker_uid: workerUid,
      consent_handle: handle,
    }),
  });
  const data = await res.json();
  appendDemoLog(`Step 2: POST /consent/approve (${handle})`, res.status, data);
  return data;
};

window.demoStepFetchAA = async function () {
  const handle = document.getElementById('demo-active-consent-input').value.trim();
  const res = await fetch(`/mock-aa/fetch/${encodeURIComponent(handle)}`);
  const data = await res.json();
  appendDemoLog(`Step 3: GET /mock-aa/fetch/${handle}`, res.status, {
    consent_handle: data.consent_handle,
    worker_uid: data.worker_uid,
    platforms_connected: data.platforms_connected,
    tenure_months: data.tenure_months,
    aggregated_summary: data.aggregated_summary,
    raw_data_persisted: data.raw_data_persisted,
    sample_months_count: (data.monthly_earnings || []).length,
    disclaimer: data.disclaimer,
  });
  return data;
};

window.demoStepScore = async function (forceFallback = false) {
  const workerUid = STATE.selectedDemoWorker;
  const handle = document.getElementById('demo-active-consent-input').value.trim();
  const apiKey = STATE.demoLenders[0].demo_api_key;
  const res = await fetch(`/score?force_fallback=${forceFallback}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
    body: JSON.stringify({
      worker_uid: workerUid,
      consent_handle: handle,
    }),
  });
  const data = await res.json();
  if (res.ok && data.request_id) {
    document.getElementById('demo-last-request-id').value = data.request_id;
    renderDemoVisualOutcome(`Score Result for ${workerUid}`, data);
  }
  appendDemoLog(`Step 4: POST /score (${workerUid})`, res.status, data);
  return { status: res.status, data };
};

window.demoStepRevokeConsent = async function () {
  const workerUid = STATE.selectedDemoWorker;
  const handle = document.getElementById('demo-active-consent-input').value.trim();
  const res = await fetch('/consent/revoke', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      worker_uid: workerUid,
      consent_handle: handle,
      reason: 'Worker clicked One-Tap Revocation in Demo',
    }),
  });
  const data = await res.json();
  appendDemoLog(`Step 5: POST /consent/revoke (${handle})`, res.status, data);
  return data;
};

window.demoStepScoreAfterRevoke = async function () {
  const workerUid = STATE.selectedDemoWorker;
  const handle = document.getElementById('demo-active-consent-input').value.trim();
  const apiKey = STATE.demoLenders[0].demo_api_key;
  const res = await fetch('/score', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
    body: JSON.stringify({
      worker_uid: workerUid,
      consent_handle: handle,
    }),
  });
  const data = await res.json();
  appendDemoLog(
    `Step 6: Verify Rejected POST /score After Revocation`,
    res.status,
    data
  );
  return { status: res.status, data };
};

window.runAutomatedEndToEndDemo = async function (workerUid) {
  window.selectDemoWorker(workerUid);
  const cReq = await window.demoStepCreateConsent();
  if (!cReq || !cReq.consent_handle) return;
  await window.demoStepApproveConsent();
  await window.demoStepFetchAA();
  const scoreRes = await window.demoStepScore(false);

  if (scoreRes.data && scoreRes.data.request_id) {
    const auditRes = await fetch(
      `/audit/${encodeURIComponent(scoreRes.data.request_id)}`,
      {
        headers: { 'X-API-Key': STATE.demoLenders[0].demo_api_key },
      }
    );
    const auditData = await auditRes.json();
    appendDemoLog(
      `Audit Verification: GET /audit/${scoreRes.data.request_id}`,
      auditRes.status,
      auditData
    );
  }

  const usageRes = await fetch(
    `/lenders/${encodeURIComponent(STATE.demoLenders[0].lender_id)}/usage`,
    {
      headers: { 'X-API-Key': STATE.demoLenders[0].demo_api_key },
    }
  );
  const usageData = await usageRes.json();
  appendDemoLog(
    `Billing Verification: GET /lenders/${STATE.demoLenders[0].lender_id}/usage`,
    usageRes.status,
    {
      lender_id: usageData.lender_id,
      total_checks: usageData.total_checks,
      total_billed_inr: usageData.total_billed_inr,
      latest_record: (usageData.recent_billing_records || [])[0] || null,
    }
  );

  await window.demoStepRevokeConsent();
  await window.demoStepScoreAfterRevoke();
};

/* ============================================================================
   WORKER DASHBOARD LOGIC
   Strictly read-only on load/switch/refresh: NEVER auto-creates consents.
============================================================================ */
window.loadWorkerDashboard = async function (workerUid) {
  try {
    const res = await fetch(`/api/workers/${encodeURIComponent(workerUid)}/overview`);
    const data = await res.json();
    const w = data.worker;
    document.getElementById('worker-dash-name').textContent = `${w.name} (${w.worker_uid})`;
    document.getElementById('worker-dash-meta').textContent = `e-Shram: ${
      w.e_shram_id
    } • ${w.primary_city} • Tenure: ${w.tenure_months}m • Platforms: ${(
      w.platforms || []
    ).join(', ')}`;

    const consentStatus = data.consent_status || 'NONE';
    const activeHandle = data.active_consent_handle || null;
    STATE.currentWorkerConsentStatus = consentStatus;
    STATE.currentWorkerActiveHandle = activeHandle;
    if (activeHandle) {
      STATE.activeConsentByWorker[w.worker_uid] = activeHandle;
    }

    // Update "+ Grant New Consent" button state so duplicate active consents cannot be spammed
    const grantBtn = document.getElementById('btn-grant-consent');
    if (grantBtn && !STATE.isGrantingConsent) {
      if (consentStatus === 'APPROVED') {
        grantBtn.disabled = true;
        grantBtn.textContent = '✓ Consent Active';
      } else if (consentStatus === 'PENDING') {
        grantBtn.disabled = true;
        grantBtn.textContent = '⏳ Consent Pending';
      } else {
        grantBtn.disabled = false;
        grantBtn.textContent = '+ Grant New Consent';
      }
    }

    renderWorkerConsents(w.worker_uid, data.consents || []);
    renderWorkerScorePanel(data.latest_score, consentStatus, activeHandle);
  } catch (err) {
    console.error('Error loading worker dashboard:', err);
  }
};

function renderWorkerScorePanel(scoreObj, consentStatus = 'NONE', activeHandle = null) {
  const gaugeScoreEl = document.getElementById('worker-gauge-score');
  const arcEl = document.getElementById('worker-gauge-arc');
  const bandEl = document.getElementById('worker-score-band');
  const tierEl = document.getElementById('worker-risk-tier');
  const engineEl = document.getElementById('worker-score-engine-badge');
  const factorsEl = document.getElementById('worker-factors-list');
  const tipsEl = document.getElementById('worker-tips-list');

  // 1. If consent is NOT APPROVED (e.g. REVOKED, PENDING, EXPIRED, NONE), NEVER display a valid or stale score.
  if (consentStatus !== 'APPROVED') {
    if (consentStatus === 'REVOKED') {
      gaugeScoreEl.textContent = 'REVOKED';
      arcEl.setAttribute('stroke-dashoffset', '314');
      arcEl.setAttribute('stroke', '#e11d48');
      bandEl.textContent = 'Consent Revoked — Scoring Disabled';
      tierEl.textContent = 'CONSENT_REVOKED';
      tierEl.className =
        'inline-block mt-1 px-2.5 py-0.5 rounded text-xs font-bold bg-rose-100 text-rose-900';
      factorsEl.innerHTML = `<div class="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-950 font-medium">🔒 Consent revoked. Scoring is immediately blocked and no previous score is valid. Click <strong>"+ Grant New Consent"</strong> and approve it to re-enable scoring.</div>`;
      tipsEl.innerHTML = `<li>You are in full control of your data. Granting and approving a new consent is required before any lender or dashboard can compute a score.</li>`;
    } else if (consentStatus === 'PENDING') {
      gaugeScoreEl.textContent = 'PENDING';
      arcEl.setAttribute('stroke-dashoffset', '314');
      arcEl.setAttribute('stroke', '#d97706');
      bandEl.textContent = 'Consent Pending Approval';
      tierEl.textContent = 'CONSENT_PENDING';
      tierEl.className =
        'inline-block mt-1 px-2.5 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-900';
      factorsEl.innerHTML = `<div class="p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-950 font-medium">⏳ Consent request (<code>${activeHandle || ''}</code>) is pending your approval. Click <strong>"✓ Approve Consent"</strong> on the right panel to authorize scoring.</div>`;
      tipsEl.innerHTML = `<li>Pending consents cannot be used for credit scoring until explicitly approved by the worker.</li>`;
    } else {
      gaugeScoreEl.textContent = '--';
      arcEl.setAttribute('stroke-dashoffset', '314');
      arcEl.setAttribute('stroke', '#64748b');
      bandEl.textContent = 'Consent Required';
      tierEl.textContent = 'CONSENT_REQUIRED';
      tierEl.className =
        'inline-block mt-1 px-2.5 py-0.5 rounded text-xs font-bold bg-slate-200 text-slate-800';
      factorsEl.innerHTML = `<div class="p-3 rounded-lg bg-slate-100 border border-slate-300 text-slate-800 font-medium">🔒 Active consent is required before generating or displaying a GigScore. Click <strong>"+ Grant New Consent"</strong> on the right panel.</div>`;
      tipsEl.innerHTML = `<li>Grant and approve Account Aggregator consent to view your score and SHAP explainability factors.</li>`;
    }
    return;
  }

  // 2. Consent is APPROVED, but no score has been calculated yet for this active consent
  if (!scoreObj) {
    gaugeScoreEl.textContent = 'READY';
    arcEl.setAttribute('stroke-dashoffset', '314');
    arcEl.setAttribute('stroke', '#0d9488');
    bandEl.textContent = 'Consent Approved — Ready to Score';
    tierEl.textContent = 'CONSENT_APPROVED';
    tierEl.className =
      'inline-block mt-1 px-2.5 py-0.5 rounded text-xs font-bold bg-emerald-100 text-emerald-900';
    factorsEl.innerHTML = `<div class="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-950 font-medium">✓ Consent <code>${activeHandle || ''}</code> is approved and active. Click <strong>"↻ Refresh My Score"</strong> above to compute your GigScore.</div>`;
    tipsEl.innerHTML = `<li>Click "↻ Refresh My Score" to run the calibrated XGBoost scoring engine on your verified platform earnings.</li>`;
    return;
  }

  if (engineEl) {
    engineEl.textContent = `Model: ${scoreObj.model_version || 'xgboost-calibrated-v1.0'}`;
  }

  // 3. Authenticity flagged NEEDS_REVIEW
  if (scoreObj.authenticity_status === 'NEEDS_REVIEW' || scoreObj.needs_review) {
    gaugeScoreEl.textContent = 'REVIEW';
    arcEl.setAttribute('stroke-dashoffset', '220');
    arcEl.setAttribute('stroke', '#d97706');
    bandEl.textContent = 'Authenticity Verification Required (NEEDS_REVIEW)';
    tierEl.textContent = 'NEEDS_REVIEW — No Score Generated';
    tierEl.className =
      'inline-block mt-1 px-2.5 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-900';

    const flags = scoreObj.authenticity_flags ||
      (scoreObj.authenticity && scoreObj.authenticity.flags) || [];
    factorsEl.innerHTML = flags
      .map(
        (fl) =>
          `<div class="p-3 rounded-lg bg-amber-50 border border-amber-300 text-amber-950 font-medium">⚠️ ${fl}</div>`
      )
      .join('');
    tipsEl.innerHTML = `<li>Ensure bank-verified AA statements match your platform payout history without duplicate or manually rounded entries.</li>`;
    return;
  }

  // 4. Reject any audit object that lacks a numeric gig_score or has a REJECTED_ status (never default to 650!)
  const rawTier = String(scoreObj.risk_tier || '');
  if (
    scoreObj.gig_score === null ||
    scoreObj.gig_score === undefined ||
    rawTier.startsWith('REJECTED_')
  ) {
    gaugeScoreEl.textContent = '--';
    arcEl.setAttribute('stroke-dashoffset', '314');
    arcEl.setAttribute('stroke', '#e11d48');
    bandEl.textContent = 'Consent Required / Scoring Rejected';
    tierEl.textContent = rawTier || 'SCORE_UNAVAILABLE';
    tierEl.className =
      'inline-block mt-1 px-2.5 py-0.5 rounded text-xs font-bold bg-rose-100 text-rose-900';
    factorsEl.innerHTML = `<div class="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-950 font-medium">Scoring was rejected (${rawTier}). Ensure you have an active, approved consent.</div>`;
    return;
  }

  const scoreVal = Number(scoreObj.gig_score);
  gaugeScoreEl.textContent = String(scoreVal);
  const pct = Math.max(0, Math.min(1, (scoreVal - 300) / 600));
  const dashOffset = Math.round(314 * (1 - pct));
  arcEl.setAttribute('stroke-dashoffset', String(dashOffset));
  arcEl.setAttribute(
    'stroke',
    scoreVal >= 750 ? '#15803d' : scoreVal >= 650 ? '#0d9488' : '#d97706'
  );

  bandEl.textContent = scoreObj.score_band || '650-749 (Good)';
  tierEl.textContent = scoreObj.risk_tier || 'MODERATE_RISK';
  tierEl.className = `inline-block mt-1 px-2.5 py-0.5 rounded text-xs font-bold ${
    scoreVal >= 650
      ? 'bg-emerald-100 text-emerald-900'
      : 'bg-amber-100 text-amber-900'
  }`;

  const factors = scoreObj.top_factors || [];
  factorsEl.innerHTML = factors
    .map((f) => {
      const pos = f.direction === 'POSITIVE';
      return `
      <div class="p-3 rounded-lg border ${
        pos
          ? 'bg-emerald-50 border-emerald-200 text-emerald-950'
          : 'bg-rose-50 border-rose-200 text-rose-950'
      } flex items-start justify-between gap-2">
        <div>
          <span class="font-bold">${pos ? '▲ Positive Factor:' : '▼ Limiting Factor:'}</span>
          <span class="ml-1">${f.plain_english}</span>
        </div>
        <span class="font-mono text-[11px] px-2 py-0.5 rounded bg-white/80 border border-slate-200">${f.reason_code}</span>
      </div>
    `;
    })
    .join('');

  const tips = scoreObj.improvement_tips || [
    'Maintain consistent active payouts across 2+ gig platforms every month.',
    'Keep customer service ratings at 4.6+ to maximize stability points.',
  ];
  tipsEl.innerHTML = tips.map((t) => `<li>${t}</li>`).join('');
}

function renderWorkerConsents(workerUid, consents) {
  const listEl = document.getElementById('worker-consents-list');
  if (!listEl) return;
  if (!consents.length) {
    listEl.innerHTML = `<div class="text-xs text-slate-500">No consent handles found. Click "+ Grant New Consent".</div>`;
    return;
  }

  listEl.innerHTML = consents
    .map((c) => {
      const isApproved = c.status === 'APPROVED';
      const isPending = c.status === 'PENDING';
      const statusBadge =
        c.status === 'APPROVED'
          ? 'bg-emerald-100 text-emerald-900 border-emerald-300'
          : c.status === 'REVOKED'
          ? 'bg-rose-100 text-rose-900 border-rose-300'
          : c.status === 'PENDING'
          ? 'bg-amber-100 text-amber-900 border-amber-300'
          : 'bg-slate-200 text-slate-700 border-slate-300';
      return `
      <div class="p-3.5 rounded-xl border border-slate-200 bg-ivory-50 space-y-2 text-xs">
        <div class="flex items-center justify-between">
          <span class="font-mono font-bold text-forest-950">${c.consent_handle}</span>
          <span class="px-2 py-0.5 rounded border font-bold text-[11px] ${statusBadge}">${c.status}</span>
        </div>
        <div class="text-slate-600 space-y-0.5">
          <div><strong>Authorized Lender:</strong> ${c.lender_id || 'LENDER_SAMUNNATI_NBFC'}</div>
          <div><strong>Purpose:</strong> ${c.purpose || 'CREDIT_SCORING'} • <strong>AA:</strong> ${c.agg_provider}</div>
          <div><strong>Expires:</strong> ${c.expires_at ? new Date(c.expires_at).toLocaleString() : '24h TTL'}</div>
        </div>
        ${
          isPending
            ? `<div class="flex gap-2 pt-1">
                 <button type="button" onclick="window.workerApproveConsent('${workerUid}', '${c.consent_handle}')"
                   class="flex-1 py-1.5 px-3 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white font-bold text-xs transition">
                   ✓ Approve Consent
                 </button>
                 <button type="button" onclick="window.workerRevokeConsent('${workerUid}', '${c.consent_handle}')"
                   class="py-1.5 px-3 rounded-lg bg-rose-700 hover:bg-rose-600 text-white font-bold text-xs transition">
                   ✕ Revoke
                 </button>
               </div>`
            : isApproved
            ? `<button type="button" onclick="window.workerRevokeConsent('${workerUid}', '${c.consent_handle}')"
                 class="w-full py-1.5 px-3 rounded-lg bg-rose-700 hover:bg-rose-600 text-white font-bold text-xs transition">
                 One-Tap Revoke Consent
               </button>`
            : ''
        }
      </div>
    `;
    })
    .join('');
}

window.workerGrantNewConsent = async function () {
  if (STATE.isGrantingConsent) return;
  if (
    STATE.currentWorkerConsentStatus === 'APPROVED' ||
    STATE.currentWorkerConsentStatus === 'PENDING'
  ) {
    return;
  }

  const workerUid = document.getElementById('worker-select').value;
  const grantBtn = document.getElementById('btn-grant-consent');
  STATE.isGrantingConsent = true;
  if (grantBtn) {
    grantBtn.disabled = true;
    grantBtn.textContent = 'Requesting...';
  }

  try {
    const reqRes = await fetch('/consent/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        worker_uid: workerUid,
        lender_id: 'LENDER_SAMUNNATI_NBFC',
        purpose: 'CREDIT_SCORING',
        requested_platforms: ['Swiggy', 'Zomato', 'Uber'],
        expiry_hours: 48,
      }),
    });
    const reqData = await reqRes.json();
    if (reqRes.ok && reqData.consent_handle) {
      STATE.activeConsentByWorker[workerUid] = reqData.consent_handle;
    }
  } finally {
    STATE.isGrantingConsent = false;
    await window.loadWorkerDashboard(workerUid);
  }
};

window.workerApproveConsent = async function (workerUid, consentHandle) {
  if (STATE.isApprovingConsent) return;
  STATE.isApprovingConsent = true;
  try {
    await fetch('/consent/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        worker_uid: workerUid,
        consent_handle: consentHandle,
      }),
    });
  } finally {
    STATE.isApprovingConsent = false;
    await window.loadWorkerDashboard(workerUid);
  }
};

window.workerRevokeConsent = async function (workerUid, consentHandle) {
  if (STATE.isRevokingConsent) return;
  STATE.isRevokingConsent = true;
  try {
    await fetch('/consent/revoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        worker_uid: workerUid,
        consent_handle: consentHandle,
        reason: 'Revoked by worker from Worker Dashboard',
      }),
    });
  } finally {
    STATE.isRevokingConsent = false;
    await window.loadWorkerDashboard(workerUid);
  }
};

window.workerComputeFreshScore = async function () {
  if (STATE.isScoringWorker) return;
  const workerUid = document.getElementById('worker-select').value;

  // NEVER create or approve consent inside Refresh My Score!
  if (
    STATE.currentWorkerConsentStatus !== 'APPROVED' ||
    !STATE.currentWorkerActiveHandle
  ) {
    renderWorkerScorePanel(
      null,
      STATE.currentWorkerConsentStatus,
      STATE.currentWorkerActiveHandle
    );
    return;
  }

  const refreshBtn = document.getElementById('btn-refresh-score');
  STATE.isScoringWorker = true;
  if (refreshBtn) {
    refreshBtn.disabled = true;
    refreshBtn.textContent = 'Scoring...';
  }

  try {
    await fetch('/score', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': STATE.demoLenders[0].demo_api_key,
      },
      body: JSON.stringify({
        worker_uid: workerUid,
        consent_handle: STATE.currentWorkerActiveHandle,
      }),
    });
  } finally {
    STATE.isScoringWorker = false;
    if (refreshBtn) {
      refreshBtn.disabled = false;
      refreshBtn.textContent = '↻ Refresh My Score';
    }
    await window.loadWorkerDashboard(workerUid);
  }
};

/* ============================================================================
   LENDER PORTAL LOGIC
============================================================================ */
window.switchDemoLenderPreset = function (lenderId) {
  const found = STATE.demoLenders.find((l) => l.lender_id === lenderId);
  if (found) {
    document.getElementById('lender-api-key-input').value = found.demo_api_key;
    window.loadLenderUsage();
  }
};

window.syncLenderConsentFromWorker = function (workerUid) {
  document.getElementById('lender-consent-handle-input').value =
    STATE.activeConsentByWorker[workerUid] ||
    `consent_demo_${workerUid.toLowerCase()}`;
};

window.submitLenderScoreQuery = async function (evt) {
  evt.preventDefault();
  const apiKey = document.getElementById('lender-api-key-input').value.trim();
  const workerUid = document.getElementById('lender-worker-uid-input').value;
  const consentHandle = document
    .getElementById('lender-consent-handle-input')
    .value.trim();
  const forceFallback = document.getElementById('lender-force-fallback').checked;

  const card = document.getElementById('lender-score-result-card');
  const res = await fetch(`/score?force_fallback=${forceFallback}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
    body: JSON.stringify({
      worker_uid: workerUid,
      consent_handle: consentHandle,
    }),
  });
  const data = await res.json();

  if (!res.ok) {
    card.innerHTML = `
      <div class="p-4 rounded-xl bg-rose-50 border-2 border-rose-300 text-rose-950 space-y-1 text-xs">
        <div class="font-extrabold text-sm">❌ Scoring Request Rejected (HTTP ${res.status}) — ₹0.00 Charged</div>
        <div><strong>Error Code:</strong> ${data.error_code || (data.detail && data.detail.error_code) || 'ERROR'}</div>
        <div><strong>Message:</strong> ${data.message || (data.detail && data.detail.message) || JSON.stringify(data)}</div>
      </div>
    `;
    await window.loadLenderUsage();
    return;
  }

  if (data.authenticity_status === 'NEEDS_REVIEW' || data.needs_review) {
    const flagsHtml = ((data.authenticity && data.authenticity.flags) || [])
      .map((f) => `<li>${f}</li>`)
      .join('');
    card.innerHTML = `
      <div class="p-5 rounded-xl bg-amber-50 border-2 border-amber-400 space-y-3">
        <div class="flex items-center justify-between">
          <span class="px-2.5 py-1 rounded bg-amber-300 text-amber-950 font-extrabold text-xs">⚠️ AUTHENTICITY: NEEDS_REVIEW</span>
          <span class="font-mono text-xs font-bold text-emerald-900">Fee Charged: ₹0.00</span>
        </div>
        <h4 class="text-lg font-extrabold text-forest-950">Worker ${data.worker_uid} — Flagged for Manual Underwriting Review</h4>
        <p class="text-xs text-slate-700 font-mono">Request ID: ${data.request_id} • Model: ${data.model_version}</p>
        <ul class="list-disc list-inside text-xs text-amber-950 space-y-1">${flagsHtml}</ul>
      </div>
    `;
  } else {
    const factorsHtml = (data.top_factors || [])
      .map(
        (f) =>
          `<li class="p-2 rounded bg-ivory-50 border border-slate-200"><strong>${
            f.direction === 'POSITIVE' ? '▲' : '▼'
          } ${f.reason_code}:</strong> ${f.plain_english}</li>`
      )
      .join('');
    card.innerHTML = `
      <div class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3">
          <div>
            <span class="text-xs font-bold uppercase text-forest-700">Underwriting Decision Report</span>
            <h4 class="text-3xl font-black text-forest-950">${data.gig_score} <span class="text-sm font-semibold text-emerald-800">${data.score_band} • ${data.risk_tier}</span></h4>
          </div>
          <div class="text-right text-xs">
            <span class="px-2.5 py-1 rounded bg-emerald-100 text-emerald-900 font-bold border border-emerald-300">✓ ${data.authenticity_status}</span>
            <div class="mt-1 font-mono font-bold text-forest-900">Fee Billed: ₹${Number(data.fee_charged_inr).toFixed(2)}</div>
          </div>
        </div>
        <div class="text-xs font-mono text-slate-600">
          Request ID: <button type="button" onclick="window.inspectRequestAudit('${data.request_id}')" class="underline text-forest-800 font-bold">${data.request_id}</button>
          • Engine: ${data.scoring_engine} (${data.model_version})
        </div>
        <ul class="space-y-1.5 text-xs">${factorsHtml}</ul>
      </div>
    `;
  }

  if (data.request_id) {
    document.getElementById('audit-lookup-input').value = data.request_id;
  }
  await window.loadLenderUsage();
};

window.loadLenderUsage = async function () {
  const lenderId = document.getElementById('lender-id-select').value;
  const apiKey = document.getElementById('lender-api-key-input').value.trim();
  const tbody = document.getElementById('lender-billing-rows');

  const res = await fetch(`/lenders/${encodeURIComponent(lenderId)}/usage`, {
    headers: { 'X-API-Key': apiKey },
  });
  const data = await res.json();
  if (!res.ok) {
    tbody.innerHTML = `<tr><td colspan="5" class="py-3 text-rose-700">Authentication failed (${res.status}): ${
      data.message || (data.detail && data.detail.message) || 'Invalid API Key'
    }</td></tr>`;
    return;
  }

  document.getElementById('lender-total-checks').textContent = String(
    data.total_checks || 0
  );
  document.getElementById('lender-total-billed').textContent = Number(
    data.total_billed_inr || 0
  ).toFixed(2);

  const rows = data.recent_billing_records || [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="py-3 text-slate-500">No billed checks yet. Run POST /score to generate a ₹30 billing entry.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .map(
      (r) => `
      <tr class="hover:bg-ivory-50">
        <td class="py-2 pr-2">${r.billing_uid}</td>
        <td class="py-2 px-2">
          <button type="button" onclick="window.inspectRequestAudit('${r.request_id}')" class="text-forest-800 underline font-bold">${r.request_id}</button>
        </td>
        <td class="py-2 px-2">${r.worker_uid}</td>
        <td class="py-2 px-2 font-bold text-emerald-900">₹${Number(r.fee_inr).toFixed(2)}</td>
        <td class="py-2 pl-2"><span class="px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 font-bold">${r.status}</span></td>
      </tr>
    `
    )
    .join('');
};

window.inspectRequestAudit = async function (requestId) {
  document.getElementById('audit-lookup-input').value = requestId;
  await window.lookupAuditById();
};

window.lookupAuditById = async function () {
  const reqId = document.getElementById('audit-lookup-input').value.trim();
  if (!reqId) return;
  const apiKey = document.getElementById('lender-api-key-input').value.trim();
  const out = document.getElementById('audit-lookup-output');
  out.classList.remove('hidden');

  const res = await fetch(`/audit/${encodeURIComponent(reqId)}`, {
    headers: apiKey ? { 'X-API-Key': apiKey } : {},
  });
  const data = await res.json();
  out.textContent = JSON.stringify(data, null, 2);
};

/* ============================================================================
   MODEL TRANSPARENCY PAGE LOGIC
============================================================================ */
window.loadTransparencyData = async function () {
  try {
    const res = await fetch('/api/model/transparency');
    const data = await res.json();
    const m = data.metrics || {};

    document.getElementById('trans-model-version').textContent =
      data.active_model_version || 'xgboost-calibrated-v1.0';
    if (m.roc_auc !== undefined)
      document.getElementById('trans-roc-auc').textContent = Number(m.roc_auc).toFixed(4);
    if (m.ks_statistic !== undefined)
      document.getElementById('trans-ks-stat').textContent = Number(m.ks_statistic).toFixed(4);
    if (m.brier_score !== undefined)
      document.getElementById('trans-brier').textContent = Number(m.brier_score).toFixed(4);
    if (m.precision !== undefined)
      document.getElementById('trans-precision').textContent = Number(m.precision).toFixed(4);
    if (m.recall !== undefined)
      document.getElementById('trans-recall').textContent = Number(m.recall).toFixed(4);

    // Feature importance bars
    const fi = m.feature_importance || {};
    const fiContainer = document.getElementById('trans-feature-bars');
    if (fiContainer) {
      fiContainer.innerHTML = Object.entries(fi)
        .map(([feat, val]) => {
          const pct = Math.min(100, Math.round(Number(val) * 180));
          return `
          <div>
            <div class="flex justify-between font-mono text-xs mb-1">
              <span class="font-bold text-forest-950">${feat}</span>
              <span class="text-slate-600">${(Number(val) * 100).toFixed(1)}%</span>
            </div>
            <div class="w-full h-2.5 bg-slate-200 rounded-full overflow-hidden">
              <div class="h-full bg-forest-800 rounded-full" style="width: ${pct}%"></div>
            </div>
          </div>
        `;
        })
        .join('');
    }

    // Confusion matrix
    const cm = m.confusion_matrix || {};
    const cmEl = document.getElementById('trans-confusion-matrix');
    if (cmEl && cm.tn !== undefined) {
      cmEl.innerHTML = `
        <div class="p-2.5 rounded-lg bg-emerald-50 border border-emerald-200">
          <div class="font-bold text-emerald-900">True Neg (TN)</div>
          <div class="text-lg font-black">${cm.tn}</div>
        </div>
        <div class="p-2.5 rounded-lg bg-amber-50 border border-amber-200">
          <div class="font-bold text-amber-900">False Pos (FP)</div>
          <div class="text-lg font-black">${cm.fp}</div>
        </div>
        <div class="p-2.5 rounded-lg bg-rose-50 border border-rose-200">
          <div class="font-bold text-rose-900">False Neg (FN)</div>
          <div class="text-lg font-black">${cm.fn}</div>
        </div>
        <div class="p-2.5 rounded-lg bg-emerald-100 border border-emerald-300">
          <div class="font-bold text-emerald-950">True Pos (TP)</div>
          <div class="text-lg font-black">${cm.tp}</div>
        </div>
      `;
    }

    // Fairness tables
    const fDimensions =
      (data.fairness_report && data.fairness_report.dimensions) || {};
    const fContainer = document.getElementById('trans-fairness-tables');
    if (fContainer) {
      fContainer.innerHTML = Object.entries(fDimensions)
        .map(([dimKey, dimObj]) => {
          const rowsHtml = (dimObj.groups || [])
            .map(
              (g) => `
            <tr class="border-t border-slate-200">
              <td class="py-1.5 font-semibold">${g.group}</td>
              <td class="py-1.5 text-right">${g.sample_size}</td>
              <td class="py-1.5 text-right">${g.average_score}</td>
              <td class="py-1.5 text-right">${(g.approval_rate_at_650 * 100).toFixed(1)}%</td>
              <td class="py-1.5 text-right font-mono font-bold text-forest-800">${Number(
                g.disparate_impact_ratio
              ).toFixed(2)}</td>
            </tr>
          `
            )
            .join('');
          return `
          <div class="p-4 rounded-xl bg-ivory-50 border border-slate-200 space-y-2 text-xs">
            <div class="flex items-center justify-between">
              <span class="font-extrabold text-forest-950 uppercase">${dimKey}</span>
              <span class="px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 font-bold text-[11px]">
                Min DIR: ${Number(dimObj.min_disparate_impact_ratio).toFixed(2)}
              </span>
            </div>
            <table class="w-full text-[11px]">
              <thead>
                <tr class="text-slate-500">
                  <th class="text-left">Group</th>
                  <th class="text-right">N</th>
                  <th class="text-right">Avg</th>
                  <th class="text-right">Appr%</th>
                  <th class="text-right">DIR</th>
                </tr>
              </thead>
              <tbody>${rowsHtml}</tbody>
            </table>
          </div>
        `;
        })
        .join('');
    }

    const cardPre = document.getElementById('trans-model-card');
    if (cardPre) {
      cardPre.textContent = data.model_card_markdown || '';
    }
  } catch (err) {
    console.error('Failed to load transparency metadata:', err);
  }
};

document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname;
  if (path.startsWith('/demo')) window.showView('demo');
  else if (path.startsWith('/worker')) window.showView('worker');
  else if (path.startsWith('/lender')) window.showView('lender');
  else if (path.startsWith('/transparency')) window.showView('transparency');
  else window.showView('landing');
  window.loadDemoCatalog();
});

