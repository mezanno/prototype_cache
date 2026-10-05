// B-013 / FR-014 / FR-040..042: execute the shipped client with controlled responses.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const source = readFileSync(join(__dirname, '../src/asset_store_core/api/admin_static/admin.js'), 'utf8');

function element() {
  return {value: '', textContent: '', checked: false, hidden: false, disabled: false,
    children: [], append(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; }};
}
function harness() {
  const elements = new Map();
  const $ = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const pending = [];
  const context = vm.createContext({
    document: {getElementById: $, createElement: element},
    URLSearchParams, FormData: class { *[Symbol.iterator]() { yield ['space', 'results']; yield ['partition_id', 'fixture']; } },
    confirm: () => true,
    fetch: (path, options) => new Promise((resolve, reject) => pending.push({path, options, resolve, reject})),
  });
  vm.runInContext(source, context);
  const respond = (data, ok = true) => pending.shift().resolve({ok, json: async () => data});
  const connect = async () => {
    $('secret').value = 'test-only';
    const done = $('connect').onclick();
    respond({items: [{asset_id: 'fixture', aliases: ['results/fixture/sample'], state: 'expired', size_bytes: 36}],
      next_cursor: null, quota: {used_bytes: 0, used_asset_count: 0, quota_bytes: 1024, quota_asset_count: 3, eviction_sweep_enabled: false}});
    await done;
  };
  return {$, pending, respond, connect};
}
function cleared(h) {
  for (const id of ['secret', 'annotations', 'alias', 'quota-bytes', 'quota-count']) assert.equal(h.$(id).value, '', id);
  for (const id of ['metadata', 'events', 'preview-result', 'quota']) assert.equal(h.$(id).textContent, '', id);
  assert.equal(h.$('assets').children.length, 0);
  assert.equal(h.$('actions').hidden, true);
  assert.equal(h.$('apply-bulk').disabled, true);
  assert.equal(h.$('next').disabled, true);
  assert.equal(h.$('mutable').checked, false);
  assert.equal(h.$('quota-sweep').checked, false);
}

test('disconnect clears quota and edit fields, then rejects unauthenticated actions', async () => {
  const h = harness(); await h.connect();
  assert.equal(h.$('quota-bytes').value, 1024);
  for (const id of ['annotations', 'alias']) h.$(id).value = 'old data';
  h.$('mutable').checked = h.$('quota-sweep').checked = true;
  h.$('disconnect').onclick(); cleared(h);
  await h.$('audit').onclick();
  assert.equal(h.pending.length, 0);
  assert.equal(h.$('status').textContent, 'Connect with an admin credential first.');
});

for (const operation of ['list', 'inspect', 'audit', 'preview']) {
  test(`late ${operation} response cannot restore data after disconnect`, async () => {
    const h = harness(); await h.connect();
    let done;
    if (operation === 'list') done = h.$('next').onclick();
    if (operation === 'inspect') done = h.$('assets').children[0].children[0].children[0].onclick();
    if (operation === 'audit') done = h.$('audit').onclick();
    if (operation === 'preview') done = h.$('preview').onclick();
    h.$('disconnect').onclick();
    const asset = {asset_id: 'fixture', aliases: ['results/fixture/sample'], annotations: {note: 'old'}, eviction_policy: 'exempt'};
    h.respond({items: [asset], asset, audit: ['old audit'], candidates: [asset], next_cursor: 'old', quota: {quota_bytes: 1024}});
    await done; cleared(h);
    assert.equal(h.$('status').textContent, 'Disconnected.');
  });
}

test('an old response cannot replace a newly connected session', async () => {
  const h = harness(); await h.connect();
  const old = h.$('audit').onclick();
  const oldRequest = h.pending.shift();
  h.$('disconnect').onclick(); await h.connect();
  oldRequest.resolve({ok: true, json: async () => ['previous session audit']});
  await old;
  assert.equal(h.$('events').textContent, '');
  assert.equal(h.$('status').textContent, '1 assets on this page.');
  assert.equal(h.$('assets').children.length, 1);
});

test('late transport errors do not replace disconnected feedback', async () => {
  const h = harness(); await h.connect();
  const done = h.$('audit').onclick();
  h.$('disconnect').onclick(); h.pending.shift().reject(new Error('network failed'));
  await done; assert.equal(h.$('status').textContent, 'Disconnected.');
});

test('a new failed connection clears previous data and reports the error', async () => {
  const h = harness(); await h.connect();
  h.$('secret').value = 'wrong-test-secret';
  const done = h.$('connect').onclick(); h.respond({detail: 'Unauthorized'}, false);
  await done; cleared(h);
  assert.equal(h.$('status').textContent, 'Unauthorized');
});

test('disconnect while decoding JSON discards the result', async () => {
  const h = harness(); await h.connect();
  const done = h.$('audit').onclick();
  let finishJson;
  const json = new Promise(resolve => { finishJson = resolve; });
  h.pending.shift().resolve({ok: true, json: () => json});
  await Promise.resolve();
  h.$('disconnect').onclick(); finishJson(['late audit']);
  await done; cleared(h);
  assert.equal(h.$('status').textContent, 'Disconnected.');
});

test('disconnect during a submitted mutation prevents refresh requests and stale feedback', async () => {
  const h = harness(); await h.connect();
  const inspect = h.$('assets').children[0].children[0].children[0].onclick();
  h.respond({asset: {asset_id: 'fixture', state: 'available', updated_at: 'revision', annotations: {}, eviction_policy: 'inherit'}, audit: []});
  await inspect;
  const mutation = h.$('expire').onclick();
  assert.equal(h.pending[0].path, '/admin/api/assets/fixture/actions');
  h.$('disconnect').onclick(); h.respond({state: 'expired'});
  await mutation; cleared(h);
  assert.equal(h.pending.length, 0);
  assert.equal(h.$('status').textContent, 'Disconnected.');
});
