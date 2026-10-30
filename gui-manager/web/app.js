// Antigravity Hub - Frosted Glass Web Frontend Controller
let appState = {
  accounts: [],
  activeIndex: 0,
  openaiAccounts: [],
  claudeAccounts: [],
  routes: {},
  config: {},
  opencodeRunning: false,
  diagnostics: {}
};

// ============================================================================
// TAB NAVIGATION
// ============================================================================
let activeTab = 'dashboard';
let lastStateUpdatedAt = null;
const providerSettings = {
  google:{key:'antigravity',id:'google'}, openai:{key:'openai',id:'openai'},
  claude:{key:'claude',id:'claude-pro'}, xpiki:{key:'xpiki',id:'xpiki'},
  openrouter:{key:'openrouter',id:'openrouter-free'}
};
function providerEnabled(tab) {
  const item = providerSettings[tab];
  return !item || appState.config?.providers_visibility?.[item.key] !== false;
}
function applyProviderVisibility() {
  document.querySelectorAll('.nav-item').forEach(el => { el.style.display = providerEnabled(el.dataset.tab) ? '' : 'none'; });
  document.querySelectorAll('[data-provider-card]').forEach(el => { el.style.display = providerEnabled(el.dataset.providerCard) ? '' : 'none'; });
  if (!providerEnabled(activeTab)) switchTab('dashboard');
}

function switchTab(tabId) {
  if (tabId === 'system') tabId = 'settings';
  if (!providerEnabled(tabId)) tabId = 'dashboard';
  const changed = activeTab !== tabId;
  activeTab = tabId;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tabId);
  });
  document.querySelectorAll('.view-tab').forEach(el => {
    el.style.display = (el.id === `view-${tabId}`) ? 'block' : 'none';
  });
  if (changed) document.getElementById('main-scroll').scrollTop = 0;
}

function showDiagnostics(tab) {
  switchTab('diagnostics');
  document.getElementById(`diagnostics-${tab}`)?.scrollIntoView({behavior:'smooth', block:'start'});
}
async function runAllDiagnostics() {
  await Promise.all(Object.keys(providerTabs).filter(providerEnabled).map(tab => runDiagnostics(tab)));
}

