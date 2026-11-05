'use strict';
// Execute the shipped controller with owned DOM/fetch only. No browser or network.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const scenario = process.argv[3];
const events = {}, windowEvents = {}, elements = new Map(), intervals = new Set();
const requests = [], contexts = [], forbidden = [];
let nextTimer = 1, maximumIntervals = 0;
class OwnedElement {
  constructor(id = '') { this.id = id; this.hidden = id === 'workspace'; this.dataset = {}; this.open = false; this.children = []; this.classList = {toggle() {}}; }
  set id(value) { this._id = value; if (value) elements.set(value, this); }
  get id() { return this._id; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  addEventListener() {}
  closest() { return element('horizon-label'); }
  querySelector(selector) { const match = selector.match(/data-page="([a-z]+)"/); return match ? this.children.find(child => child.dataset.page === match[1]) || null : null; }
  querySelectorAll() { return this.children; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function element(id) { if (!elements.has(id)) new OwnedElement(id); return elements.get(id); }
const nav = element('nav');
for (const page of ['team', 'players', 'decisions', 'performance', 'health']) { const button = new OwnedElement(); button.dataset.page = page; nav.append(button); }
const document = {
  hidden: scenario === 'background_open', documentElement: {dataset: {}}, body: new OwnedElement(),
  getElementById: element, createElement: () => new OwnedElement(),
  querySelector: selector => selector === 'nav' ? nav : element('aside-note'),
  querySelectorAll: () => nav.children,
  addEventListener: (name, callback) => { events[name] = callback; }
};
function response(ok, value) { return {ok, json: async () => value}; }
const contextValue = {persistent_history: true, demo: false, synthetic_sources: false, eligibility: null};
const sandbox = {
  document, window: {addEventListener: (name, callback) => { windowEvents[name] = callback; }},
  AbortController, DOMException, Node: OwnedElement, performance: {now: () => 0},
  setTimeout: () => nextTimer++, clearTimeout() {},
  setInterval: () => { const id = nextTimer++; intervals.add(id); maximumIntervals = Math.max(maximumIntervals, intervals.size); return id; },
  clearInterval: id => intervals.delete(id),
  fetch: (url, options) => {
    requests.push({path: url, method: options.method});
    if (url === '/api/context' && options.method === 'GET') {
      return new Promise((resolve, reject) => {
        const call = {done: false, aborted: false, resolve: (ok = true) => { call.done = true; resolve(response(ok, ok ? contextValue : {error_code: 'SESSION_REQUIRED'})); }};
        options.signal.addEventListener('abort', () => { call.aborted = true; reject(new DOMException('Owned abort', 'AbortError')); }, {once: true});
        contexts.push(call);
      });
    }
    if (options.method === 'GET' && url === '/api/status') return Promise.resolve(response(true, {status: 'PENDING', stages: [], diagnostics: null}));
    if (options.method === 'GET' && url === '/api/eligibility') return Promise.resolve(response(true, null));
    if (options.method === 'GET' && url === '/api/analysis/status') return Promise.resolve(response(true, {selected_run: null, provenance_class: 'OWNED_SYNTHETIC'}));
    if (options.method === 'GET' && url === '/api/desk') return Promise.resolve(response(false, {error_code: 'NO_CURRENT_RECOMMENDATION'}));
    if (options.method === 'POST' && url === '/api/logout') return Promise.resolve(response(true, {status: 'SIGNED_OUT'}));
    forbidden.push({path: url, method: options.method});
    return Promise.reject(new Error('OWNED_UNEXPECTED_REQUEST'));
  }
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, {filename: 'actual-desk.js', timeout: 1000});
async function flush() { for (let i = 0; i < 30; i++) await Promise.resolve(); }
function visible(value) { document.hidden = !value; events.visibilitychange(); }
function pageshow() { windowEvents.pageshow(); }
function resolveCurrent(ok = true) { const call = contexts.find(item => !item.done && !item.aborted); assert.ok(call, 'A live owned context GET is required'); call.resolve(ok); }
function workspaceVisible() { assert.equal(element('workspace').hidden, false); assert.equal(element('pair-panel').hidden, true); assert.equal(intervals.size, 1); }
(async () => {
  if (scenario === 'background_open') {
    await flush(); assert.equal(contexts.length, 0); assert.equal(intervals.size, 0);
    visible(true); pageshow(); assert.equal(contexts.length, 1); resolveCurrent(); await flush(); workspaceVisible();
  } else if (scenario === 'hidden_response') {
    assert.equal(contexts.length, 1); visible(false); await flush();
    contexts[0].resolve(); await flush(); assert.equal(element('workspace').hidden, true);
    visible(true); resolveCurrent(); await flush(); workspaceVisible(); assert.equal(contexts.length, 2);
  } else if (scenario === 'show_before_abort_settles') {
    visible(false); visible(true); pageshow(); await flush();
    assert.equal(contexts.length, 2); resolveCurrent(); await flush(); workspaceVisible();
  } else if (scenario === 'duplicate_events') {
    for (let i = 0; i < 4; i++) { visible(true); pageshow(); }
    assert.equal(contexts.length, 1); resolveCurrent(); await flush(); workspaceVisible();
    visible(true); pageshow(); await flush(); assert.equal(contexts.length, 1); assert.equal(maximumIntervals, 1);
  } else if (scenario === 'unauthorized') {
    resolveCurrent(false); await flush(); assert.equal(element('workspace').hidden, true); assert.equal(intervals.size, 0); assert.equal(contexts.length, 1);
  } else if (scenario === 'logout') {
    resolveCurrent(); await flush(); workspaceVisible(); await element('logout').onclick(); await flush();
    visible(false); visible(true); pageshow(); await flush();
    assert.equal(contexts.length, 1); assert.equal(element('workspace').hidden, true); assert.equal(intervals.size, 0);
  } else if (scenario === 'logout_during_pending') {
    await element('logout').onclick(); contexts[0].resolve(); await flush(); visible(true); pageshow(); await flush();
    assert.equal(contexts.length, 1); assert.equal(element('workspace').hidden, true); assert.equal(intervals.size, 0);
  } else throw new Error('UNKNOWN_OWNED_SCENARIO');
  assert.deepEqual(forbidden, []); assert.ok(maximumIntervals <= 1);
  assert.ok(requests.every(item => item.method === 'GET' || item.path === '/api/logout'));
  console.log(JSON.stringify({state: 'PASS', scenario, source_sha256: crypto.createHash('sha256').update(source).digest('hex'), context_gets: contexts.length, maximum_polling_intervals: maximumIntervals, provider_requests: 0}));
})().catch(() => { console.error('OWNED_BROWSER_SESSION_ASSERTION_FAILED'); process.exitCode = 2; });
