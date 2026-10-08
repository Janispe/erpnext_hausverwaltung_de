// Streamable-HTTP pass-through to mcp-email-server that turns binary attachment resources into text.
//
// get_attachment_content returns an embedded resource {uri, mimeType, blob}. LibreChat keeps only the
// text, URI and MIME type of MCP resources and drops the blob, so the attachment never arrives. Here
// blob resources become one text item with a JSON object {attachment: {name, mime_type, size_bytes,
// base64}}; code in the sandbox (run_tools_with_bash) decodes it into a file. The agent grants the
// tool to code execution only, so the base64 never enters the model context. Everything else passes
// through unchanged. Adds read-only, account-wide JMAP search when configured. No dependencies.
const http = require('node:http');
const { JmapArchive, tools: archiveTools } = require('./jmap');

const upstream = (process.env.UPSTREAM_URL || '').replace(/\/$/, '');
const port = Number(process.env.PORT || 9558);
const maxBytes = Number(process.env.MAX_ATTACHMENT_BYTES || 15 * 1024 * 1024);
const archive = new JmapArchive({
  url: process.env.JMAP_URL,
  username: process.env.JMAP_USERNAME,
  password: process.env.JMAP_PASSWORD,
  account: process.env.JMAP_ACCOUNT_NAME || 'archiv',
});

const REQUEST_HEADERS = ['authorization', 'content-type', 'accept', 'mcp-session-id', 'mcp-protocol-version', 'last-event-id'];
const RESPONSE_HEADERS = ['content-type', 'mcp-session-id', 'mcp-protocol-version', 'cache-control'];

function attachmentText(resource, name) {
  const size = Math.floor((resource.blob.length * 3) / 4) - (resource.blob.match(/=*$/)[0].length || 0);
  if (size > maxBytes) {
    return JSON.stringify({ error: `Anhang ${name || ''} ist ${size} Bytes groß; Grenze ${maxBytes} Bytes.` });
  }
  return JSON.stringify({
    attachment: { name: name || null, mime_type: resource.mimeType || null, size_bytes: size, base64: resource.blob },
  });
}

function transform(message, names) {
  if (archive.enabled && Array.isArray(message?.result?.tools)) {
    const existing = new Set(message.result.tools.map((tool) => tool.name));
    message.result.tools.push(...archiveTools.filter((tool) => !existing.has(tool.name)));
  }
  const content = message?.result?.content;
  if (!Array.isArray(content)) return message;
  message.result.content = content.map((item) => {
    if (item?.type !== 'resource' || typeof item.resource?.blob !== 'string') return item;
    return { type: 'text', text: attachmentText(item.resource, names.get(message.id)) };
  });
  names.delete(message.id);
  return message;
}

function transformPayload(text, names) {
  try {
    const parsed = JSON.parse(text);
    const out = Array.isArray(parsed) ? parsed.map((m) => transform(m, names)) : transform(parsed, names);
    return JSON.stringify(out);
  } catch {
    return text;
  }
}

function transformSseLine(line, names) {
  if (!line.startsWith('data:')) return line;
  const data = line.slice(5).trim();
  return data ? `data: ${transformPayload(data, names)}` : line;
}

function rememberNames(body, names) {
  try {
    const parsed = JSON.parse(body.toString('utf8'));
    for (const message of Array.isArray(parsed) ? parsed : [parsed]) {
      if (message?.method === 'tools/call' && message.params?.name === 'get_attachment_content') {
        names.set(message.id, message.params.arguments?.attachment_name);
      }
    }
  } catch {
    // not JSON: pass through
  }
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 2 * 1024 * 1024) throw new Error('Request too large');
    chunks.push(chunk);
  }
  return chunks.length ? Buffer.concat(chunks) : undefined;
}

const server = http.createServer(async (req, res) => {
  if (req.url === '/healthz') {
    res.writeHead(200).end('ok');
    return;
  }
  try {
    const headers = {};
    for (const name of REQUEST_HEADERS) if (req.headers[name]) headers[name] = req.headers[name];
    const body = ['GET', 'HEAD', 'DELETE'].includes(req.method) ? undefined : await readBody(req);
    if (archive.enabled && req.method === 'POST' && req.url === '/mcp' && body) {
      let message;
      try { message = JSON.parse(body.toString('utf8')); } catch { /* pass through */ }
      if (message?.method === 'tools/call' && archiveTools.some((tool) => tool.name === message.params?.name)) {
        if (message.id === undefined) {
          res.writeHead(400).end();
          return;
        }
        const result = await archive.handle(message.params.name, message.params.arguments || {});
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }));
        return;
      }
    }
    const names = new Map();
    if (body) rememberNames(body, names);
    const controller = new AbortController();
    res.on('close', () => controller.abort());
    const response = await fetch(upstream + req.url, { method: req.method, headers, body, signal: controller.signal });
    const out = {};
    for (const name of RESPONSE_HEADERS) {
      const value = response.headers.get(name);
      if (value) out[name] = value;
    }
    res.writeHead(response.status, out);
    const type = response.headers.get('content-type') || '';
    if (type.includes('text/event-stream') && response.body) {
      const decoder = new TextDecoder();
      let pending = '';
      for await (const chunk of response.body) {
        pending += decoder.decode(chunk, { stream: true });
        const lines = pending.split('\n');
        pending = lines.pop();
        res.write(lines.map((line) => transformSseLine(line, names)).join('\n') + '\n');
      }
      pending += decoder.decode();
      if (pending) res.write(transformSseLine(pending, names));
      res.end();
      return;
    }
    const text = await response.text();
    res.end(type.includes('application/json') ? transformPayload(text, names) : text);
  } catch (error) {
    if (error.name === 'AbortError') return;
    console.error(`[mail-proxy] ${req.method} ${req.url}: ${error.message}`);
    if (!res.headersSent) res.writeHead(502, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'Upstream request failed' } }));
  }
});

if (require.main === module) {
  if (!upstream) throw new Error('UPSTREAM_URL is required');
  server.listen(port, () => console.log(`[mail-proxy] listening on ${port} -> ${upstream}; JMAP ${archive.enabled ? 'enabled' : 'disabled'}`));
}
module.exports = { server, transformPayload, transformSseLine };