// ============================================================================
// TOAST NOTIFICATIONS
// ============================================================================
function showToast(msg) {
  const container = document.getElementById('toasts');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ============================================================================
// DATA FETCHING & RENDERING
// ============================================================================
let stateRefreshing = false;
let networkFormInitialized = false;
let networkDirty = false;

function html(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
}

async function refreshState() {
  if (!window.pywebview?.api || stateRefreshing) return;
  stateRefreshing = true;
  try {
    const data = await window.pywebview.api.get_state();
    if (!data) return;
    appState = data;
    lastStateUpdatedAt = Date.now();
    renderAll();
    void refreshEnabledDiagnostics();
    void refreshDnsChecks();
  } catch (e) {
    console.error("Failed to refresh state:", e);
    document.getElementById('status-left').textContent = 'Ошибка загрузки: ' + e;
  } finally {
    stateRefreshing = false;
  }
}

function renderAll() {
  renderSidebar();
  renderNetworkTab();
  renderGoogleTab();
  renderOpenAiTab();
  renderClaudeTab();
  renderSettingsTab();
  renderXpikiTab();
  renderOpenRouterState();
  renderActiveAccounts();
  renderProviderDiagnostics();
  applyProviderVisibility();
}

// --- Sidebar ---
function renderSidebar() {
  const opencodeBadge = document.getElementById('sidebar-opencode-status');
  if (opencodeBadge) {
    if (appState.opencodeRunning) {
      opencodeBadge.innerHTML = `<span class="dot" style="color:var(--accent-emerald);"></span><span>OpenCode: Окно открыто</span>`;
      opencodeBadge.style.color = "var(--accent-emerald)";
      opencodeBadge.style.background = "rgba(66, 214, 160, 0.10)";
    } else {
      opencodeBadge.innerHTML = `<span class="dot" style="color:var(--accent-red);"></span><span>OpenCode: Остановлен</span>`;
      opencodeBadge.style.color = "var(--accent-red)";
      opencodeBadge.style.background = "rgba(248, 113, 113, 0.10)";
    }
  }
}

// --- Network Tab (Variant 3) ---
const routeNames = {default:'По настройкам Hub', direct:'Напрямую', dns:'DNS Hub', vless:'VLESS', proxy:'Внешний прокси', 'google-smart':'SmartDNS · эксперимент'};
function autoRouteState(provider) {
  return appState.network?.autoRoutes?.[provider] || {selected:null, status:'pending', rows:[]};
}
function routeLabel(mode, provider = 'google') {
  if (!mode || mode === 'default' || mode === 'auto') {
    const state = autoRouteState(provider);
    return state.selected ? `Авто → ${routeNames[state.selected]}` : state.status === 'not-configured' ? 'Авто: нет маршрутов' : state.running ? 'Авто: проверка…' : state.status === 'unavailable' ? 'Авто: нет связи' : 'Авто: выбрать лучший';
  }
  return routeNames[mode] || mode;
}
function routeDescription(mode, provider = 'google') {
  const automatic = !mode || ['default','auto'].includes(mode);
  const state = autoRouteState(provider);
  if (automatic && !state.selected) return state.status === 'not-configured' ? 'Для Auto настройте VLESS, DNS или HTTP-прокси. Прямое подключение исключено.' : state.status === 'unavailable' ? 'Ни один настроенный маршрут не прошёл проверку HTTPS.' : 'Auto сравнивает настроенные маршруты по HTTPS-доступности и задержке…';
  const selected = automatic ? state.selected : mode;
  const cfg = appState.config || {};
  let detail = routeNames[selected] || selected;
  if (selected === 'dns') {
    const protocol = cfg.dns_mode || 'system';
    const server = protocol === 'standard' ? (cfg.custom_dns || ['143.20.64.55']).join(', ')
      : protocol === 'dot' ? cfg.dot_host : protocol === 'doh' ? cfg.doh_url : 'DNS операционной системы';
    detail += ` · ${dnsModeLabels[protocol]} · ${server || 'сервер не указан'}`;
  }
  if (selected === 'vless' && !appState.network?.vlessRunning) detail += ' · туннель остановлен';
  const measurement = state.rows?.find(row => row.mode === selected);
  return `${automatic ? 'Auto выбрал' : 'Используется'}: ${detail}${automatic && measurement?.latency_ms != null ? ` · HTTPS ${measurement.latency_ms} мс` : ''}`;
}
function renderAutoComparison(provider, tab) {
  const state = autoRouteState(provider);
  const automatic = ['default','auto'].includes(appState.routes?.[provider] || 'default');
  const container = document.getElementById(`auto-routes-${tab}`);
  container.innerHTML = '';
  for (const row of state.rows || []) {
    const div = document.createElement('div');
    div.className = 'auto-route-row';
    div.innerHTML = `<span>${html(routeNames[row.mode])}</span><span class="${row.available ? 'status-good' : 'quota-unknown'}">${row.available ? `${row.passed}/${row.total} · ${row.latency_ms ?? '—'} мс` : 'Недоступен'}</span>${state.selected === row.mode ? `<strong>${automatic ? 'Выбран Auto' : 'Рекомендуется'}</strong>` : ''}`;
    container.appendChild(div);
  }
  if (!state.rows?.length) container.textContent = state.status === 'not-configured' ? 'Нет настроенных маршрутов для сравнения' : state.running ? 'Проверяем HTTPS без API-ключей…' : 'Нажмите «Сравнить маршруты» или выберите Auto';
  const button = document.getElementById(`auto-check-${tab}`);
  button.disabled = !!state.running;
  button.textContent = state.running ? 'Сравнение…' : 'Сравнить маршруты';
}
async function refreshAutoRoutes(tab) {
  try {
    await window.pywebview.api.refresh_auto_routes(providerTabs[tab]);
    await refreshState();
    setTimeout(refreshState, 2000);
  } catch (e) { showToast(`Ошибка Auto: ${e}`); }
}

function renderNetworkTab() {
  const routes = appState.routes || {};
  for (const provider of ['google', 'claude', 'openai', 'xpiki', 'openrouter']) {
    const key = provider === 'claude' ? 'claude-pro' : provider === 'openrouter' ? 'openrouter-free' : provider;
    const options = ['default', 'dns', 'vless', 'direct', 'proxy'];
    if (provider === 'google') options.push('google-smart');
    updateSegmentedGroup(`seg-group-${provider}`, routes[key] || 'default',
      options.map(val => ({val, label:routeLabel(val, key)})));
    document.getElementById(`card-route-${provider}`).textContent = routeDescription(routes[key] || 'default', key);
    renderAutoComparison(key, provider);
  }
  document.getElementById('hub-auto-route').textContent = 'Auto проверяет HTTPS без API-ключей, выбирает маршрут с наибольшей доступностью и наименьшей задержкой. Прямое подключение и экспериментальный SmartDNS в сравнении не участвуют.';
  const net = appState.network || {};
  const badge = document.getElementById('vless-status');
  badge.textContent = net.vlessRunning ? '● Туннель запущен' : '● Остановлен';
  badge.className = `badge-pill ${net.vlessRunning ? 'badge-available' : 'badge-pool'}`;
  document.getElementById('vless-core-status').textContent = net.vlessCore ? `Выбранное ядро: ${net.vlessCore}` : 'Для запуска нужно установить ядро или указать путь к нему';
  const coreList = document.getElementById('vless-core-list');
  coreList.innerHTML = '';
  for (const kind of ['sing-box', 'xray']) {
    const core = net.cores?.[kind] || {};
    const row = document.createElement('div');
    row.className = 'core-row';
    row.innerHTML = `<span class="connection-indicator ${core.installed ? 'ok' : 'idle'}" aria-label="${core.installed ? 'Установлено' : 'Не установлено'}"></span><span class="core-name">${html(kind === 'xray' ? 'Xray' : kind)}</span><span>${core.installed ? 'Установлено' : 'Не установлено'}${core.selected ? ' · выбрано' : ''}</span>${core.installed && !core.selected ? '<button class="btn-secondary">Выбрать</button>' : ''}${core.path ? `<span class="core-path">${html(core.path)}</span>` : ''}`;
    row.querySelector('button')?.addEventListener('click', () => { document.getElementById('vless-core-path').value = core.path; networkDirty = true; showToast('Ядро выбрано. Сохраните настройки сети.'); });
    coreList.appendChild(row);
    const button = document.getElementById(`btn-download-${kind}`);
    button.disabled = !!core.installed;
    button.textContent = core.installed ? `${kind === 'xray' ? 'Xray' : kind} установлен` : `Скачать ${kind === 'xray' ? 'Xray' : kind}`;
  }
  const proxyConfigured = !!appState.config?.proxy;
  document.getElementById('http-proxy-indicator').className = `connection-indicator ${proxyConfigured ? 'ok' : 'idle'}`;
  document.getElementById('http-proxy-indicator').setAttribute('aria-label', proxyConfigured ? 'Прокси настроен' : 'Прокси не задан');
  document.getElementById('http-proxy-status').textContent = proxyConfigured ? 'Адрес сохранён. Доступность проверяется во вкладке провайдера.' : 'Прокси не настроен';
  document.getElementById('btn-vless-start').disabled = !!net.vlessRunning;
  document.getElementById('btn-vless-stop').disabled = !net.vlessRunning;
  if (!networkFormInitialized) fillNetworkForm();
  const cfg = appState.config || {};
  const mode = cfg.dns_mode || 'system';
  const resolver = mode === 'standard' ? (cfg.custom_dns || ['143.20.64.55','31.58.216.201']).join(', ')
    : mode === 'dot' ? cfg.dot_host : mode === 'doh' ? cfg.doh_url : 'DNS операционной системы';
  document.getElementById('dns-active-summary').textContent = `Применяется сейчас: ${dnsModeLabels[mode]} · ${resolver || 'не задан'}.`;
  renderDnsStatus();

}

function fillNetworkForm() {
  const cfg = appState.config || {};
  const values = {'vless-url':cfg.vless_url || '', 'vless-core-path':cfg.vless_core_path || '',
    'dns-mode':cfg.dns_mode || 'system', 'dns-primary':(cfg.custom_dns || ['143.20.64.55'])[0] || '',
    'dns-secondary':(cfg.custom_dns || ['143.20.64.55','31.58.216.201'])[1] || '',
    'dns-dot':cfg.dot_host || 'dns.bezmezhau.com', 'dns-doh':cfg.doh_url || 'https://dns.bezmezhau.com/dns-query',
    'google-smart-doh':cfg.google_smart_doh || 'https://dns.dns-ai.ru/dns-query', 'network-proxy':cfg.proxy || ''};
  for (const [id, value] of Object.entries(values)) document.getElementById(id).value = value;
  document.getElementById('vless-kill-switch').checked = cfg.vless_kill_switch !== false;
  document.getElementById('dns-preset').value = 'custom';
  networkFormInitialized = true;
  updateDnsFields();
}

const dnsModeLabels = {standard:'Обычный DNS',doh:'DNS-over-HTTPS (DoH)',dot:'DNS-over-TLS (DoT)',system:'Системный DNS'};
const dnsChecks = new Map();
const dnsPending = new Map();
let dnsAutoTimer = null;
function scheduleDnsChecks() {
  if (!window.pywebview?.api) return;
  if (dnsAutoTimer !== null) clearTimeout(dnsAutoTimer);
  dnsAutoTimer = setTimeout(() => { dnsAutoTimer = null; void refreshDnsChecks(); }, 800);
}
function onDnsInput() {
  networkDirty = true;
  document.getElementById('dns-result').textContent = '';
  renderDnsStatus();
  scheduleDnsChecks();
}
function selectDnsMode(mode) {
  if (!(mode in dnsModeLabels)) return;
  document.getElementById('dns-mode').value = mode;
  networkDirty = true;
  document.getElementById('dns-result').textContent = '';
  updateDnsFields();
}
function updateDnsFields() {
  const mode = document.getElementById('dns-mode').value;
  for (const key of Object.keys(dnsModeLabels)) {
    const button = document.getElementById(`dns-mode-${key}`);
    button.classList.toggle('active', mode === key);
    button.setAttribute('aria-checked', String(mode === key));
  }
  for (const key of ['standard', 'dot', 'doh']) document.getElementById(`dns-${key}-fields`).style.display = mode === key ? (key === 'standard' ? 'grid' : 'block') : 'none';
  document.getElementById('dns-preset').disabled = mode === 'system';
  document.getElementById('btn-dns-test').disabled = mode === 'system';
  renderDnsStatus();
  scheduleDnsChecks();
}
function selectedDnsAddresses() {
  const mode = document.getElementById('dns-mode').value;
  const ids = mode === 'standard' ? ['dns-primary','dns-secondary'] : mode === 'dot' ? ['dns-dot'] : mode === 'doh' ? ['dns-doh'] : [];
  return ids.map(id => ({id, mode, value:document.getElementById(id).value.trim()}));
}
function dnsBadge(element, state, label) {
  element.className = `badge-pill ${state === 'ok' ? 'badge-available' : state === 'error' ? 'badge-error' : state === 'checking' ? 'badge-checking' : 'badge-pool'}${element.id === 'dns-status' ? '' : ' dns-address-status'}`;
  element.textContent = `● ${label}`;
}
function renderDnsStatus() {
  const mode = document.getElementById('dns-mode').value;
  const targets = selectedDnsAddresses();
  const states = [];
  for (const target of targets) {
    const result = dnsChecks.get(`${mode}:${target.value}`);
    const state = result?.state || 'idle';
    if (target.value) states.push(state);
    const label = !target.value ? 'Не задан' : state === 'ok' ? `Доступен${result.latency_ms == null ? '' : ` · ${result.latency_ms} мс`}` : state === 'error' ? 'Недоступен' : state === 'checking' ? 'Проверка…' : 'Не проверен';
    const badge = document.getElementById(`${target.id}-status`);
    dnsBadge(badge, state, label);
    badge.title = result?.message || (target.value ? `${dnsModeLabels[mode]}: ${target.value}` : 'Адрес не задан');
  }
  const overall = states.includes('checking') ? 'checking' : states.includes('error') ? 'error' : states.length && states.every(s=>s === 'ok') ? 'ok' : 'idle';
  dnsBadge(document.getElementById('dns-status'), overall, mode === 'system' ? 'Системный DNS' : overall === 'ok' ? 'DNS доступен' : overall === 'error' ? 'Есть недоступные DNS' : overall === 'checking' ? 'Проверка…' : 'Не проверен');
  document.getElementById('btn-dns-test').disabled = mode === 'system' || states.includes('checking');
  const cfg = appState.config || {};
  const savedValues = mode === 'standard' ? (cfg.custom_dns || ['143.20.64.55','31.58.216.201']) : mode === 'dot' ? [cfg.dot_host || 'dns.bezmezhau.com'] : mode === 'doh' ? [cfg.doh_url || 'https://dns.bezmezhau.com/dns-query'] : [];
  const changed = mode !== (cfg.dns_mode || 'system') || targets.some((t,i)=>t.value !== (savedValues[i] || ''));
  document.getElementById('dns-selection-summary').textContent = `Выбрано: ${dnsModeLabels[mode]}. ${changed ? 'Нажмите «Применить DNS», чтобы использовать этот вариант.' : 'Этот вариант уже сохранён.'}`;
  renderDashboard();
}
async function saveDnsSettings() {
  const button = document.getElementById('btn-dns-apply');
  const output = document.getElementById('dns-result');
  button.disabled = true;
  try {
    const value = id => document.getElementById(id).value.trim();
    const result = await window.pywebview.api.save_network_settings({dns_mode:value('dns-mode'),
      custom_dns:[value('dns-primary'),value('dns-secondary')].filter(Boolean), dot_host:value('dns-dot'), doh_url:value('dns-doh')});
    if (!result.ok) throw new Error(result.message);
    await refreshState();
    output.textContent = `${dnsModeLabels[value('dns-mode')]} применяется к новым подключениям через DNS Hub.`;
    renderDnsStatus();
  } catch (e) { output.textContent = String(e); }
  finally { button.disabled = false; }
}

function applyDnsPreset() {
  const presets = {
    bezmezhau:['143.20.64.55','31.58.216.201','dns.bezmezhau.com','https://dns.bezmezhau.com/dns-query'],
    cloudflare:['1.1.1.1','1.0.0.1','cloudflare-dns.com','https://cloudflare-dns.com/dns-query'],
    google:['8.8.8.8','8.8.4.4','dns.google','https://dns.google/dns-query'],
    quad9:['9.9.9.9','149.112.112.112','dns.quad9.net','https://dns.quad9.net/dns-query']
  };
  const values = presets[document.getElementById('dns-preset').value];
  if (values) ['dns-primary','dns-secondary','dns-dot','dns-doh'].forEach((id,i) => document.getElementById(id).value = values[i]);
  networkDirty = true;
  document.getElementById('dns-result').textContent = '';
  renderDnsStatus();
  scheduleDnsChecks();
}

async function saveNetworkSettings() {
  const value = id => document.getElementById(id).value.trim();
  const button = document.getElementById('btn-network-save');
  button.disabled = true;
  try {
    const result = await window.pywebview.api.save_network_settings({
      vless_url:value('vless-url'), vless_core_path:value('vless-core-path') || null,
      vless_kill_switch:document.getElementById('vless-kill-switch').checked,
      dns_mode:value('dns-mode'), custom_dns:[value('dns-primary'),value('dns-secondary')].filter(Boolean),
      dot_host:value('dns-dot'), doh_url:value('dns-doh'), google_smart_doh:value('google-smart-doh'), proxy:value('network-proxy')
    });
    if (!result.ok) throw new Error(result.message);
    networkDirty = false;
    document.getElementById('network-save-result').textContent = result.message;
    await refreshState();
    return true;
  } catch (e) {
    document.getElementById('network-save-result').textContent = String(e);
    showToast(`Не удалось сохранить сеть: ${e}`);
    return false;
  } finally { button.disabled = false; }
}

async function vlessAction(action) {
  const output = document.getElementById('vless-result');
  output.textContent = 'Выполняется…';
  try {
    if (action === 'start' && !(await saveNetworkSettings())) { output.textContent = 'Сначала исправьте настройки сети'; return; }
    const result = await window.pywebview.api[`${action}_vless`]();
    output.textContent = result.message || (result.ok ? `IP: ${result.ip || '—'} · ${result.country || ''} · ${result.latency_ms ?? '—'} мс` : 'Ошибка подключения');
    await refreshState();
  } catch (e) { output.textContent = String(e); }
}

async function downloadCore(type) {
  const output = document.getElementById('vless-result');
  output.textContent = `Скачивание ${type}…`;
  try {
    const result = await window.pywebview.api.download_vless_core(type);
    output.textContent = result.message;
    await refreshState();
  } catch (e) { output.textContent = String(e); }
}

function validDnsTarget(target) {
  if (target.mode === 'standard') {
    const parts = target.value.split('.');
    return parts.length === 4 && parts.every(part => /^\d{1,3}$/.test(part) && Number(part) <= 255);
  }
  if (target.mode === 'doh') {
    try { const url = new URL(target.value); return url.protocol === 'https:' && !!url.hostname; }
    catch { return false; }
  }
  return !!target.value && /^[a-zA-Z0-9.-]+(?::[0-9]+)?$/.test(target.value);
}
async function refreshDnsChecks(force = false) {
  if (!window.pywebview?.api) return;
  const targets = selectedDnsAddresses().filter(target => target.value && (force || validDnsTarget(target)));
  if (!targets.length) {
    if (force) document.getElementById('dns-result').textContent = 'Укажите адрес DNS-сервера';
    return;
  }
  const signature = JSON.stringify(selectedDnsAddresses());
  const now = Date.now();
  const due = targets.filter(target => {
    const cached = dnsChecks.get(`${target.mode}:${target.value}`);
    return dnsPending.has(`${target.mode}:${target.value}`) || force || !cached?.checkedAt || now - cached.checkedAt >= 60000;
  });
  if (!due.length) return;
  document.getElementById('dns-result').textContent = force ? 'Проверяем выбранные DNS-серверы…' : 'Автоматическая проверка DNS…';
  const jobs = due.map(target => {
    const key = `${target.mode}:${target.value}`;
    if (dnsPending.has(key)) return dnsPending.get(key);
    dnsChecks.set(key, {...dnsChecks.get(key), state:'checking'});
    const job = (async () => {
      // Register the shared job before calling a bridge method that may throw.
      await Promise.resolve();
      let result;
      try { result = await window.pywebview.api.test_dns(target.mode, target.value); }
      catch (e) { result = {ok:false,message:String(e)}; }
      result = {...result, state:result.ok ? 'ok' : 'error', checkedAt:Date.now()};
      dnsChecks.set(key, result);
      dnsPending.delete(key);
      renderDnsStatus();
      return result;
    })();
    dnsPending.set(key, job);
    return job;
  });
  renderDnsStatus();
  await Promise.all(jobs);
  if (signature === JSON.stringify(selectedDnsAddresses())) {
    document.getElementById('dns-result').textContent = targets.map(target => {
      const result = dnsChecks.get(`${target.mode}:${target.value}`);
      return `${target.value}: ${result?.message || (result?.state === 'ok' ? 'Доступен' : 'Недоступен')}`;
    }).join(' · ');
  }
}
async function testDns() {
  if (dnsAutoTimer !== null) { clearTimeout(dnsAutoTimer); dnsAutoTimer = null; }
  await refreshDnsChecks(true);
}

function updateSegmentedGroup(groupId, currentVal, options) {
  const group = document.getElementById(groupId);
  if (!group) return;
  group.innerHTML = "";
  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.className = `seg-btn ${opt.val === currentVal ? "active" : ""}`;
    btn.textContent = opt.label;
    if (opt.val === 'default') btn.title = 'Сравнить настроенные VLESS, DNS и HTTP-прокси. Выбрать доступный маршрут с наименьшей задержкой. При отказе соединения — переключиться на другой проверенный маршрут.';
    btn.onclick = () => {
      const provider = groupId.replace("seg-group-", "");
      setProviderRoute(provider, opt.val);
    };
    group.appendChild(btn);
  });
}

