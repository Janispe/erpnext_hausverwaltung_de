const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JmapArchive, buildFilter } = require('./jmap');

function fixture({ queryState = 'q1', errorMethod, bodyTruncated = false, boxes = 2 } = {}) {
  const calls = [];
  const request = async (url, options) => {
    assert.equal(options.redirect, 'manual');
    assert.match(options.headers.Authorization, /^Basic /);
    if (!options.body) return Response.json({ apiUrl: 'https://mail.test/jmap', primaryAccounts: { 'urn:ietf:params:jmap:mail': 'a' }, accounts: { a: { accountCapabilities: { 'urn:ietf:params:jmap:mail': {} } } } });
    const [method, args] = JSON.parse(options.body).methodCalls[0];
    calls.push([method, args]);
    if (method === errorMethod) return Response.json({ methodResponses: [['error', { type: 'serverFail', description: 'private provider details' }, '0']] });
    let result;
    if (method === 'Email/query') result = { ids: ['e1', 'e2', 'e3'], queryState };
    if (method === 'Email/get') result = { list: args.ids.map((id, index) => ({
      id, mailboxIds: { [index ? 'b2' : 'b1']: true }, subject: id, preview: 'preview',
      textBody: [{ partId: 'p', type: 'text/plain' }], bodyValues: { p: { value: 'abcdefghij', isTruncated: bodyTruncated } },
    })) };
    if (method === 'Mailbox/query') result = { ids: Array.from({ length: Math.min(500, Math.max(0, boxes - args.position)) }, (_, index) => `b${args.position + index + 1}`), queryState: 'm1' };
    if (method === 'Mailbox/get') result = { list: args.ids.map((id) => ({ id, name: id === 'b1' ? 'Archive' : id === 'b2' ? 'Tenant' : id, parentId: id === 'b2' ? 'b1' : null })) };
    return Response.json({ methodResponses: [[method, result, '0']] });
  };
  return { calls, client: new JmapArchive({ url: 'https://mail.test', username: 'user', password: 'secret', fetchImpl: request }) };
}

test('global query has no mailbox restriction, pages cheaply, preserves ordered results and folder paths', async () => {
  const { client, calls } = fixture();
  const result = await client.handle('search_all_emails', { text: 'Hiller', limit: 2 });
  assert.equal(result.isError, false);
  const data = result.structuredContent;
  assert.equal(data.has_more, true);
  assert.equal(data.next_offset, 2);
  assert.deepEqual(data.emails.map((email) => email.jmap_email_id), ['e1', 'e2']);
  assert.equal(data.emails[1].mailboxes[0].path, 'Archive/Tenant');
  const query = calls.find(([method]) => method === 'Email/query')[1];
  assert.deepEqual(query.filter, { text: 'Hiller' });
  assert.equal(query.calculateTotal, false);
  assert.equal(query.limit, 3);
  await client.handle('search_all_emails', { subject: 'test' });
  assert.equal(calls.filter(([method]) => method === 'Mailbox/query').length, 1);
});

test('mailbox discovery retrieves more than the server get cap of 500', async () => {
  const { client, calls } = fixture({ boxes: 701 });
  const rows = await client.mailboxes();
  assert.equal(rows.size, 701);
  assert.deepEqual(calls.filter(([method]) => method === 'Mailbox/get').map(([, args]) => args.ids.length), [500, 201]);
});

test('input validation refuses wrong accounts, oversized calls, unknown/mutation parameters before network', async () => {
  const { client, calls } = fixture();
  for (const args of [{ account_name: 'other' }, { limit: 51 }, { offset: -1 }, { text: '' }, { since: '2026-10-08' }, { mark_as_read: true }, { since: '2026-10-09T00:00:00Z', before: '2026-10-08T00:00:00Z' }]) {
    assert.equal((await client.handle('search_all_emails', args)).isError, true);
  }
  for (const args of [{ jmap_email_ids: ['e1', 'e1'] }, { jmap_email_ids: [] }, { jmap_email_ids: ['1:20'] }, { jmap_email_ids: ['e1'], mark_as_read: true }]) {
    assert.equal((await client.handle('get_archive_emails_content', args)).isError, true);
  }
  assert.equal(calls.length, 0);
});

test('participant search is OR across address fields and AND with other filters; dates normalised', () => {
  const filter = buildFilter({ participant: 'a@test', subject: 'Rent', since: '2026-10-08T12:00:00+02:00' });
  assert.equal(filter.operator, 'AND');
  assert.deepEqual(filter.conditions[0], { subject: 'Rent', after: '2026-10-08T10:00:00.000Z' });
  assert.deepEqual(filter.conditions[1].conditions, [{ from: 'a@test' }, { to: 'a@test' }, { cc: 'a@test' }, { bcc: 'a@test' }]);
});

test('changed query state and provider errors never produce misleading empty search results', async () => {
  const { client } = fixture();
  const changed = await client.handle('search_all_emails', { offset: 2, query_state: 'old' });
  assert.equal(changed.isError, true);
  const failed = await fixture({ errorMethod: 'Email/query' }).client.handle('search_all_emails', { text: 'test' });
  assert.equal(failed.isError, true);
  assert.doesNotMatch(failed.content[0].text, /private provider details/);
});

test('content reads use JMAP IDs, bounded body pages and no mutations', async () => {
  const { client, calls } = fixture();
  const result = await client.handle('get_archive_emails_content', { jmap_email_ids: ['e1'], body_offset: 2, body_limit: 3 });
  const email = result.structuredContent.emails[0];
  assert.equal(email.body, 'cde');
  assert.equal(email.body_truncated, true);
  assert.equal(email.next_body_offset, 5);
  assert.ok(calls.every(([method]) => ['Email/get', 'Mailbox/query', 'Mailbox/get'].includes(method)));
  const truncated = await fixture({ bodyTruncated: true }).client.handle('get_archive_emails_content', { jmap_email_ids: ['e1'] });
  assert.equal(truncated.structuredContent.emails[0].provider_truncated, true);
  assert.equal(truncated.structuredContent.emails[0].next_body_offset, null);
});

test('discovery cannot send credentials to a different origin', async () => {
  let count = 0;
  const client = new JmapArchive({ url: 'https://mail.test', username: 'u', password: 'p', fetchImpl: async () => {
    count++;
    return Response.json({ apiUrl: 'https://evil.test/jmap', primaryAccounts: { 'urn:ietf:params:jmap:mail': 'a' }, accounts: { a: { accountCapabilities: { 'urn:ietf:params:jmap:mail': {} } } } });
  } });
  assert.equal((await client.handle('search_all_emails', {})).isError, true);
  assert.equal(count, 1);
});

test('discovery follows Stalwart same-origin redirect but never relays credentials cross-origin', async () => {
  for (const target of ['/jmap/session', 'https://evil.test/session']) {
    const urls = [];
    const client = new JmapArchive({ url: 'https://mail.test', username: 'u', password: 'p', fetchImpl: async (url) => {
      urls.push(url);
      if (urls.length === 1) return new Response(null, { status: 307, headers: { location: target } });
      return Response.json({ apiUrl: 'https://mail.test/jmap', primaryAccounts: { 'urn:ietf:params:jmap:mail': 'a' }, accounts: { a: { accountCapabilities: { 'urn:ietf:params:jmap:mail': {} } } } });
    } });
    if (target.startsWith('/')) {
      assert.equal((await client.session()).accountId, 'a');
      assert.deepEqual(urls, ['https://mail.test/.well-known/jmap', 'https://mail.test/jmap/session']);
    } else {
      await assert.rejects(client.session());
      assert.equal(urls.length, 1);
    }
  }
});
