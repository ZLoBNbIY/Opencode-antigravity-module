import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../gui-manager/web/app.js', import.meta.url), 'utf8');
const markup = fs.readFileSync(new URL('../gui-manager/web/index.html', import.meta.url), 'utf8');

function frontend(state) {
  class Element {
    constructor() { this.children = []; this.style = {}; this.value = ''; this.dataset = {}; this.attributes = {}; this.classes = new Set(); this.classList = {toggle:(name, value) => value ? this.classes.add(name) : this.classes.delete(name)}; }
    set innerHTML(value) { this.content = value; this.children = []; }
    get innerHTML() { return this.content || ''; }
    appendChild(child) { this.children.push(child); }
    append(...children) { this.children.push(...children); }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener() {}
    querySelector() { return null; }
    closest() { return null; }
  }
  const elements = new Map([...markup.matchAll(/id="([^"]+)"/g)].map(m => {const el = new Element(); el.id = m[1]; return [m[1], el];}));
  const nav = [...markup.matchAll(/class="nav-item[^\"]*" data-tab="([^"]+)"/g)].map(m=>{ const el = new Element(); el.dataset.tab=m[1]; return el; });
  const cards = [...markup.matchAll(/data-provider-card="([^"]+)"/g)].map(m=>{ const el = new Element(); el.dataset.providerCard=m[1]; return el; });
  const context = vm.createContext({
    document: {getElementById: id => elements.get(id) || null,
      createElement: () => new Element(), createTextNode: value => ({textContent: value}),
      querySelectorAll: selector => selector === '.nav-item' ? nav : selector === '[data-provider-card]' ? cards : selector === '.view-tab' ? [...elements.values()].filter(el=>el.id.startsWith('view-')) : []},
    window: {addEventListener() {}}, console, URL, setTimeout() { return 1; }, clearTimeout() {}, setInterval() {}, confirm: () => false,
  });
  vm.runInContext(source, context);
  vm.runInContext(`appState = ${JSON.stringify(state)}; renderAll();`, context);
  return {elements, context, nav, cards};
}

const state = {
  accounts: [{id:'google-active', index:3, email:'active@example.com', is_active:true, groups:[]},
    {id:'google-idle', index:1, email:'idle@example.com', is_active:false, groups:[]}],
  activeIndex:2, config:{dns_mode:'standard',custom_dns:['1.1.1.1','1.0.0.1']},
  routes:{google:'dns'}, network:{cores:{'sing-box':{installed:true,selected:true,path:'sing-box.exe'},xray:{installed:false}},vlessCore:'sing-box.exe'},
  openaiAccounts:[{email:'chat@example.com',is_active:true,plan_type:'plus',quota:{status:'ok',primary:{remaining_percent:0},secondary:{remaining_percent:42}}}],
  claudeAccounts:[], diagnostics:{openai:{rows:[{domain:'chatgpt.com',status:'error',latency_ms:null,error:'TimeoutError'}]}},
  providers:{xpiki:{models:[{id:'claude-test',name:'Claude Test'}],enabledModels:['claude-test'],quota:{},baseUrl:'https://api.xpiki.com/v1'},openrouter:{hasKey:true},
    deepseek:{connected:false,hasKey:false,keyLabel:null,baseUrl:'https://api.deepseek.com',balance:{status:'no_key'}},
    tokenlavka:{hasKey:false,connected:false,selectedModels:[],models:[{id:'gpt-6-luna',name:'GPT-6 Luna',context:512000,output:65536}],baseUrl:'https://tokenlavka.com/v1',
      balance:{status:'ok',issued:1000,spent:600,balance:400,reserved:0,remaining_percent:40,used_percent:60,checked_at:1794309000,error:null}}},
};

test('network markup escapes diagnostic values and omits saved connection secrets', () => {
  const fixture = structuredClone(state);
  const bad = '<img src=x onerror=alert(1)>';
  fixture.config.proxy = 'http://private-user:private-password@proxy.example:8080';
  fixture.config.vless_url = 'opaque-id';
  fixture.config.vless_pool = [{id:'opaque-id', url:'vless://private-value@host:443',
    label:'Saved node', status:'ok', latency_ms:bad}];
  fixture.network.autoRoutes = {google:{selected:'vless', status:'ready',
    rows:[{mode:'vless', available:true, passed:bad, total:2, latency_ms:bad}]}};
  const {elements} = frontend(fixture);
  const vless = elements.get('vless-pool-container').children[0].innerHTML;
  const proxy = elements.get('proxy-pool-container').children[0].innerHTML;
  const automatic = [...elements.values()].flatMap(el => el.children).map(el => el.innerHTML).join('');
  assert.match(vless, /&lt;img/);
  assert.doesNotMatch(vless, /<img|private-value/);
  assert.match(proxy, /proxy.example:8080/);
  assert.doesNotMatch(proxy, /private-user|private-password/);
  assert.match(automatic, /&lt;img.*\/2/);
  assert.doesNotMatch(automatic, /<img src=x/);
});

test('backup export uses a masked input and passes only the password to the bridge', async () => {
  const {context} = frontend(state);
  assert.match(markup, /id="backup-password" type="password" required/);
  const calls = [];
  context.window.pywebview = {api:{export_backup:async (...args) => {
    calls.push(args);
    return {ok:false, cancelled:true};
  }}};
  await vm.runInContext(`requestBackupPassword = async () => null; exportBackup()`, context);
  assert.deepEqual(calls, []);
  await vm.runInContext(`requestBackupPassword = async () => 'test-password'; exportBackup()`, context);
  assert.deepEqual(calls, [['test-password']]);
});

test('all account tabs render with active identity and real zero ChatGPT quota', () => {
  const {elements} = frontend(state);
  const google = elements.get('google-accounts-list').children;
  assert.match(google[0].innerHTML, /Используется сейчас/);
  assert.doesNotMatch(google[0].innerHTML, /data-action="activate"/);
  assert.match(google[1].innerHTML, /data-action="activate"/);
  assert.equal(elements.get('detail-active-email').textContent, 'active@example.com');
  const chat = elements.get('openai-accounts-container').children[0].innerHTML;
  assert.match(chat, /0% осталось/);
  assert.match(chat, /42% осталось/);
  const coreButtons = elements.get('vless-core-row').children;
  assert.equal(coreButtons.length, 2);
  assert.match(coreButtons[0].className, /active/);
  assert.doesNotMatch(coreButtons[1].className, /active/);
});

test('failed domains show error indicators and no invented milliseconds', () => {
  const {elements} = frontend(state);
  const row = elements.get('diag-tbody-openai').children[0].innerHTML;
  assert.match(row, /connection-indicator error/);
  assert.match(row, /TimeoutError/);
  assert.doesNotMatch(row, /\d+ мс/);
  assert.equal(elements.get('diag-tbody-google').children.length, 8);
  assert.equal(elements.get('diag-tbody-claude').children.length, 3);
  assert.equal(elements.get('diag-tbody-xpiki').children.length, 1);
  assert.equal(elements.get('diag-tbody-deepseek').children.length, 1);
  assert.equal(elements.get('diag-tbody-openrouter').children.length, 1);
  assert.equal(elements.get('diag-tbody-tokenlavka').children.length, 1);
  assert.equal(elements.get('seg-group-deepseek').children.length, 5);
  assert.equal(elements.get('seg-group-tokenlavka').children.length, 5);
  assert.equal((elements.get('tokenlavka-models-list').innerHTML.match(/<label class="model-card\b/g) || []).length, 1);
  assert.match(elements.get('vless-active-summary').textContent, /не выбран/);
  assert.match(elements.get('tokenlavka-balance').innerHTML, /40%/);
  assert.match(elements.get('tokenlavka-balance').innerHTML, /progress-fill-emerald/);
});

test('Dashboard VLESS displays the exit country and address, not the core or config', () => {
  const fixture = structuredClone(state);
  Object.assign(fixture.network, {vlessRunning:true, vlessCore:'xray.exe',
    vlessExit:{status:'ok', country:'DE', ip:'8.8.8.8'}});
  const {elements, context} = frontend(fixture);
  const network = elements.get('dashboard-network');
  assert.match(network.innerHTML, /Германия · 8\.8\.8\.8/);
  assert.doesNotMatch(network.innerHTML, /xray\.exe|Активный конфиг/);
  vm.runInContext('appState.network.vlessRunning = false; renderDashboard()', context);
  assert.match(network.innerHTML, /Нет активного подключения/);
  assert.doesNotMatch(network.innerHTML, /8\.8\.8\.8/);
});

test('standalone Qwen provider is not registered or shown', () => {
  const {context, nav, elements} = frontend(state);
  assert.equal(vm.runInContext("Object.values(providerTabs).includes('qwen-code')", context), false);
  assert.equal(nav.some(item => item.dataset.tab === 'qwen'), false);
  assert.equal(elements.has('view-qwen'), false);
});

test('polling preserves edited DNS inputs and unknown quota stays unknown', () => {
  const fixture = structuredClone(state);
  fixture.openaiAccounts[0].quota = {status:'error'};
  const {elements, context} = frontend(fixture);
  elements.get('dns-primary').value = '9.9.9.9';
  vm.runInContext('renderAll()', context);
  assert.equal(elements.get('dns-primary').value, '9.9.9.9');
  const chat = elements.get('openai-accounts-container').children[0].innerHTML;
  assert.match(chat, /Нет данных/);
  assert.doesNotMatch(chat, /100%/);
  assert.equal(elements.has('vless-http-port'), false);
  assert.equal(elements.has('vless-socks-port'), false);
});

test('DoH and DoT are explicit choices with the matching address fields', () => {
  const {elements, context} = frontend(state);
  vm.runInContext("selectDnsMode('doh')", context);
  assert.equal(elements.get('dns-mode').value, 'doh');
  assert.equal(elements.get('dns-doh-fields').style.display, 'block');
  assert.equal(elements.get('dns-standard-fields').style.display, 'none');
  assert.equal(elements.get('dns-mode-doh').attributes['aria-checked'], 'true');
  assert.match(elements.get('dns-selection-summary').textContent, /Применить DNS/);
  vm.runInContext("selectDnsMode('dot')", context);
  assert.equal(elements.get('dns-dot-fields').style.display, 'block');
  assert.equal(elements.get('dns-doh-fields').style.display, 'none');
});

test('DNS badges distinguish primary success and secondary failure, and invalidate edited addresses', async () => {
  const {elements, context} = frontend(state);
  const requested = [];
  context.window.pywebview = {api:{test_dns:async (mode, value) => {
    requested.push([mode, value]);
    return {ok:value === '1.1.1.1', latency_ms:35, message:'test DNS response'};
  }}};
  await vm.runInContext('testDns()', context);
  assert.deepEqual(requested, [['standard','1.1.1.1'],['standard','1.0.0.1']]);
  assert.match(elements.get('dns-primary-status').textContent, /Доступен.*35 мс/);
  assert.match(elements.get('dns-secondary-status').textContent, /Недоступен/);
  assert.match(elements.get('dns-status').className, /badge-error/);
  elements.get('dns-primary').value = '9.9.9.9';
  vm.runInContext('renderDnsStatus()', context);
  assert.match(elements.get('dns-primary-status').textContent, /Не проверен/);
});

test('disabled providers disappear from navigation and route cards', () => {
  const fixture = structuredClone(state);
  fixture.config.providers_visibility = {openai:false, xpiki:false};
  const {elements, context, nav, cards} = frontend(fixture);
  assert.equal(nav.find(el=>el.dataset.tab === 'openai').style.display, 'none');
  assert.equal(cards.find(el=>el.dataset.providerCard === 'xpiki').style.display, 'none');
  assert.equal(elements.get('provider-enabled-openai').checked, false);
  vm.runInContext("switchTab('openai')", context);
  assert.equal(elements.get('view-dashboard').style.display, 'block');
  elements.get('provider-enabled-openai').checked = true;
  vm.runInContext('markSettingsDirty(); renderAll()', context);
  assert.equal(elements.get('provider-enabled-openai').checked, true);
});

test('automatic routes name the effective transport and manual DNS explains its server', () => {
  const fixture = structuredClone(state);
  fixture.network.autoRoutes = {
    google:{selected:'vless',status:'ready',rows:[{mode:'vless',available:true,passed:2,total:2,latency_ms:20}]},
    openai:{selected:'dns',status:'ready',rows:[{mode:'dns',available:true,passed:1,total:1,latency_ms:10}]},
  };
  fixture.network.vlessRunning = true;
  const {elements} = frontend(fixture);
  assert.equal(elements.get('seg-group-google').children[0].textContent, 'Авто → VLESS');
  assert.match(elements.get('card-route-google').textContent, /Используется: DNS Hub.*Обычный DNS.*1\.1\.1\.1/);
  assert.equal(elements.get('seg-group-openai').children[0].textContent, 'Авто → DNS Hub');
  assert.match(elements.get('card-route-openai').textContent, /Auto выбрал: DNS Hub.*HTTPS 10 мс/);
  assert.doesNotMatch(elements.get('card-route-openai').textContent, /По настройкам Hub/);
});

test('service cards show labeled green, amber and red domain summaries', () => {
  const fixture = structuredClone(state);
  fixture.diagnostics.google = {rows:[{domain:'one.test',status:'ok'},{domain:'two.test',status:'error'}]};
  fixture.diagnostics.xpiki = {rows:[{domain:'api.xpiki.com',status:'ok'}]};
  const {elements} = frontend(fixture);
  assert.match(elements.get('provider-status-google').className, /badge-checking/);
  assert.match(elements.get('provider-status-google').innerHTML, /connection-indicator warning.*Домены: 1\/2/);
  assert.match(elements.get('provider-status-openai').innerHTML, /Нет соединения/);
  assert.match(elements.get('provider-status-xpiki').className, /badge-available/);
  assert.match(elements.get('provider-status-xpiki').innerHTML, /Домены: 1\/1/);
});

test('automatic checks run for enabled providers, are throttled, and refresh after route changes', async () => {
  const fixture = structuredClone(state);
  fixture.config.providers_visibility = {antigravity:true,openai:true,claude:false,xpiki:false,deepseek:false,openrouter:false,tokenlavka:false,nvidia:false};
  const {context} = frontend(fixture);
  const calls = [];
  context.window.pywebview = {api:{run_provider_diagnostics:async provider => {
    calls.push(provider);
    return [{domain:'example.test',status:'ok',latency_ms:1}];
  }}};
  await vm.runInContext('refreshEnabledDiagnostics()', context);
  assert.deepEqual(calls.sort(), ['google','openai']);
  await vm.runInContext('refreshEnabledDiagnostics()', context);
  assert.equal(calls.length, 2);
  await vm.runInContext("appState.routes.google='direct'; refreshEnabledDiagnostics()", context);
  assert.equal(calls.length, 4);
  await vm.runInContext("diagnosticAttempts.get('google').time -= 61000; refreshEnabledDiagnostics()", context);
  assert.equal(calls.length, 5);
});

test('DeepSeek tab shows real balance and does not invent numbers on error', () => {
  const fixture = structuredClone(state);
  fixture.providers.deepseek = {
    connected:true, hasKey:true, keyLabel:'sk-••••9abc', baseUrl:'https://api.deepseek.com',
    balance:{status:'ok',is_available:true,currency:'CNY',total_balance:110.5,granted_balance:10,topped_up_balance:100.5,checked_at:1794309000},
  };
  const {elements} = frontend(fixture);
  const card = elements.get('deepseek-balance').innerHTML;
  assert.match(card, /110,5 CNY/);
  assert.match(card, /Доступен/);
  assert.match(card, /dashboard-tone-ok/);
  assert.equal(elements.get('deepseek-connection-status').textContent, '● Подключён');
  assert.equal(elements.get('active-account-deepseek').textContent, 'API-ключ sk-••••9abc');
  assert.equal(elements.get('active-status-deepseek').textContent, '● Подключён');
  assert.match(elements.get('active-count-deepseek').textContent, /110,5 CNY/);

  fixture.providers.deepseek.balance = {status:'error',error:'HTTP 401'};
  const {elements: errorElements} = frontend(fixture);
  const errorCard = errorElements.get('deepseek-balance').innerHTML;
  assert.match(errorCard, /Нет данных/);
  assert.doesNotMatch(errorCard, /110,5/);
  assert.match(errorCard, /HTTP 401/);

  fixture.providers.deepseek.balance = {status:'ok',is_available:false,currency:'CNY',total_balance:0,granted_balance:0,topped_up_balance:0};
  const {elements: unavailableElements} = frontend(fixture);
  assert.match(unavailableElements.get('deepseek-balance').innerHTML, /Недоступен/);
  assert.match(unavailableElements.get('deepseek-balance').innerHTML, /dashboard-tone-error/);

  fixture.providers.deepseek.balance = {
    status:'ok', is_available:true, currency:'CNY', total_balance:110.5,
    granted_balance:0, topped_up_balance:110.5,
    balances:[{currency:'CNY',total_balance:110.5,granted_balance:0,topped_up_balance:110.5},
      {currency:'USD',total_balance:5,granted_balance:0,topped_up_balance:5}],
  };
  const {elements: multiElements} = frontend(fixture);
  assert.match(multiElements.get('deepseek-balance').innerHTML, /Также на счету: 5 USD/);
});

test('DeepSeek tab charts real OpenCode money and token usage', () => {
  const fixture = structuredClone(state);
  fixture.providers.deepseek = {
    connected:true, hasKey:true, keyLabel:'sk-••••9abc', baseUrl:'https://api.deepseek.com',
    balance:{status:'ok',is_available:true,currency:'CNY',total_balance:110.5,granted_balance:10,topped_up_balance:100.5,checked_at:1794309000},
    usage:{status:'ok',source:'OpenCode',currency:'CNY',pricing:'DeepSeek official tariff',window_days:30,checked_at:1794309000,
      days:[
        {date:'2026-11-16',cost:0.159097,cost_usd:0.023865,tokens_total:2192941,tokens_input:58950,tokens_output:8942,tokens_reasoning:5497,tokens_cache_read:2119552,messages:52,unpriced_messages:0},
        {date:'2026-11-17',cost:3.750892,cost_usd:0.574445,tokens_total:100567460,tokens_input:768423,tokens_output:114892,tokens_reasoning:152753,tokens_cache_read:99531392,messages:421,unpriced_messages:0},
      ],
      totals:{cost:3.909989,cost_usd:0.59831,tokens_total:102760401,messages:473,unpriced_messages:0}},
  };
  const {elements, context} = frontend(fixture);
  const card = elements.get('deepseek-usage').innerHTML;
  assert.match(card, /Расход токенов и денег/);
  assert.match(card, /usage-bar-money/);
  assert.match(card, /usage-bar-tokens/);
  assert.match(card, /3,91 CNY/);
  assert.match(card, /млн/);
  assert.match(card, /официальному тарифу DeepSeek в CNY/);
  assert.doesNotMatch(card, /\$0,57/);
  assert.match(card, /14 дн\./);

  vm.runInContext('setDeepseekUsagePeriod(7)', context);
  assert.match(elements.get('deepseek-usage').innerHTML, /class="seg-btn active"[^>]*>7 дн\./);

  fixture.providers.deepseek.usage = {status:'unavailable', error:'Локальная база OpenCode не найдена'};
  const {elements: missingElements} = frontend(fixture);
  assert.match(missingElements.get('deepseek-usage').innerHTML, /Локальная база OpenCode не найдена/);
  assert.doesNotMatch(missingElements.get('deepseek-usage').innerHTML, /usage-bar-money/);
});

test('each provider sidebar shows the actual active profile or masked API key', () => {
  const fixture = structuredClone(state);
  fixture.claudeAccounts = [{email:'idle@claude.test',is_active:false},{email:'active@claude.test',is_active:true}];
  fixture.providers.xpiki = {...fixture.providers.xpiki, connected:true, hasKey:true, keyLabel:'••••1234'};
  fixture.providers.openrouter = {connected:true,hasKey:true,keyLabel:'••••5678'};
  const {elements, context} = frontend(fixture);
  assert.equal(elements.get('detail-active-email').textContent, 'active@example.com');
  assert.equal(elements.get('active-account-openai').textContent, 'chat@example.com');
  assert.equal(elements.get('active-account-claude').textContent, 'active@claude.test');
  assert.equal(elements.get('active-count-claude').textContent, '2');
  assert.equal(elements.get('active-account-xpiki').textContent, 'API-ключ ••••1234');
  assert.equal(elements.get('active-account-openrouter').textContent, 'API-ключ ••••5678');
  vm.runInContext('appState.accounts=[]; appState.openaiAccounts=[]; renderAll()', context);
  assert.equal(elements.get('detail-active-email').textContent, 'Нет аккаунтов');
  assert.equal(elements.get('active-account-openai').textContent, 'Нет аккаунтов');
});

test('DNS checks start after loading state, share pending requests, and refresh only expired addresses', async () => {
  const fixture = structuredClone(state);
  fixture.config.providers_visibility = {antigravity:false,openai:false,claude:false,xpiki:false,deepseek:false,openrouter:false,tokenlavka:false,nvidia:false};
  const {elements, context} = frontend(fixture);
  const calls = [];
  context.window.pywebview = {api:{get_state:async ()=>fixture, test_dns:async (mode,value) => {
    calls.push([mode,value]); return {ok:true,latency_ms:12,message:'available'};
  }}};
  await vm.runInContext('refreshState()', context);
  await vm.runInContext('refreshDnsChecks()', context);
  assert.deepEqual(calls, [['standard','1.1.1.1'],['standard','1.0.0.1']]);
  assert.match(elements.get('dns-status').textContent, /DNS доступен/);
  await vm.runInContext('refreshDnsChecks()', context);
  assert.equal(calls.length, 2);
  await vm.runInContext("dnsChecks.get('standard:1.1.1.1').checkedAt -= 61000; refreshDnsChecks()", context);
  assert.equal(calls.length, 3);
  assert.equal(calls[2][1], '1.1.1.1');
});

test('changing DNS mode schedules a debounced check without needing the check button', async () => {
  const {elements, context} = frontend(state);
  const timers = new Map();
  let nextId = 0;
  context.setTimeout = callback => { const id=++nextId; timers.set(id,callback); return id; };
  context.clearTimeout = id => timers.delete(id);
  const calls = [];
  context.window.pywebview = {api:{test_dns:async (mode,value)=>{ calls.push([mode,value]); return {ok:true,message:'available'}; }}};
  vm.runInContext("selectDnsMode('doh')", context);
  elements.get('dns-doh').value='https://resolver.test/dns-query';
  vm.runInContext('onDnsInput(); onDnsInput()', context);
  assert.equal(timers.size, 1);
  for (const callback of timers.values()) callback();
  await vm.runInContext('refreshDnsChecks()', context);
  assert.deepEqual(calls, [['doh','https://resolver.test/dns-query']]);
  assert.match(elements.get('dns-doh-status').textContent, /Доступен/);
});

test('synchronous DNS bridge errors do not leave a permanent pending request', async () => {
  const {context} = frontend(state);
  context.window.pywebview = {api:{test_dns:()=>{ throw new Error('bridge error'); }}};
  await vm.runInContext('refreshDnsChecks()', context);
  assert.equal(vm.runInContext('dnsPending.size', context), 0);
  assert.equal(vm.runInContext("dnsChecks.get('standard:1.1.1.1').state", context), 'error');
});

test('Dashboard summarizes enabled providers and preserves real zero and unknown quotas', () => {
  const fixture = structuredClone(state);
  fixture.config.providers_visibility = {antigravity:true,openai:true,claude:false,xpiki:false,deepseek:false,openrouter:false,tokenlavka:false,nvidia:false};
  const {elements} = frontend(fixture);
  const cards = elements.get('dashboard-providers').children;
  assert.equal(cards.length, 2);
  assert.match(elements.get('dashboard-metrics').innerHTML, /2 \/ 2/);
  assert.match(elements.get('dashboard-metrics').innerHTML, />3<\/strong>/);
  assert.match(cards[0].innerHTML, /active@example.com/);
  assert.match(cards[0].innerHTML, /Нет данных/);
  assert.doesNotMatch(cards[0].innerHTML, /100%/);
  assert.match(cards[1].innerHTML, /chat@example.com/);
  assert.match(cards[1].innerHTML, /dashboard-tone-error">0%/);
  assert.match(cards[1].innerHTML, /42%/);
  assert.match(elements.get('dashboard-attention').children[0].innerHTML, /лимит исчерпан/);
});

test('Dashboard uses saved DNS status and hides proxy credentials', async () => {
  const fixture = structuredClone(state);
  fixture.config.proxy = 'http://private-user:private-password@proxy.example:8080';
  const {elements, context} = frontend(fixture);
  context.window.pywebview = {api:{test_dns:async () => ({ok:true,message:'available'})}};
  await vm.runInContext('refreshDnsChecks()', context);
  const network = elements.get('dashboard-network').innerHTML;
  assert.match(network, /proxy.example:8080/);
  assert.doesNotMatch(network, /private-user|private-password/);
  assert.match(network, /badge-available.*Доступен/);
  elements.get('dns-primary').value = '9.9.9.9';
  vm.runInContext('renderDnsStatus()', context);
  assert.match(elements.get('dashboard-network').innerHTML, /1\.1\.1\.1, 1\.0\.0\.1/);
  assert.doesNotMatch(elements.get('dashboard-network').innerHTML, /9\.9\.9\.9/);
});

test('Dashboard handles all providers disabled and navigation places Network above Diagnostics', () => {
  const fixture = structuredClone(state);
  fixture.config.providers_visibility = {antigravity:false,openai:false,claude:false,xpiki:false,deepseek:false,openrouter:false,tokenlavka:false,nvidia:false};
  const {elements, nav, context} = frontend(fixture);
  assert.equal(vm.runInContext('activeTab', context), 'dashboard');
  assert.equal(nav[0].dataset.tab, 'dashboard');
  assert.equal(nav[nav.findIndex(item=>item.dataset.tab === 'network')+1].dataset.tab, 'diagnostics');
  assert.match(markup, /id="view-dashboard" class="view-tab active"/);
  assert.match(elements.get('dashboard-providers').innerHTML, /Провайдеры выключены/);
  assert.match(elements.get('dashboard-metrics').innerHTML, /0 \/ 0/);
  assert.equal(elements.get('dashboard-check').disabled, true);
});


test('ChatGPT login waits for completion, suppresses double clicks, and shows failure', async () => {
  const {elements, context} = frontend(state);
  let finish;
  let calls = 0;
  context.window.pywebview = {api: {add_openai_account: () => {
    calls++;
    return new Promise(resolve => { finish = resolve; });
  }}};
  vm.runInContext('refreshState = async () => {};', context);
  const pending = vm.runInContext('addOpenAiAccount()', context);
  await vm.runInContext('addOpenAiAccount()', context);
  assert.equal(calls, 1);
  finish({status:'error', message:'token exchange failed'});
  await pending;
  assert.match(elements.get('toasts').children.at(-1).textContent, /Ошибка входа: token exchange failed/);
});

test('Google login refreshes accounts only after successful completion', async () => {
  const {elements, context} = frontend(state);
  let finish;
  let refreshed = 0;
  context.window.pywebview = {api: {add_google_account: () => new Promise(resolve => { finish = resolve; })}};
  context.onRefresh = () => { refreshed++; };
  vm.runInContext('refreshState = async () => onRefresh();', context);
  const pending = vm.runInContext('addGoogleAccount()', context);
  assert.equal(refreshed, 0);
  finish({status:'ok', message:'Google аккаунт добавлен в пул'});
  await pending;
  assert.equal(refreshed, 1);
  assert.match(elements.get('toasts').children.at(-1).textContent, /добавлен/);
});

test('Google account patch disclaimer follows live OpenCode patch status', async () => {
  const {elements, context} = frontend(state);
  vm.runInContext('refreshState = async () => {};', context);
  let pluginState = 'pending';
  let patchState = 'patched';
  context.window.pywebview = {api:{
    get_opencode_plugin_status: async () => ({state:pluginState}),
    get_antigravity_patch_status: async () => ({state:patchState}),
    add_google_account: async () => ({status:'ok', message:'Google аккаунт добавлен в пул'}),
  }};
  const disclaimer = elements.get('google-patch-disclaimer');
  const toasts = elements.get('toasts');

  await vm.runInContext('refreshGooglePatchDisclaimer()', context);
  assert.equal(disclaimer.style.display, '', 'disclaimer is shown when a patch is pending');
  await vm.runInContext('addGoogleAccount()', context);
  assert.match(toasts.children.at(-1).textContent, /Патчи OpenCode не активны/);

  pluginState = 'patched';
  patchState = 'patched';
  toasts.children.length = 0;
  await vm.runInContext('addGoogleAccount()', context);
  assert.equal(disclaimer.style.display, 'none', 'disclaimer is hidden when patches are active');
  assert.equal(toasts.children.length, 2, 'no extra disclaimer toast when patches work');
  assert.match(toasts.children.at(-1).textContent, /добавлен/);
  assert.doesNotMatch(toasts.children.map(t => t.textContent).join(' '), /Патчи OpenCode не активны/);
});

test('accent theme selection applies swatches and persists the choice', async () => {
  const {context} = frontend(state);
  let saved = null;
  context.window.pywebview = {api:{save_general_settings: async settings => { saved = settings; return true; }}};
  const swatches = ['amber', 'azure', 'violet', 'rose', 'crimson', 'cyan', 'indigo', 'mango', 'magenta', 'gray'].map(theme => {
    const el = context.document.createElement('button');
    el.dataset.theme = theme;
    return el;
  });
  context.document.querySelectorAll = selector => selector === '.theme-swatch' ? swatches : [];

  await vm.runInContext("selectAccentTheme('azure')", context);
  assert.equal(saved.accent_theme, 'azure');
  assert.equal(vm.runInContext('appState.config.accent_theme', context), 'azure');
  const azure = swatches.find(el => el.dataset.theme === 'azure');
  assert.equal(azure.classes.has('active'), true);
  assert.equal(azure.attributes['aria-pressed'], 'true');
  assert.equal(swatches[0].classes.has('active'), false);
  assert.equal(swatches.length, 10, 'green theme removed, nine alternatives available');
});

test('OpenCode restart button is placed in sidebar above status indicator and removed from settings', () => {
  const footerMatch = markup.match(/<div class="sidebar-footer">([\s\S]*?)<\/div>\s*<\/aside>/);
  assert.ok(footerMatch, 'sidebar-footer should exist');
  const footerHtml = footerMatch[1];
  const restartIdx = footerHtml.indexOf('id="btn-restart-opencode"');
  const statusIdx = footerHtml.indexOf('id="sidebar-opencode-status"');
  assert.ok(restartIdx !== -1, 'restart button should be in sidebar-footer');
  assert.ok(statusIdx !== -1, 'status indicator should be in sidebar-footer');
  assert.ok(restartIdx < statusIdx, 'restart button should appear above status indicator');

  const settingsMatch = markup.match(/<section id="view-settings"[\s\S]*?<\/section>/);
  assert.ok(settingsMatch, 'view-settings should exist');
  assert.doesNotMatch(settingsMatch[0], /onclick="restartOpenCode\(\)"/);
});

test('DeepSeek usage chart escapes currency in innerHTML and failover toggle marks networkDirty', () => {
  const fixture = structuredClone(state);
  fixture.providers.deepseek.usage = {
    status: 'ok',
    currency: '<img src=x onerror=alert(1)>',
    source: 'OpenCode',
    days: [{date: '2026-11-17', cost: 1.5, cost_usd: 0.2, tokens_total: 1000, tokens_input: 500, tokens_cache_read: 0, tokens_output: 500, tokens_reasoning: 0, messages: 1}],
  };
  const {elements} = frontend(fixture);
  const usageHtml = elements.get('deepseek-usage').innerHTML;
  assert.doesNotMatch(usageHtml, /<img src=x/);
  assert.match(usageHtml, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(markup, /id="switch-proxy-failover"[^>]*onchange="networkDirty = true"/);
  const css = fs.readFileSync(new URL('../gui-manager/web/style.css', import.meta.url), 'utf8');
  const statusBadgeRule = css.match(/\.status-badge\s*\{[^}]*\}/);
  assert.ok(statusBadgeRule && /justify-content:\s*center/.test(statusBadgeRule[0]), '.status-badge should center its content');
});

test('Dashboard has Restart Hub button wired to restart_hub API', async () => {
  assert.match(markup, /<section id="view-dashboard"[\s\S]*id="btn-restart-hub"[^>]*onclick="restartHub\(\)"/);
  const {elements, context} = frontend(state);
  let called = 0;
  context.window.pywebview = {api: {restart_hub: async () => { called++; return {ok: true, message: 'restarting'}; }}};
  await vm.runInContext('restartHub()', context);
  assert.equal(called, 1);
  assert.equal(elements.get('btn-restart-hub').disabled, true);
});