async function setProviderRoute(provider, route) {
  if (!window.pywebview || !window.pywebview.api) return;
  try {
    const ok = await window.pywebview.api.set_provider_route(provider, route);
    if (ok) {
      await refreshState();
      showToast(`Маршрут для ${provider} переключен на ${route}`);
    }
  } catch (e) {
    showToast(`Ошибка смены маршрута: ${e}`);
  }
}

const providerTabs = {google:'google', openai:'openai', claude:'claude-pro', xpiki:'xpiki', openrouter:'openrouter-free'};
const diagnosticDomains = {
  google:['daily-cloudcode-pa.googleapis.com','cloudcode-pa.googleapis.com','containers.cloud.google.com','artifactregistry.googleapis.com','oauth2.googleapis.com','clients6.google.com'],
  openai:['chatgpt.com','auth.openai.com','api.openai.com'],
  claude:['claude.ai','api.anthropic.com','console.anthropic.com'],
  xpiki:['api.xpiki.com'], openrouter:['openrouter.ai']
};
const diagnosticBusy = new Set();
const diagnosticAttempts = new Map();
const diagnosticErrors = new Map();
function diagnosticSignature(tab) {
  const cfg = appState.config || {};
  return JSON.stringify([tab, appState.routes || {}, cfg.dns_mode, cfg.custom_dns, cfg.dot_host,
    cfg.doh_url, cfg.proxy, cfg.vless_enabled, cfg.vless_url, cfg.google_smart_doh,
    appState.network?.vlessRunning, appState.providers?.xpiki?.baseUrl, appState.network?.autoRoutes?.[providerTabs[tab]]?.selected]);
}
async function refreshEnabledDiagnostics() {
  const now = Date.now();
  const targets = Object.keys(providerTabs).filter(tab => {
    if (!providerEnabled(tab) || diagnosticBusy.has(tab)) return false;
    const previous = diagnosticAttempts.get(tab);
    return !previous || previous.signature !== diagnosticSignature(tab) || now - previous.time >= 60000;
  });
  await Promise.all(targets.map(tab => runDiagnostics(tab, true)));
}
async function runDiagnostics(tab = 'google', automatic = false) {
  if (diagnosticBusy.has(tab) || !providerEnabled(tab) || !window.pywebview?.api) return;
  const signature = diagnosticSignature(tab);
  diagnosticAttempts.set(tab, {signature, time:Date.now()});
  diagnosticErrors.delete(tab);
  diagnosticBusy.add(tab);
  renderProviderDiagnostics();
  try {
    const rows = await window.pywebview.api.run_provider_diagnostics(providerTabs[tab]);
    if (signature !== diagnosticSignature(tab)) return;
    if (!appState.diagnostics || Array.isArray(appState.diagnostics)) appState.diagnostics = {};
    appState.diagnostics[providerTabs[tab]] = {rows, running:false, checkedAt:Date.now()/1000};
  } catch (e) {
    diagnosticErrors.set(tab, String(e));
    if (!automatic) showToast(`Ошибка проверки доменов: ${e}`);
  } finally { diagnosticBusy.delete(tab); renderProviderDiagnostics(); }
}

