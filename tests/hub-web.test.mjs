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
  providers:{xpiki:{models:[{id:'claude-test',name:'Claude Test'}],enabledModels:['claude-test'],quota:{},baseUrl:'https://api.xpiki.com/v1'},openrouter:{hasKey:true}},
};

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
  assert.equal(elements.get('btn-download-sing-box').disabled, true);
  assert.equal(elements.get('btn-download-xray').disabled, false);
});

test('failed domains show error indicators and no invented milliseconds', () => {
  const {elements} = frontend(state);
  const row = elements.get('diag-tbody-openai').children[0].innerHTML;
  assert.match(row, /connection-indicator error/);
  assert.match(row, /TimeoutError/);
  assert.doesNotMatch(row, /\d+ мс/);
  assert.equal(elements.get('diag-tbody-google').children.length, 5);
  assert.equal(elements.get('diag-tbody-claude').children.length, 3);
  assert.equal(elements.get('diag-tbody-xpiki').children.length, 1);
  assert.equal(elements.get('diag-tbody-openrouter').children.length, 1);
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
  fixture.config.providers_visibility = {antigravity:true,openai:true,claude:false,xpiki:false,openrouter:false};
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
  fixture.config.providers_visibility = {antigravity:false,openai:false,claude:false,xpiki:false,openrouter:false};
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
  fixture.config.providers_visibility = {antigravity:true,openai:true,claude:false,xpiki:false,openrouter:false};
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
  fixture.config.providers_visibility = {antigravity:false,openai:false,claude:false,xpiki:false,openrouter:false};
  const {elements, nav, context} = frontend(fixture);
  assert.equal(vm.runInContext('activeTab', context), 'dashboard');
  assert.equal(nav[0].dataset.tab, 'dashboard');
  assert.equal(nav[nav.findIndex(item=>item.dataset.tab === 'network')+1].dataset.tab, 'diagnostics');
  assert.match(markup, /id="view-dashboard" class="view-tab active"/);
  assert.match(elements.get('dashboard-providers').innerHTML, /Провайдеры выключены/);
  assert.match(elements.get('dashboard-metrics').innerHTML, /0 \/ 0/);
  assert.equal(elements.get('dashboard-check').disabled, true);
});
