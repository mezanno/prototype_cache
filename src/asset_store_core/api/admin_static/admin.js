'use strict';
const $ = id => document.getElementById(id);
let session = 0;
class StaleSessionError extends Error {}
let secret = '', selected = null, next = null, filters = '', preview = null, previewPrefix = '';
function status(message, error = false) { $('status').textContent = message; $('status').className = error ? 'error' : ''; }
async function request(path, body, method) {
  if (!secret) throw new Error('Connect with an admin credential first.');
  const started = session;
  try {
    const response = await fetch('/admin/api' + path, {
      method: method || (body ? 'POST' : 'GET'), cache: 'no-store',
      headers: {'Authorization': 'Service admin:' + secret, 'Content-Type': 'application/json'},
      body: body ? JSON.stringify(body) : undefined
    });
    const data = await response.json();
    if (started !== session) throw new StaleSessionError();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
    return data;
  } catch (error) {
    if (started !== session) throw new StaleSessionError();
    throw error;
  }
}
function run(fn) { return async () => { try { await fn(); } catch (e) { if (!(e instanceof StaleSessionError)) status(e.message, true); } }; }
// FR-014 / FR-040..042: retire old requests and all loaded or editable data.
function clearSession() {
  session++; secret = ''; selected = null; preview = null; previewPrefix = ''; next = null;
  for (const id of ['secret', 'annotations', 'alias', 'quota-bytes', 'quota-count']) $(id).value = '';
  for (const id of ['metadata', 'events', 'preview-result', 'quota']) $(id).textContent = '';
  $('ttl').value = '86400'; $('eviction').value = 'inherit';
  $('mutable').checked = false; $('quota-sweep').checked = false;
  $('assets').replaceChildren(); $('actions').hidden = true;
  $('apply-bulk').disabled = true; $('next').disabled = true;
  $('selection').textContent = 'Choose an asset.';
}

function getFilters() {
  const params = new URLSearchParams();
  for (const [key, value] of new FormData($('filters'))) {
    if (value) params.set(key, key.startsWith('created_') ? new Date(value).toISOString() : value);
  }
  return params.toString();
}
async function list(cursor = null) {
  const params = new URLSearchParams(filters);
  if (cursor) params.set('cursor', cursor);
  const data = await request('/assets?' + params);
  $('assets').replaceChildren();
  for (const asset of data.items) {
    const row = document.createElement('tr'), cell = document.createElement('td'), button = document.createElement('button');
    button.textContent = asset.aliases[0] || asset.asset_id;
    button.onclick = run(() => inspect(asset.asset_id)); cell.append(button); row.append(cell);
    for (const value of [asset.state, asset.size_bytes ?? '—']) { const td = document.createElement('td'); td.textContent = value; row.append(td); }
    $('assets').append(row);
  }
  if (!data.items.length) { const row = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 3; td.textContent = 'No assets match these filters.'; row.append(td); $('assets').append(row); }
  next = data.next_cursor; $('next').disabled = !next;
  $('quota').textContent = data.quota ? `Partition usage: ${data.quota.used_bytes} bytes / ${data.quota.quota_bytes ?? 'unlimited'} · ${data.quota.used_asset_count} assets / ${data.quota.quota_asset_count ?? 'unlimited'}` : '';
  if (data.quota) { $('quota-bytes').value = data.quota.quota_bytes ?? ''; $('quota-count').value = data.quota.quota_asset_count ?? ''; $('quota-sweep').checked = data.quota.eviction_sweep_enabled; }
  status(`${data.items.length} assets on this page${next ? ' · more available' : ''}.`);
}
async function inspect(id) {
  const data = await request('/assets/' + encodeURIComponent(id)); selected = data.asset;
  $('selection').textContent = selected.asset_id + ' · ' + selected.state;
  $('metadata').textContent = JSON.stringify(selected, null, 2);
  $('events').textContent = JSON.stringify(data.audit, null, 2);
  $('annotations').value = JSON.stringify(selected.annotations, null, 2);
  $('eviction').value = selected.eviction_policy; $('actions').hidden = false;
}
async function mutate(action, extra = {}) {
  if (!selected) throw new Error('Select an asset first.');
  if (!confirm(`Apply ${action} to ${selected.asset_id}?`)) return;
  const id = selected.asset_id;
  await request('/assets/' + encodeURIComponent(id) + '/actions', {action, expected_updated_at: selected.updated_at, ...extra});
  await list(); await inspect(id); status(`Applied ${action}.`);
}
$('connect').onclick = run(async () => { const credential = $('secret').value; clearSession(); secret = credential; filters = getFilters(); await list(); });
$('disconnect').onclick = () => { clearSession(); status('Disconnected.'); };
$('filters').onsubmit = event => { event.preventDefault(); run(async () => { filters = getFilters(); preview = null; $('apply-bulk').disabled = true; await list(); })(); };
$('next').onclick = run(() => list(next));
$('expire').onclick = run(() => mutate('expire'));
$('delete').onclick = run(() => mutate('delete'));
$('set-ttl').onclick = run(() => mutate('ttl', {ttl_seconds: Number($('ttl').value)}));
$('attach').onclick = run(() => mutate('attach', {alias: $('alias').value, mutable: $('mutable').checked}));
$('detach').onclick = run(() => mutate('detach', {alias: $('alias').value}));
$('save-annotations').onclick = run(() => mutate('annotations', {annotations: JSON.parse($('annotations').value)}));
$('save-eviction').onclick = run(() => mutate('eviction', {eviction_policy: $('eviction').value}));
$('save-quota').onclick = run(async () => {
  const params = new URLSearchParams(getFilters());
  if (!params.get('space') || !params.get('partition_id')) throw new Error('Choose a space and partition first.');
  if (!confirm('Replace this partition quota configuration?')) return;
  await request('/quotas/partition', {space: params.get('space'), partition_id: params.get('partition_id'), quota_bytes: $('quota-bytes').value === '' ? null : Number($('quota-bytes').value), quota_asset_count: $('quota-count').value === '' ? null : Number($('quota-count').value), eviction_sweep_enabled: $('quota-sweep').checked}, 'PUT');
  filters = getFilters(); await list(); status('Partition quota saved.');
});
$('preview').onclick = run(async () => {
  preview = null; $('apply-bulk').disabled = true;
  previewPrefix = new URLSearchParams(getFilters()).get('prefix') || '';
  preview = await request('/aliases/expire?prefix=' + encodeURIComponent(previewPrefix));
  $('preview-result').textContent = JSON.stringify(preview, null, 2);
  $('apply-bulk').disabled = !preview.candidates.length; status(`${preview.candidates.length} assets would expire.`);
});
$('apply-bulk').onclick = run(async () => {
  if (!preview || !confirm(`Expire ${preview.candidates.length} assets under ${previewPrefix}?`)) return;
  const data = await request('/aliases/expire?prefix=' + encodeURIComponent(previewPrefix), {candidates: preview.candidates});
  preview = null; $('apply-bulk').disabled = true; await list();
  if (selected) await inspect(selected.asset_id);
  status(`Expired ${data.applied}; skipped ${data.skipped} changed assets.`);
});
$('audit').onclick = run(async () => { $('events').textContent = JSON.stringify(await request('/audit'), null, 2); });