function renderProviderDiagnostics() {
  for (const [tab, provider] of Object.entries(providerTabs)) {
    const state = appState.diagnostics?.[provider] || {};
    const running = !!state.running || diagnosticBusy.has(tab);
    const rows = state.rows?.length ? state.rows : diagnosticDomains[tab].map(domain => ({domain,status:'idle'}));
    const button = document.getElementById(`btn-diag-${tab}`);
    const enabled = providerEnabled(tab);
    button.disabled = running || !enabled;
    button.textContent = !enabled ? 'Провайдер отключён' : running ? 'Проверка…' : 'Проверить домены';
    const tbody = document.getElementById(`diag-tbody-${tab}`);
    tbody.innerHTML = '';
    for (const item of rows) {
      const status = running ? 'checking' : item.status;
      const label = status === 'ok' ? 'TCP доступен' : status === 'error' ? `Ошибка: ${item.error || 'нет соединения'}` : running ? 'Проверка' : 'Не проверялся';
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="domain-cell">${html(item.domain)}</td><td class="diagnostic-state"><span class="connection-indicator ${html(status)}" role="img" title="${html(label)}" aria-label="${html(label)}"></span></td><td>${item.latency_ms == null ? '—' : html(item.latency_ms) + ' мс'}</td><td>${html(item.route || routeLabel(appState.routes?.[provider] || 'default', provider))}</td><td>${html(item.ip || '—')}</td>`;
      tbody.appendChild(tr);
    }
    const count = state.rows?.length || 0;
    const available = (state.rows || []).filter(row => row.status === 'ok').length;
    const summary = running ? 'checking' : diagnosticErrors.has(tab) ? 'error' : !count ? 'idle' : available === count ? 'ok' : available ? 'warning' : 'error';
    const text = running ? 'Проверка…' : diagnosticErrors.has(tab) ? 'Ошибка проверки' : !count ? 'Не проверено' : available ? `Домены: ${available}/${count}` : 'Нет соединения';
    const badge = document.getElementById(`provider-status-${tab}`);
    badge.className = `badge-pill provider-status ${summary === 'ok' ? 'badge-available' : summary === 'error' ? 'badge-error' : ['warning','checking'].includes(summary) ? 'badge-checking' : 'badge-pool'}`;
    badge.innerHTML = `<span class="connection-indicator ${summary}"></span><span>${html(text)}</span>`;
    badge.setAttribute('aria-label', text);
    badge.title = diagnosticErrors.get(tab) || (count ? `TCP доступен для ${available} из ${count} доменов. Подробности во вкладке провайдера.` : 'Автоматическая проверка доменов');
    const checked = state.checkedAt;
    document.getElementById(`card-check-time-${tab}`).textContent = running ? 'Проверяем выбранный маршрут…' : checked ? `TCP · ${new Date(checked*1000).toLocaleTimeString('ru-RU')}` : 'Автопроверка каждую минуту';
    const retry = document.getElementById(`card-check-${tab}`);
    retry.disabled = false;
    retry.textContent = 'Диагностика →';
  }
  const all = document.getElementById('btn-diag-all');
  const running = Object.keys(providerTabs).some(tab => providerEnabled(tab) && (diagnosticBusy.has(tab) || appState.diagnostics?.[providerTabs[tab]]?.running));
  const enabledCount = Object.keys(providerTabs).filter(providerEnabled).length;
  all.disabled = running || !enabledCount;
  all.textContent = running ? 'Проверка…' : 'Проверить все';
  const latencies = Object.values(appState.diagnostics || {}).flatMap(d => d.rows || []).filter(r=>r.status === 'ok' && r.latency_ms != null).map(r=>r.latency_ms);
  document.getElementById('avg-latency-val').textContent = latencies.length ? `${Math.round(latencies.reduce((a,b)=>a+b,0)/latencies.length)} мс` : '—';
  renderDashboard();
}

function resetLabel(window) {
  const raw = window?.reset_at || window?.resetTime;
  if (raw) {
    const number = Number(raw);
    const date = Number.isFinite(number) ? new Date(number < 1e12 ? number * 1000 : number) : new Date(raw);
    if (!Number.isNaN(date.getTime())) return `Сброс: ${date.toLocaleString('ru-RU')}`;
  }
  return window?.reset_label ? `Сброс ${window.reset_label}` : 'Время сброса неизвестно';
}

function quotaMarkup(title, window, color, available = true) {
  const raw = window?.remaining_percent ?? window?.remainingPercent;
  const known = available && raw != null && Number.isFinite(Number(raw));
  const percent = known ? Math.max(0, Math.min(100, Number(raw))) : null;
  return `<div class="quota-row"><div class="quota-meta"><span class="quota-title">${html(title)}</span><span class="quota-percent ${known ? color : 'quota-unknown'}">${known ? `${percent}% осталось` : 'Нет данных'}</span></div><div class="progress-track"><div class="progress-fill-${color === 'green' ? 'emerald' : 'amber'}" style="width:${percent ?? 0}%"></div></div><div class="quota-reset">${known ? html(resetLabel(window)) : 'Обновите лимиты, чтобы получить данные'}</div></div>`;
}

const dashboardProviderInfo = {
  google:{name:'Google Antigravity',icon:'G',color:'#71a7ff'},
  openai:{name:'ChatGPT',icon:'◎',color:'#42d6a0'},
  claude:{name:'Claude Pro',icon:'✦',color:'#e6a36b'},
  xpiki:{name:'Claude API · Xpiki',icon:'ϟ',color:'#f0b257'},
  openrouter:{name:'OpenRouter Free',icon:'◉',color:'#b29aff'}
};
function dashboardAccess(tab) {
  if (['google','openai','claude'].includes(tab)) {
    const accounts = (tab === 'google' ? appState.accounts : tab === 'openai' ? appState.openaiAccounts : appState.claudeAccounts) || [];
    const active = accounts.find(account => account.is_active === true);
    return {active, connected:!!active, count:accounts.length,
      label:active?.email || active?.name || (accounts.length ? 'Активный аккаунт не выбран' : 'Нет аккаунтов')};
  }
  const cfg = appState.providers?.[tab] || {};
  return {active:null, connected:!!cfg.connected, count:cfg.hasKey ? 1 : 0,
    label:cfg.hasKey ? `API-ключ ${cfg.keyLabel || 'сохранён'}` : 'Ключ не задан'};
}
function dashboardQuota(tab, active) {
  if (tab === 'google') {
    const windows = active?.groups?.find(group => group.name === 'gemini')?.windows || [];
    return [{label:'5 часов',value:windows.find(w=>/5h|5.hour|5ч|short/i.test(String(w.window)))?.remainingPercent},
      {label:'Неделя',value:windows.find(w=>/week|7d|нед/i.test(String(w.window)))?.remainingPercent}];
  }
  if (tab === 'openai') {
    const quota = active?.quota || {};
    const valid = ['ok','stale'].includes(quota.status);
    return [{label:'5 часов',value:valid ? (quota.window_5h || quota.primary)?.remaining_percent : null},
      {label:'Неделя',value:valid ? (quota.window_weekly || quota.secondary)?.remaining_percent : null}];
  }
  return [];
}
function dashboardPercent(value) {
  return value != null && Number.isFinite(Number(value)) ? Math.max(0,Math.min(100,Number(value))) : null;
}
function dashboardQuotaHtml(item) {
  const value = dashboardPercent(item.value);
  const tone = value == null ? 'muted' : value === 0 ? 'error' : value <= 20 ? 'warning' : 'ok';
  return `<div class="dashboard-quota"><div><span>${html(item.label)}</span><strong class="dashboard-tone-${tone}">${value == null ? 'Нет данных' : `${value}%`}</strong></div><div class="dashboard-quota-track"><span class="dashboard-fill-${tone}" style="width:${value ?? 0}%"></span></div></div>`;
}
function dashboardDns() {
  const cfg = appState.config || {};
  const mode = cfg.dns_mode || 'system';
  const values = mode === 'standard' ? (cfg.custom_dns || ['143.20.64.55','31.58.216.201'])
    : mode === 'dot' ? [cfg.dot_host || 'dns.bezmezhau.com'] : mode === 'doh' ? [cfg.doh_url || 'https://dns.bezmezhau.com/dns-query'] : [];
  const checks = values.filter(Boolean).map(value=>dnsChecks.get(`${mode}:${value}`));
  const fresh = check => check && check.checkedAt && Date.now()-check.checkedAt < 90000;
  const status = mode === 'system' ? 'idle' : checks.some(check=>check?.state === 'checking') ? 'checking'
    : checks.some(check=>fresh(check) && check.state === 'error') ? 'error'
    : checks.length && checks.every(check=>fresh(check) && check.state === 'ok') ? 'ok' : 'idle';
  let server = values.join(', ');
  if (mode === 'doh') { try { const url = new URL(values[0]); server=url.hostname+url.pathname; } catch { server='Сервер не задан'; } }
  return {mode,status,server:server || 'DNS операционной системы',
    label:mode === 'system' ? 'По настройкам ОС' : status === 'ok' ? 'Доступен' : status === 'error' ? 'Ошибка DNS' : status === 'checking' ? 'Проверка…' : 'Ожидает проверки'};
}
function dashboardTime(value) {
  return new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Europe/Moscow'});
}
function renderDashboard() {
  const tabs = Object.keys(dashboardProviderInfo).filter(providerEnabled);
  const connected = tabs.filter(tab=>dashboardAccess(tab).connected).length;
  const totalAccounts = tabs.reduce((sum,tab)=>sum+dashboardAccess(tab).count,0);
  const rows = tabs.flatMap(tab=>appState.diagnostics?.[providerTabs[tab]]?.rows || []);
  const passed = rows.filter(row=>row.status === 'ok').length;
  const running = tabs.some(tab=>diagnosticBusy.has(tab) || appState.diagnostics?.[providerTabs[tab]]?.running);
  const failed = rows.length-passed;
  const domainTone = failed ? 'warning' : rows.length ? 'ok' : 'muted';
  const metrics = [
    {title:'OpenCode',value:appState.opencodeRunning ? 'Запущен' : 'Остановлен',note:appState.opencodeRunning ? 'Процесс приложения работает' : 'Запуск доступен в настройках',tone:appState.opencodeRunning ? 'ok' : 'muted',icon:'⌘'},
    {title:'Провайдеры',value:`${connected} / ${tabs.length}`,note:`Подключено из включённых · всего ${Object.keys(dashboardProviderInfo).length}`,tone:connected === tabs.length && tabs.length ? 'ok' : 'warning',icon:'◈'},
    {title:'Аккаунты и ключи',value:String(totalAccounts),note:'Сохранённые доступы включённых провайдеров',tone:'neutral',icon:'◎'},
    {title:'Домены доступны',value:rows.length ? `${passed} / ${rows.length}` : '—',note:running ? 'Проверки выполняются…' : rows.length ? 'Результат TCP-проверки маршрутов' : 'Ожидаем результаты автопроверки',tone:domainTone,icon:'↗'}
  ];
  document.getElementById('dashboard-metrics').innerHTML = metrics.map(metric=>`<div class="glass-card dashboard-metric"><div class="dashboard-metric-title"><span>${html(metric.title)}</span><span>${metric.icon}</span></div><strong class="dashboard-tone-${metric.tone}">${html(metric.value)}</strong><p>${html(metric.note)}</p></div>`).join('');
  document.getElementById('dashboard-updated').textContent = lastStateUpdatedAt ? `Сводка: ${dashboardTime(lastStateUpdatedAt)} · 10 с` : 'Обновление каждые 10 с';
  const checkButton = document.getElementById('dashboard-check');
  checkButton.disabled = running || !tabs.length;
  checkButton.textContent = running ? 'Проверка…' : 'Проверить домены';
  const alerts = [];
  const providerGrid = document.getElementById('dashboard-providers');
  providerGrid.innerHTML = '';
  for (const tab of tabs) {
    const info = dashboardProviderInfo[tab];
    const access = dashboardAccess(tab);
    const state = appState.diagnostics?.[providerTabs[tab]] || {};
    const busy = diagnosticBusy.has(tab) || state.running;
    const domains = state.rows || [];
    const available = domains.filter(row=>row.status === 'ok').length;
    const domainText = busy ? 'Проверка…' : domains.length ? `Домены ${available}/${domains.length}` : 'Не проверено';
    const domainState = busy ? 'checking' : !domains.length ? 'idle' : available === domains.length ? 'ok' : available ? 'warning' : 'error';
    const badge = domainState === 'ok' ? 'badge-available' : domainState === 'error' ? 'badge-error' : ['checking','warning'].includes(domainState) ? 'badge-checking' : 'badge-pool';
    const quota = dashboardQuota(tab, access.active);
    let limits = quota.map(dashboardQuotaHtml).join('');
    const cfg = appState.providers?.[tab] || {};
    if (tab === 'xpiki') {
      const q = cfg.quota || {};
      const valid = ['ok','stale'].includes(q.status);
      const amount = value => value != null && Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU') : '—';
      limits = `<div class="dashboard-token-balance"><span>Остаток токенов</span><strong>${valid ? amount(q.remaining_tokens) : 'Нет данных'}</strong><small>${valid ? `из ${amount(q.quota_limit)}${q.status === 'stale' ? ' · сохранённые данные' : ''}` : 'Обновите квоту во вкладке Xpiki'}</small></div>`;
      if (valid && dashboardPercent(q.remaining_percent) != null && Number(q.remaining_percent) <= 20) alerts.push({priority:1,tab,text:`Xpiki: осталось ${q.remaining_percent}% квоты`});
    }
    if (tab === 'openrouter') limits = `<div class="dashboard-token-balance"><span>Моделей в OpenCode</span><strong>${cfg.selectedModels?.length || 0}</strong><small>Выбор каталога во вкладке OpenRouter</small></div>`;
    if (tab === 'claude') limits = `<div class="dashboard-token-balance"><span>Тариф</span><strong>${html(access.active?.plan || '—')}</strong><small>Данные о лимитах сессии не получены</small></div>`;
    const activeQuota = access.active?.quota || {};
    const quotaNote = tab === 'openai' && activeQuota.last_checked ? `Лимиты: ${dashboardTime(activeQuota.last_checked*1000)}${activeQuota.status === 'stale' ? ' · сохранённые данные' : ''}` : 'Лимиты показаны по последним полученным данным';
    const route = appState.routes?.[providerTabs[tab]] || 'default';
    const card = document.createElement('div');
    card.className = 'glass-card dashboard-provider';
    card.innerHTML = `<div class="dashboard-provider-heading"><span class="dashboard-provider-icon" style="color:${info.color}">${info.icon}</span><h3>${html(info.name)}</h3><span class="badge-pill ${badge}"><span class="connection-indicator ${domainState}"></span>${html(domainText)}</span></div><div class="dashboard-access"><span>${access.connected ? 'Активный доступ' : 'Подключение не настроено'}</span><strong>${html(access.label)}</strong></div><div class="dashboard-provider-limits">${limits}</div>${quota.length ? `<p class="dashboard-quota-note">${html(quotaNote)}</p>` : ''}<div class="dashboard-provider-route"><span>Маршрут</span><strong>${html(routeLabel(route,providerTabs[tab]))}</strong></div><button class="btn-secondary dashboard-provider-open">Открыть ${tab === 'xpiki' || tab === 'openrouter' ? 'провайдера' : 'аккаунты'} →</button>`;
    card.querySelector('button')?.addEventListener('click',()=>switchTab(tab));
    providerGrid.appendChild(card);
    if (!access.connected) alerts.push({priority:3,tab,text:`${info.name}: ${access.count ? 'активный доступ не подключён' : 'добавьте аккаунт или ключ'}`});
    for (const item of quota) {
      const value = dashboardPercent(item.value);
      if (value != null && value <= 20) alerts.push({priority:value === 0 ? 0 : 4,tab,text:`${info.name}: ${item.label.toLowerCase()} — ${value === 0 ? 'лимит исчерпан' : `осталось ${value}%`}`});
    }
    if (!busy && domains.some(row=>row.status !== 'ok')) alerts.push({priority:2,tab,diagnostics:true,text:`${info.name}: недоступны ${domains.length-available} из ${domains.length} доменов`});
    const auto = autoRouteState(providerTabs[tab]);
    if (['default','auto'].includes(route) && !auto.running && ['unavailable','not-configured'].includes(auto.status)) alerts.push({priority:1,tab,text:`${info.name}: Auto не нашёл доступный маршрут`});
  }
  if (!tabs.length) providerGrid.innerHTML = '<div class="glass-card dashboard-empty"><h3>Провайдеры выключены</h3><p class="help-text">Включите нужные провайдеры в разделе «Настройки и система».</p></div>';
  const dns = dashboardDns();
  const net = appState.network || {};
  const core = net.vlessCore ? String(net.vlessCore).split(/[\\/]/).pop() : 'Ядро не выбрано';
  let proxy = 'Не настроен';
  try {
    const url = new URL(appState.config?.proxy || '');
    if (!(['127.0.0.1','localhost','[::1]'].includes(url.hostname) && ['10880','51180'].includes(url.port))) proxy=url.hostname+(url.port ? `:${url.port}` : '');
  } catch {}
  document.getElementById('dashboard-network').innerHTML = `<div class="dashboard-network-row"><div><strong>VLESS</strong><span>${html(core)}</span></div><span class="badge-pill ${net.vlessRunning ? 'badge-available' : 'badge-pool'}">● ${net.vlessRunning ? 'Работает' : 'Остановлен'}</span></div><div class="dashboard-network-row"><div><strong>${html(dnsModeLabels[dns.mode] || 'DNS')}</strong><span>${html(dns.server)}</span></div><span class="badge-pill ${dns.status === 'ok' ? 'badge-available' : dns.status === 'error' ? 'badge-error' : dns.status === 'checking' ? 'badge-checking' : 'badge-pool'}">● ${html(dns.label)}</span></div><div class="dashboard-network-row"><div><strong>HTTP(S)-прокси</strong><span>${html(proxy)}</span></div></div><p class="dashboard-quota-note">Auto сравнивает настроенные маршруты по HTTPS. Прямое подключение исключено.</p>`;
  const usesVless = tabs.some(tab=>appState.routes?.[providerTabs[tab]] === 'vless' || (['default','auto'].includes(appState.routes?.[providerTabs[tab]] || 'default') && autoRouteState(providerTabs[tab]).selected === 'vless'));
  if (!net.vlessRunning && (usesVless || appState.config?.vless_enabled)) alerts.push({priority:0,network:true,text:'VLESS нужен для выбранного маршрута, но туннель остановлен'});
  if (dns.status === 'error') alerts.push({priority:2,network:true,text:'Сохранённый DNS-сервер не прошёл проверку доступности'});
  const attention = document.getElementById('dashboard-attention');
  attention.innerHTML = '';
  alerts.sort((a,b)=>a.priority-b.priority);
  for (const alert of alerts) {
    const row = document.createElement('button');
    row.className = 'dashboard-alert';
    row.innerHTML = `<span class="dashboard-alert-dot ${alert.priority === 0 ? 'critical' : ''}"></span><span>${html(alert.text)}</span><span>→</span>`;
    row.addEventListener('click',()=>alert.network ? switchTab('network') : alert.diagnostics ? showDiagnostics(alert.tab) : switchTab(alert.tab));
    attention.appendChild(row);
  }
  if (!alerts.length) attention.innerHTML = `<div class="dashboard-clear"><span>✓</span><strong>${running || !rows.length ? 'Собираем результаты проверок' : 'Нет обнаруженных проблем'}</strong><p>${tabs.length ? 'Статусы и лимиты обновляются автоматически.' : 'Обзор появится после включения провайдеров.'}</p></div>`;
}

// --- Google Tab (Accounts & Quotas) ---
function renderGoogleTab() {
  const container = document.getElementById("google-accounts-list");
  if (!container) return;

  const accounts = appState.accounts || [];


  if (accounts.length === 0) {
    container.innerHTML = `
      <div class="glass-card" style="text-align: center; padding: 40px;">
        <div style="font-size: 36px; margin-bottom: 12px;">📭</div>
        <div style="font-size: 16px; font-weight: 700; color: #fff;">Нет подключенных аккаунтов Google</div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-top: 6px; margin-bottom: 20px;">
          Нажмите кнопку «＋ Добавить аккаунт» вверху для входа через браузер.
        </div>
        <button class="btn-primary" onclick="addGoogleAccount()">＋ Добавить аккаунт</button>
      </div>
    `;
    return;
  }

  // Sort: Active account first
  const sorted = [...accounts].sort((a, b) => {
    const aIsActive = a.is_active === true;
    const bIsActive = b.is_active === true;
    return bIsActive - aIsActive;
  });

  container.innerHTML = "";
  sorted.forEach(acc => {
    const isAct = acc.is_active === true;
    const email = acc.email || "unknown@gmail.com";


    // Extract Gemini quotas
    const gemini = (acc.groups || []).find(g => g.name === "gemini") || {};
    const windows = gemini.windows || [];
    const fiveHour = windows.find(w => /5h|5.hour|5ч|short/i.test(String(w.window)));
    const weekly = windows.find(w => /week|7d|нед/i.test(String(w.window)));

    const card = document.createElement("div");
    card.className = `glass-card acc-card ${isAct ? 'is-active' : ''}`;
    if (isAct) {
      card.style.borderColor = "var(--glass-border-amber)";
      card.style.boxShadow = "0 16px 40px rgba(217, 154, 67, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.15)";
    }

    card.innerHTML = `
      <div class="acc-top">
        <div class="acc-identity">
          <div class="acc-avatar">G</div>
          <div>
            <div class="acc-email">${html(email)}</div>
            <div class="acc-role">${isAct ? "Используется сейчас для Google" : "В пуле ротации"}</div>
          </div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="badge-pill ${isAct ? 'badge-available' : 'badge-pool'}">
            <span class="dot"></span> ${isAct ? 'Активен' : 'В пуле'}
          </span>
        </div>
      </div>

      <div class="quotas-box">
        ${quotaMarkup('Gemini · 5 часов', fiveHour, 'green')}
        ${quotaMarkup('Gemini · неделя', weekly, 'amber')}
      </div>

      <div class="acc-footer">
        <div class="acc-actions">
          ${!isAct ? `<button class="btn-primary" style="padding:6px 14px; font-size:11px;" data-action="activate">⭐ Сделать активным</button>` : ''}
          <button class="btn-secondary" style="padding:6px 12px; font-size:11px;" data-action="test">🩺 Проверить</button>
          <button class="btn-secondary" style="padding:6px 10px; font-size:11px; color:var(--accent-red);" data-action="delete">🗑</button>
        </div>
        <label class="switch-label">
          <input type="checkbox" class="switch-input" ${acc.candidate !== false ? 'checked' : ''} data-action="candidate">
          <span>Авторотация</span>
        </label>
      </div>
    `;
    card.querySelector('[data-action="activate"]')?.addEventListener('click', () => activateGoogleAccount(acc.index - 1));
    card.querySelector('[data-action="test"]')?.addEventListener('click', () => testGoogleAccount(acc.id || acc.email));
    card.querySelector('[data-action="delete"]')?.addEventListener('click', () => deleteGoogleAccount(acc.id || acc.email));
    card.querySelector('[data-action="candidate"]')?.addEventListener('change', event => toggleCandidate(acc.id || acc.email, event.target.checked));
    container.appendChild(card);
  });


}

function renderActiveAccounts() {
  const pools = {google:appState.accounts || [], openai:appState.openaiAccounts || [], claude:appState.claudeAccounts || []};
  for (const [tab, accounts] of Object.entries(pools)) {
    const active = accounts.find(account => account.is_active === true);
    const google = tab === 'google';
    const identity = document.getElementById(google ? 'detail-active-email' : `active-account-${tab}`);
    const status = document.getElementById(google ? 'detail-auth-status' : `active-status-${tab}`);
    const count = document.getElementById(google ? 'detail-total-count' : `active-count-${tab}`);
    identity.textContent = active?.email || active?.name || (accounts.length ? 'Активный аккаунт не определён' : 'Нет аккаунтов');
    status.textContent = active ? '● Активен' : accounts.length ? 'Не выбран' : 'Не подключён';
    status.className = `detail-val ${active ? 'status-good' : ''}`;
    count.textContent = String(accounts.length);
  }
  for (const tab of ['xpiki','openrouter']) {
    const cfg = appState.providers?.[tab] || {};
    document.getElementById(`active-account-${tab}`).textContent = cfg.hasKey ? `API-ключ ${cfg.keyLabel || 'сохранён'}` : 'Ключ не задан';
    const status = document.getElementById(`active-status-${tab}`);
    status.textContent = cfg.connected ? '● Подключён' : cfg.hasKey ? 'Ключ сохранён · не подключён' : 'Не подключён';
    status.className = `detail-val ${cfg.connected ? 'status-good' : ''}`;
    document.getElementById(`active-count-${tab}`).textContent = cfg.hasKey ? '1' : '0';
  }
}

// --- OpenAI Tab ---
function renderOpenAiTab() {
  const container = document.getElementById("openai-accounts-container");
  if (!container) return;
  const accs = appState.openaiAccounts || [];
  const refreshButton = document.getElementById('btn-openai-refresh');
  refreshButton.disabled = !!appState.openaiRefreshing;
  refreshButton.textContent = appState.openaiRefreshing ? 'Обновление…' : 'Обновить лимиты';
  document.getElementById('openai-refresh-status').textContent = appState.openaiError || (appState.openaiRefreshing ? 'Запрашиваем лимиты ChatGPT в фоне…' : 'Лимиты обновляются каждые 5 минут.');

  if (accs.length === 0) {
    container.innerHTML = `
      <div class="glass-card" style="text-align: center; padding: 40px;">
        <div style="font-size: 36px; margin-bottom: 12px;">📭</div>
        <div style="font-size: 16px; font-weight: 700; color: #fff;">Нет подключенных аккаунтов ChatGPT</div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-top: 6px; margin-bottom: 20px;">
          Авторизуйтесь через браузер для подключения GPT-4o и моделей OpenAI к OpenCode.
        </div>
        <button class="btn-primary" onclick="addOpenAiAccount()">＋ Добавить ChatGPT</button>
      </div>
    `;
    return;
  }

  const refresh = document.getElementById('btn-openai-refresh');
  refresh.disabled = !!appState.openaiRefreshing;
  refresh.textContent = appState.openaiRefreshing ? 'Обновление…' : 'Обновить лимиты';
  document.getElementById('openai-refresh-status').textContent = appState.openaiError || (appState.openaiRefreshing ? 'Запрашиваем лимиты ChatGPT в фоне…' : 'Лимиты обновляются автоматически каждые 5 минут.');
  container.innerHTML = '';
  accs.forEach(acc => {
    const card = document.createElement('div');
    card.className = `glass-card acc-card ${acc.is_active ? 'is-active' : ''}`;
    const quota = acc.quota || {};
    const valid = quota.status === 'ok' || quota.status === 'stale';
    const primary = quota.window_5h || quota.primary;
    const secondary = quota.window_weekly || quota.secondary;
    const checked = quota.last_checked ? new Date(quota.last_checked * 1000).toLocaleString('ru-RU') : 'ещё не обновлялись';
    card.innerHTML = `<div class="acc-top"><div class="acc-identity"><div class="acc-avatar" style="color:#10a37f">◎</div><div><div class="acc-email">${html(acc.email || 'ChatGPT Session')}</div><div class="acc-role">${html(acc.plan_type || quota.plan_type || 'Тариф неизвестен')}</div></div></div><span class="badge-pill ${acc.is_active ? 'badge-available' : 'badge-pool'}">${acc.is_active ? '● Активен' : 'В пуле'}</span></div><div class="quotas-box">${quotaMarkup('ChatGPT · 5 часов', primary, 'green', valid)}${quotaMarkup('ChatGPT · неделя', secondary, 'amber', valid)}</div><div class="help-text">Проверено: ${html(checked)}${quota.status === 'stale' ? ' · сохранённые данные, обновление не удалось' : quota.status === 'error' ? ' · запрос лимитов не удался' : ''}${quota.limit_reached ? ' · Лимит исчерпан' : ''}</div>`;
    container.appendChild(card);
  });
}

async function refreshOpenAiQuotas() {
  try {
    await window.pywebview.api.refresh_openai_quotas();
    await refreshState();
    setTimeout(refreshState, 2000);
  } catch (e) { showToast(`Ошибка обновления лимитов: ${e}`); }
}

// --- Claude Tab ---
function renderClaudeTab() {
  const container = document.getElementById("claude-accounts-container");
  if (!container) return;
  const accs = appState.claudeAccounts || [];

  if (accs.length === 0) {
    container.innerHTML = `
      <div class="glass-card" style="text-align: center; padding: 40px;">
        <div style="font-size: 36px; margin-bottom: 12px;">📭</div>
        <div style="font-size: 16px; font-weight: 700; color: #fff;">Нет подключенных сессий Claude</div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-top: 6px; margin-bottom: 20px;">
          Выполните вход на claude.ai в открывшемся браузере для связки аккаунта с Hub.
        </div>
        <button class="btn-primary" onclick="addClaudeAccount()">＋ Добавить Claude</button>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  accs.forEach(acc => {
    const card = document.createElement("div");
    card.className = `glass-card acc-card ${acc.is_active ? 'is-active' : ''}`;
    card.innerHTML = `
      <div class="acc-top">
        <div class="acc-identity">
          <div class="acc-avatar" style="color: #d97706;">✦</div>
          <div>
            <div class="acc-email">${html(acc.email || acc.name || "Claude Session")}</div>
            <div class="acc-role">${html(acc.plan || "Claude Pro")}</div>
          </div>
        </div>
        <span class="badge-pill ${acc.is_active ? 'badge-available' : 'badge-pool'}"><span class="dot"></span> ${acc.is_active ? 'Активен' : 'В пуле'}</span>
      </div>
    `;
    container.appendChild(card);
  });
}

let xpikiFormInitialized = false;
let openrouterModels = [];
function renderXpikiTab() {
  const cfg = appState.providers?.xpiki;
  if (!cfg) return;
  const badge = document.getElementById('xpiki-connection-status');
  badge.textContent = cfg.connected ? '● Подключён' : 'Не подключён';
  badge.className = `badge-pill ${cfg.connected ? 'badge-available' : 'badge-pool'}`;
  document.getElementById('xpiki-key').placeholder = cfg.hasKey ? 'Ключ сохранён · оставьте пустым для сохранения' : 'Введите API-ключ';
  if (!xpikiFormInitialized) {
    document.getElementById('xpiki-base-url').value = cfg.baseUrl;
    const picker = document.getElementById('xpiki-models');
    picker.innerHTML = '';
    for (const model of cfg.models || []) {
      const label = document.createElement('label');
      label.className = 'model-choice';
      const input = document.createElement('input');
      input.type = 'checkbox'; input.value = model.id; input.checked = cfg.enabledModels.includes(model.id);
      label.append(input, document.createTextNode(model.name)); picker.appendChild(label);
    }
    xpikiFormInitialized = true;
  }
  const quota = cfg.quota || {};
  const valid = ['ok','stale'].includes(quota.status);
  const amount = value => value == null ? 'Нет данных' : Number(value).toLocaleString('ru-RU');
  document.getElementById('xpiki-quota').innerHTML = `<h2>Квота Xpiki</h2><div class="quota-summary"><div class="help-text">Осталось<strong>${valid ? amount(quota.remaining_tokens) : 'Нет данных'}</strong></div><div class="help-text">Всего токенов<strong>${valid ? amount(quota.quota_limit) : '—'}</strong></div><div class="help-text">Использовано<strong>${valid ? amount(quota.quota_used) : '—'}</strong></div></div><p class="help-text">RPM: ${amount(quota.effective_rpm)} · TPM: ${amount(quota.effective_tpm)}${quota.status === 'stale' ? ' · сохранённые данные' : ''}</p>`;
}

async function configureXpiki() {
  const result = document.getElementById('xpiki-result');
  result.textContent = 'Сохранение…';
  try {
    const models = [...document.querySelectorAll('#xpiki-models input:checked')].map(i=>i.value);
    const response = await window.pywebview.api.configure_xpiki(document.getElementById('xpiki-key').value, document.getElementById('xpiki-base-url').value.trim(), models);
    result.textContent = response.message;
    document.getElementById('xpiki-key').value = '';
    await refreshState();
    await refreshXpikiQuota();
  } catch (e) { result.textContent = String(e); }
}
async function refreshXpikiQuota() {
  const result = document.getElementById('xpiki-result');
  result.textContent = 'Обновление квоты…';
  try {
    const quota = await window.pywebview.api.refresh_xpiki_quota();
    if (appState.providers?.xpiki) appState.providers.xpiki.quota = quota;
    renderXpikiTab();
    result.textContent = quota.status === 'ok' ? 'Квота обновлена' : quota.error || 'Не удалось получить квоту';
  } catch (e) { result.textContent = String(e); }
}
async function disconnectXpiki() {
  if (!confirm('Отключить Xpiki в OpenCode?')) return;
  try { await window.pywebview.api.disconnect_xpiki(); await refreshState(); document.getElementById('xpiki-result').textContent = 'Xpiki отключён'; }
  catch (e) { showToast(String(e)); }
}

function renderOpenRouterState() {
  const cfg = appState.providers?.openrouter;
  if (!cfg) return;
  document.getElementById('openrouter-key-input').placeholder = cfg.hasKey ? 'Ключ сохранён · можно загрузить каталог' : 'sk-or-v1-…';
}
async function loadOpenRouterModels() {
  const output = document.getElementById('openrouter-status-text');
  output.textContent = 'Проверка ключа и загрузка бесплатных моделей…';
  try {
    openrouterModels = await window.pywebview.api.load_openrouter_models(document.getElementById('openrouter-key-input').value);
    document.getElementById('openrouter-key-input').value = '';
    const list = document.getElementById('openrouter-models-list');
    list.innerHTML = '';
    const configured = appState.providers?.openrouter?.selectedModels || [];
    for (const model of openrouterModels) {
      const label = document.createElement('label'); label.className = 'model-choice';
      const input = document.createElement('input'); input.type='checkbox'; input.value=model.id;
      input.checked = configured.length ? configured.includes(model.id) : true;
      label.append(input, document.createTextNode(`${model.name} · ${model.id} · контекст ${model.context.toLocaleString('ru-RU')}`));
      list.appendChild(label);
    }
    document.getElementById('btn-apply-openrouter').disabled = !openrouterModels.length;
    output.textContent = `Ключ проверен. Бесплатных моделей: ${openrouterModels.length}. Выберите нужные и добавьте в OpenCode.`;
    await refreshState();
  } catch (e) { output.textContent = String(e); }
}
async function applyOpenRouterModels() {
  const output = document.getElementById('openrouter-status-text');
  try {
    const ids = [...document.querySelectorAll('#openrouter-models-list input:checked')].map(i=>i.value);
    await window.pywebview.api.apply_openrouter_models(ids);
    output.textContent = `В OpenCode добавлено моделей: ${ids.length}`;
    await refreshState();
  } catch (e) { output.textContent = String(e); }
}
async function disconnectOpenRouter() {
  if (!confirm('Удалить сохранённый ключ OpenRouter из Hub и OpenCode?')) return;
  try {
    await window.pywebview.api.disconnect_openrouter();
    document.getElementById('openrouter-models-list').innerHTML = '';
    document.getElementById('btn-apply-openrouter').disabled = true;
    document.getElementById('openrouter-status-text').textContent = 'OpenRouter отключён';
    await refreshState();
  } catch (e) { showToast(String(e)); }
}

// --- Settings Tab ---
let settingsDirty = false;
function markSettingsDirty() { settingsDirty = true; }
function renderSettingsTab() {
  if (settingsDirty) return;
  const cfg = appState.config || {};
  const strat = cfg.account_selection_strategy || "hybrid";
  selectStrategy(strat, false);

  const swRate = document.getElementById("switch-rate-limit");
  if (swRate) swRate.checked = cfg.switch_on_first_rate_limit !== false;
  for (const item of Object.values(providerSettings)) document.getElementById(`provider-enabled-${item.key}`).checked = cfg.providers_visibility?.[item.key] !== false;
}

function selectStrategy(strat, save = true) {
  ["hybrid", "sticky", "round-robin"].forEach(s => {
    const btn = document.getElementById(`strat-${s}`);
    if (btn) btn.classList.toggle("active", s === strat);
  });

  const descs = {
    hybrid: "⭐ Рекомендуется: сохраняет контекст сессии на одном аккаунте, но плавно ротирует при исчерпании лимитов.",
    sticky: "📌 Последовательная: работает с одним аккаунтом до полного отказа, затем переходит к следующему.",
    "round-robin": "🔄 Равномерная: распределяет каждый новый запрос по очереди между всеми аккаунтами."
  };
  const descEl = document.getElementById("strat-desc");
  if (descEl) descEl.textContent = descs[strat] || "";

  if (save && window.pywebview?.api) {
    window.pywebview.api.set_strategy(strat).then(() => {
      showToast(`Стратегия выбора обновлена: ${strat}`);
    });
  }
}

async function saveSettings() {
  if (!window.pywebview?.api) return;
  const swRate = document.getElementById("switch-rate-limit");
  try {
    const visibility = Object.fromEntries(Object.values(providerSettings).map(item=>[item.key, document.getElementById(`provider-enabled-${item.key}`).checked]));
    const ok = await window.pywebview.api.save_general_settings({
      switch_on_first_rate_limit: swRate ? swRate.checked : true, providers_visibility:visibility
    });
    if (!ok) throw new Error('Не удалось сохранить настройки');
    settingsDirty = false;
    await refreshState();
    document.getElementById('provider-settings-result').textContent = 'Настройки провайдеров сохранены. Для обновления выбора моделей в OpenCode может потребоваться его перезапуск.';
    showToast("Настройки успешно сохранены");
  } catch (e) {
    showToast(`Ошибка сохранения: ${e}`);
  }
}

// --- OpenCode system actions ---
async function restartOpenCode() {
  if (!window.pywebview?.api) return;
  showToast("Перезапуск OpenCode...");
  await window.pywebview.api.restart_opencode();
  setTimeout(refreshState, 1500);
}

async function stopOpenCode() {
  if (!window.pywebview?.api) return;
  showToast("Остановка OpenCode...");
  await window.pywebview.api.stop_opencode();
  setTimeout(refreshState, 1500);
}

async function startOpenCode() {
  if (!window.pywebview?.api) return;
  showToast("Запуск OpenCode...");
  await window.pywebview.api.start_opencode();
  setTimeout(refreshState, 1500);
}

async function fixSessionTitle() {
  if (!window.pywebview?.api) return;
  showToast("Проверка подписи сессий opencode/big-pickle...");
  const res = await window.pywebview.api.fix_session_title();
  showToast(res || "Настройка проверена");
}

async function openFolder(type) {
  if (!window.pywebview?.api) return;
  await window.pywebview.api.open_folder(type);
}

// --- Account Actions ---
async function addGoogleAccount() {
  if (!window.pywebview?.api) return;
  showToast("Открытие браузера для входа в Google...");
  const res = await window.pywebview.api.add_google_account();
  showToast(res.message || "Готово");
  refreshState();
}

async function activateGoogleAccount(idx) {
  if (!window.pywebview?.api) return;
  try {
    const ok = await window.pywebview.api.activate_google_account(idx);
    if (!ok) throw new Error('Не удалось сохранить выбор');
    await refreshState();
    showToast('Активный Google-аккаунт переключён');
  } catch (e) { showToast(`Ошибка переключения: ${e}`); }
}

async function deleteGoogleAccount(id) {
  if (!confirm("Удалить этот Google аккаунт из пула?")) return;
  if (!window.pywebview?.api) return;
  await window.pywebview.api.delete_google_account(id);
  showToast("Аккаунт удален");
  refreshState();
}

async function testGoogleAccount(id) {
  if (!window.pywebview?.api) return;
  showToast("Тестирование токена и квот...");
  const res = await window.pywebview.api.test_google_account(id);
  showToast(res || "Аккаунт активен и отвечает");
}

async function toggleCandidate(id, enabled) {
  if (!window.pywebview?.api) return;
  await window.pywebview.api.toggle_google_candidate(id, enabled);
  showToast(`Авторотация ${enabled ? "включена" : "отключена"}`);
}

async function addOpenAiAccount() {
  if (!window.pywebview?.api) return;
  showToast("Запуск браузера для входа ChatGPT...");
  await window.pywebview.api.add_openai_account();
  refreshState();
}

async function addClaudeAccount() {
  if (!window.pywebview?.api) return;
  showToast("Запуск браузера для входа Claude...");
  await window.pywebview.api.add_claude_account();
  refreshState();
}

async function checkUpdates() {
  if (!window.pywebview?.api) return;
  showToast("Проверка обновлений с GitHub...");
  const res = await window.pywebview.api.check_updates();
  showToast(res || "У вас актуальная версия");
}

// ============================================================================
// INITIALIZATION
// ============================================================================
window.addEventListener('pywebviewready', () => {
  console.log("PyWebView bridge ready");
  document.getElementById('network-settings').addEventListener('input', () => { networkDirty = true; renderDnsStatus(); });
  document.getElementById('network-proxy').addEventListener('input', () => { networkDirty = true; });
  document.getElementById('google-smart-doh').addEventListener('input', () => { networkDirty = true; });
  refreshState();
  // Auto refresh loop every 10 seconds
  setInterval(refreshState, 10000);
});
