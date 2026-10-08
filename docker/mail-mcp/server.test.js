const { test } = require('node:test');
const assert = require('node:assert/strict');
process.env.JMAP_URL = 'https://mail.test';
process.env.JMAP_USERNAME = 'user';
process.env.JMAP_PASSWORD = 'secret';
const { server, transformPayload, transformSseLine } = require('./server');

test('adds tools to JSON and SSE catalogs without duplication or losing upstream tools/session framing', () => {
  const catalog = { jsonrpc: '2.0', id: 1, result: { tools: [{ name: 'list_emails_metadata' }] } };
  const augmented = transformPayload(JSON.stringify(catalog), new Map());
  const names = JSON.parse(augmented).result.tools.map((tool) => tool.name);
  assert.deepEqual(names, ['list_emails_metadata', 'search_all_emails', 'get_archive_emails_content']);
  assert.deepEqual(JSON.parse(transformPayload(augmented, new Map())).result.tools.map((tool) => tool.name), names);
  assert.deepEqual(JSON.parse(transformSseLine('data: ' + JSON.stringify(catalog), new Map()).slice(6)).result.tools.map((tool) => tool.name), names);
  assert.equal(transformSseLine('event: message', new Map()), 'event: message');
});

test('keeps attachment conversion for existing IMAP tools', () => {
  const payload = { id: 2, result: { content: [{ type: 'resource', resource: { mimeType: 'text/plain', blob: 'aGVsbG8=' } }] } };
  const result = JSON.parse(transformPayload(JSON.stringify(payload), new Map([[2, 'test.txt']])));
  const attachment = JSON.parse(result.result.content[0].text).attachment;
  assert.deepEqual(attachment, { name: 'test.txt', mime_type: 'text/plain', size_bytes: 5, base64: 'aGVsbG8=' });
});

test('local calls preserve MCP request ID and report validation failures as tool errors', async () => {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/mcp`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 'search-1', method: 'tools/call', params: { name: 'search_all_emails', arguments: { account_name: 'unauthorized' } } }),
    });
    assert.equal(response.status, 200);
    const result = await response.json();
    assert.equal(result.id, 'search-1');
    assert.equal(result.result.isError, true);
  } finally { await new Promise((resolve) => server.close(resolve)); }
});
