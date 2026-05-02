const metrics = [
  { value: 4, suffix: '', label: 'Event Types', note: 'Volume, bulk, sector, promoter' },
  { value: 5, suffix: '', label: 'Risk Gates', note: 'Liquidity, volatility, regime, confidence, expiry' },
  { value: 2, suffix: 'd', label: 'Signal Validity', note: 'Expires after two trading days' },
  { value: 3, suffix: 'x', label: 'Telegram Retries', note: 'Exponential backoff on failure' },
];

const terminalLines = [
  { left: 'init_db()', right: 'OK' },
  { left: 'bhavcopy -> prices', right: 'INGESTED' },
  { left: 'events normalized', right: 'READY' },
  { left: 'worker -> signals', right: 'SCORED' },
  { left: 'telegram.send()', right: 'DELIVERED' },
];

const pipeline = [
  {
    stage: 'Stage 1',
    title: 'Ingest public market files',
    body: 'Bhavcopy, bulk deal, sector composition, and promoter/shareholding files are collected and parsed into structured records.',
    pills: ['bhavcopy.py', 'bulk_deals.py', 'sector.py', 'promoter.py'],
  },
  {
    stage: 'Stage 2',
    title: 'Validate and normalize',
    body: 'Price quality is checked, duplicate events are removed, and grouped stock-day events are enriched with diversity metadata.',
    pills: ['quality.py', 'dedup.py', 'event_id', 'diversity_factor'],
  },
  {
    stage: 'Stage 3',
    title: 'Queue and route events',
    body: 'Normalized events are pushed into Redis and pulled by the worker for signal creation. The queue also supports dead-letter recovery.',
    pills: ['redis_queue.py', 'dead_letter', 'retry_dead_letters'],
  },
  {
    stage: 'Stage 4',
    title: 'Score a single confidence value',
    body: 'Grouped events are converted into one signal using weighted strength, diversity factor, and average quality score.',
    pills: ['engine.py', 'signal_weights', 'confidence'],
  },
  {
    stage: 'Stage 5',
    title: 'Boost and filter',
    body: 'Rule combinations raise confidence, while the risk firewall rejects low-liquidity, high-volatility, weak, expired, or bearish-regime setups.',
    pills: ['evaluator.py', 'filter.py', 'rules.yaml'],
  },
  {
    stage: 'Stage 6',
    title: 'Alert and evaluate',
    body: 'Qualified signals are sent to Telegram and later measured using 3, 5, and 10 day forward return backtests.',
    pills: ['telegram.py', 'backtest.py', 'alerts table'],
  },
];

const weights = [
  { name: 'BULK_DEAL', value: 0.35, detail: 'Most influential event in the default mix' },
  { name: 'VOLUME_SPIKE', value: 0.30, detail: 'Captures abnormal participation and attention' },
  { name: 'SECTOR_ROTATION', value: 0.20, detail: 'Rewards strong sector leadership' },
  { name: 'PROMOTER_CHANGE', value: 0.15, detail: 'Quarterly ownership shift signal' },
];

const riskChecks = [
  {
    title: 'Liquidity Check',
    body: '20-day average volume must stay above the configured minimum so thin names do not trigger attractive-looking but hard-to-trade alerts.',
  },
  {
    title: 'Volatility Check',
    body: 'Signals are rejected when price behavior becomes too unstable relative to the configured maximum 20-day volatility threshold.',
  },
  {
    title: 'Market Regime Check',
    body: 'The engine uses a NIFTY500 membership-based market proxy to avoid sending aggressive long signals during a bearish backdrop.',
  },
  {
    title: 'Confidence Floor',
    body: 'Even before Telegram thresholding, weak signals are filtered out if the confidence score does not clear the configured minimum.',
  },
  {
    title: 'Expiry Check',
    body: 'Signals are valid only for a short trading window. Expired ideas are blocked automatically at alert time.',
  },
];

const modules = [
  {
    name: 'producers/',
    body: 'Collects bhavcopy, bulk deals, sector constituents, and promoter data, then emits structured market events.',
    tags: ['ingestion', 'NSE files', 'event generation'],
  },
  {
    name: 'normalization/',
    body: 'Deduplicates events, merges duplicate payloads, and adds diversity metadata for multi-confirmation signal scoring.',
    tags: ['dedup', 'merge', 'metadata'],
  },
  {
    name: 'queue/',
    body: 'Moves events through Redis with dead-letter handling and a development-friendly in-memory fallback path.',
    tags: ['Redis', 'retry', 'fallback'],
  },
  {
    name: 'scoring/',
    body: 'Calculates final confidence from weighted event strength, event diversity, and data quality.',
    tags: ['weights', 'confidence', 'drivers'],
  },
  {
    name: 'risk/ + rules/',
    body: 'Adds business logic for market quality: risk rejection plus score boosts when strong event combinations appear together.',
    tags: ['risk gate', 'rule boost', 'thresholds'],
  },
  {
    name: 'alerts/ + validation/',
    body: 'Delivers Telegram alerts and later evaluates whether alerted signals produced forward returns worth trusting.',
    tags: ['Telegram', 'audit log', 'backtest'],
  },
];

