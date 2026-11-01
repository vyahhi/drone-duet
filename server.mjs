import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { MOVES } from './src/engine.js';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const dev = process.argv.includes('--dev');
const host = process.env.HOST || '127.0.0.1';
const port = Number(process.env.PORT || 5173);
const modelBase = process.env.DUET_MODEL_BASE_URL?.replace(/\/$/, '');
const modelName = process.env.DUET_MODEL_NAME || 'LFM3-1.7B';
const modelKey = process.env.DUET_MODEL_API_KEY;
let vite;
if (dev) {
  const { createServer } = await import('vite');
  vite = await createServer({ root: ROOT, server: { middlewareMode: true, host }, appType: 'spa' });
}

function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(value));
}

async function body(req) {
  let raw = '';
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 12000) throw new Error('Request too large');
  }
  return JSON.parse(raw);
}

const server = http.createServer(async (req, res) => {
  // Private local API: only same-origin browser calls; no arbitrary inference URLs
  // or secrets are accepted from clients. Credentials stay in this Node process.
  const origin = req.headers.origin;
  if (req.url.startsWith('/api/') && origin && origin !== `http://${req.headers.host}` && origin !== `https://${req.headers.host}`) {
    return json(res, 403, { error: 'Same-origin requests only' });
  }
  if (req.url === '/api/model' && req.method === 'GET') {
    return json(res, 200, { configured: Boolean(modelBase), model: modelName });
  }
  if (req.url === '/api/decide' && req.method === 'POST') {
    if (!modelBase) return json(res, 503, { error: 'No model endpoint configured. Local autonomy is available.' });
    try {
      const observation = await body(req);
      if (!['Ari', 'Sol'].includes(observation.name) || !Array.isArray(observation.position) || !MOVES.includes(observation.partner?.move)) {
        return json(res, 400, { error: 'Invalid dance observation' });
      }
      const response = await fetch(`${modelBase}/chat/completions`, {
        method: 'POST', signal: AbortSignal.timeout(10000),
        headers: { 'Content-Type': 'application/json', ...(modelKey ? { Authorization: `Bearer ${modelKey}` } : {}) },
        body: JSON.stringify({
          model: modelName, temperature: 0.8, max_tokens: 220,
          messages: [
            { role: 'system', content: `You are ${observation.name}, an autonomous simulated drone dancer. Your personality: ${observation.role}. Observe the other dancer and choose YOUR next eight-beat phrase. Respond to your partner, vary your moves, fit the musical energy. You only select high-level moves; a separate controller executes them. Choose exactly one of: ${MOVES.join(', ')}. Reply ONLY with a JSON object: {"move":"orbit","reason":"One short sentence describing your intention."}. No markdown, no reasoning trace.` },
            { role: 'user', content: JSON.stringify(observation) },
          ],
        }),
      });
      if (!response.ok) throw new Error(`Inference endpoint returned ${response.status}`);
      const data = await response.json();
      const content = data.choices?.[0]?.message?.content || '';
      const match = content.match(/\{[^{}]*\}/g);
      const decision = match?.map(s => { try { return JSON.parse(s); } catch { return null; } }).find(d => MOVES.includes(d?.move) && typeof d.reason === 'string');
      if (!decision) throw new Error('Model returned an invalid dance decision');
      json(res, 200, { move: decision.move, reason: decision.reason.slice(0, 180), model: data.model || modelName });
    } catch (error) {
      // Do not expose upstream response bodies or credentials in client errors.
      console.warn('Model decision unavailable:', error.name === 'TimeoutError' ? 'timeout' : 'request or output invalid');
      json(res, 502, { error: 'Model unavailable or returned an invalid move. Using local autonomy.' });
    }
    return;
  }
  if (req.url.startsWith('/api/')) return json(res, 404, { error: 'Unknown API route' });
  if (dev) return vite.middlewares(req, res, () => { res.writeHead(404); res.end(); });
  if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end(); }
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const dist = path.join(ROOT, 'dist');
    let file = path.resolve(dist, `.${pathname}`);
    if (!file.startsWith(dist + path.sep) && file !== dist) throw new Error('Invalid path');
    if (pathname.split('/').some(p => p.startsWith('.'))) throw new Error('Invalid path');
    try { if (!(await stat(file)).isFile()) file = path.join(dist, 'index.html'); }
    catch { file = path.join(dist, 'index.html'); }
    const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json' };
    const data = await readFile(file);
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'X-Content-Type-Options': 'nosniff' });
    res.end(req.method === 'HEAD' ? undefined : data);
  } catch { res.writeHead(404); res.end('Not found. Run npm run build first.'); }
});
server.listen(port, host, () => console.log(`Drone Duet · http://${host}:${server.address().port} · ${modelBase ? `model configured: ${modelName}` : 'local autonomous agents'}`));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, async () => { await vite?.close(); server.close(); process.exit(0); });
