// Run inside a client container: node smoke.js [http://mail-proxy:9558/mcp].
// Prints only counts and timings, never mail headers, bodies or credentials.
const assert = require('node:assert/strict');
const url = process.argv[2] || 'http://mail-proxy:9558/mcp';
const base = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' };
let session;
let id = 0;
async function rpc(method, params = {}) {
  const response = await fetch(url, {
    method: 'POST', headers: { ...base, ...(session ? { 'Mcp-Session-Id': session } : {}) },
    body: JSON.stringify({ jsonrpc: '2.0', id: ++id, method, params }), signal: AbortSignal.timeout(30000),
  });
  assert.ok(response.ok, `HTTP ${response.status}`);
  session = response.headers.get('mcp-session-id') || session;
  const text = await response.text();
  const message = JSON.parse(text.match(/^data:\s*(.*)$/m)?.[1] ?? text);
  assert.equal(message.id, id);
  assert.ok(!message.error, 'MCP protocol error');
  return message.result;
}
async function call(name, args) {
  const result = await rpc('tools/call', { name, arguments: args });
  assert.ok(!result.isError, result.content?.[0]?.text || 'Tool error');
  return result.structuredContent || JSON.parse(result.content[0].text);
}
(async () => {
  await rpc('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'global-mail-smoke', version: '1' } });
  const initialized = await fetch(url, { method: 'POST', headers: { ...base, 'Mcp-Session-Id': session }, body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) });
  assert.ok(initialized.ok);
  const catalog = await rpc('tools/list');
  for (const name of ['search_all_emails', 'get_archive_emails_content', 'list_emails_metadata', 'get_emails_content', 'get_attachment_content']) {
    assert.ok(catalog.tools.some((tool) => tool.name === name), `${name} missing`);
  }
  const start = performance.now();
  const first = await call('search_all_emails', { text: 'Miete', limit: 20 });
  const ms = Math.round(performance.now() - start);
  assert.equal(first.scope, 'all_accessible_mailboxes');
  const folders = new Set(first.emails.flatMap((email) => email.mailboxes.map((box) => box.id))).size;
  assert.ok(folders > 1, 'Expected actual hits in multiple archive folders');
  const second = await call('search_all_emails', { text: 'Miete', limit: 20, offset: first.next_offset, query_state: first.query_state });
  assert.ok(second.emails.every((email) => !first.emails.some((previous) => previous.jmap_email_id === email.jmap_email_id)), 'Duplicate page results');
  const content = await call('get_archive_emails_content', { jmap_email_ids: [first.emails[0].jmap_email_id], body_limit: 500 });
  assert.equal(content.emails.length, 1);
  const denied = await rpc('tools/call', { name: 'search_all_emails', arguments: { account_name: 'unconfigured' } });
  assert.equal(denied.isError, true);
  console.log(JSON.stringify({ catalog_tools: catalog.tools.length, search_ms: ms, first_page: first.emails.length, folders, second_page: second.emails.length, body_chars: content.emails[0].body.length, wrong_account_rejected: true }));
  await fetch(url, { method: 'DELETE', headers: { ...base, 'Mcp-Session-Id': session } });
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