function createMetricCard(metric) {
  const article = document.createElement('article');
  article.className = 'metric-card';
  article.innerHTML = `
    <p class="eyebrow">${metric.label}</p>
    <span class="metric-value" data-target="${metric.value}" data-suffix="${metric.suffix}">0${metric.suffix}</span>
    <p class="metric-note">${metric.note}</p>
  `;
  return article;
}

function createPipelineCard(item) {
  const article = document.createElement('article');
  article.className = 'pipeline-card';
  article.innerHTML = `
    <span class="pipeline-stage">${item.stage}</span>
    <h3>${item.title}</h3>
    <p>${item.body}</p>
    <div class="pipeline-pills">${item.pills.map((pill) => `<span>${pill}</span>`).join('')}</div>
  `;
  return article;
}

function createWeightItem(item) {
  const wrapper = document.createElement('article');
  wrapper.className = 'weight-item';
  wrapper.innerHTML = `
    <div class="weight-row">
      <div>
        <strong>${item.name}</strong>
        <p class="metric-note">${item.detail}</p>
      </div>
      <span class="weight-value">${item.value.toFixed(2)}</span>
    </div>
    <div class="weight-bar"><span style="width:${item.value * 100}%"></span></div>
  `;
  return wrapper;
}

function createRiskCard(item) {
  const article = document.createElement('article');
  article.className = 'risk-card';
  article.innerHTML = `
    <span class="risk-tag">Guardrail</span>
    <h3>${item.title}</h3>
    <p>${item.body}</p>
  `;
  return article;
}

function createModuleCard(item) {
  const article = document.createElement('article');
  article.className = 'module-card';
  article.innerHTML = `
    <p class="eyebrow">Backend Layer</p>
    <h3>${item.name}</h3>
    <p>${item.body}</p>
    <div class="module-pills">${item.tags.map((tag) => `<span>${tag}</span>`).join('')}</div>
  `;
  return article;
}

function renderTerminal() {
  const terminal = document.getElementById('terminal-lines');
  terminalLines.forEach((line) => {
    const row = document.createElement('div');
    row.className = 'terminal-line';
    row.innerHTML = `<span>${line.left}</span><strong>${line.right}</strong>`;
    terminal.appendChild(row);
  });
}

function renderSparkline() {
  const host = document.getElementById('sparkline');
  const values = [42, 48, 46, 55, 62, 59, 66, 72, 69, 80, 84, 88];
  const width = 360;
  const height = 110;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 12) - 6;
    return `${x},${y}`;
  }).join(' ');

  host.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="110" aria-label="Signal momentum sparkline">
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(239,143,52,0.38)"></stop>
          <stop offset="100%" stop-color="rgba(239,143,52,0)"></stop>
        </linearGradient>
        <linearGradient id="spark-line" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#69d0b4"></stop>
          <stop offset="100%" stop-color="#f6b15d"></stop>
        </linearGradient>
      </defs>
      <polyline fill="none" stroke="url(#spark-line)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${points}"></polyline>
    </svg>
  `;
}

function animateCounters() {
  const counters = document.querySelectorAll('[data-target]');
  counters.forEach((counter) => {
    const target = Number(counter.dataset.target);
    const suffix = counter.dataset.suffix || '';
    const start = performance.now();
    const duration = 1200;

    function step(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = Math.round(target * eased);
      counter.textContent = `${value}${suffix}`;
      if (progress < 1) {
        requestAnimationFrame(step);
      }
    }

    requestAnimationFrame(step);
  });
}

function init() {
  const metricGrid = document.getElementById('metric-grid');
  metrics.forEach((metric) => metricGrid.appendChild(createMetricCard(metric)));

  const pipelineGrid = document.getElementById('pipeline-grid');
  pipeline.forEach((item) => pipelineGrid.appendChild(createPipelineCard(item)));

  const weightList = document.getElementById('weight-list');
  weights.forEach((item) => weightList.appendChild(createWeightItem(item)));

  const riskGrid = document.getElementById('risk-grid');
  riskChecks.forEach((item) => riskGrid.appendChild(createRiskCard(item)));

  const moduleGrid = document.getElementById('module-grid');
  modules.forEach((item) => moduleGrid.appendChild(createModuleCard(item)));

  renderTerminal();
  renderSparkline();
  animateCounters();
  document.getElementById('footer-year').textContent = `Portfolio frontend ${new Date().getFullYear()}`;
}

window.addEventListener('DOMContentLoaded', init);
