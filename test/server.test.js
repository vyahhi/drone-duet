import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import { DuetEngine } from '../src/engine.js';

async function startApp(t, extraEnv = {}) {
  const child = spawn(process.execPath, ['server.mjs'], {
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    env: { ...process.env, HOST: '127.0.0.1', PORT: '0', DUET_MODEL_BASE_URL: '', ...extraEnv },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => child.kill('SIGTERM'));
  let output = '';
  return await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { child.kill(); reject(new Error('Server startup timed out')); }, 6000);
    child.stderr.on('data', chunk => { output += chunk; });
    child.once('exit', () => { clearTimeout(timeout); reject(new Error(`Server exited: ${output}`)); });
    child.stdout.on('data', chunk => {
      output += chunk;
      const match = output.match(/http:\/\/127\.0\.0\.1:(\d+)/);
      if (match) { clearTimeout(timeout); resolve(`http://127.0.0.1:${match[1]}`); }
    });
  });
}

test('server reports unconfigured model, rejects foreign origins, serves production build', async t => {
  const base = await startApp(t);
  const config = await fetch(`${base}/api/model`).then(r => r.json());
  assert.equal(config.configured, false);
  const result = await fetch(`${base}/api/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(result.status, 503);
  const foreign = await fetch(`${base}/api/model`, { headers: { Origin: 'http://unrelated.example' } });
  assert.equal(foreign.status, 403);
  const page = await fetch(base);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Drone Duet/);
});

test('model adapter validates observations and model output without disclosing credentials', async t => {
  let mode = 'valid', captured;
  const mock = http.createServer(async (req, res) => {
    let raw = ''; for await (const chunk of req) raw += chunk;
    captured = { body: JSON.parse(raw), auth: req.headers.authorization };
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ model: 'test-lfm3', choices: [{ message: { content: mode === 'valid' ? '{"move":"mirror","reason":"Echo the partner."}' : '{"move":"takeoff","reason":"invalid"}' } }] }));
  });
  mock.listen(0, '127.0.0.1'); await once(mock, 'listening');
  t.after(() => mock.close());
  const base = await startApp(t, { DUET_MODEL_BASE_URL: `http://127.0.0.1:${mock.address().port}/v1`, DUET_MODEL_NAME: 'test-lfm3', DUET_MODEL_API_KEY: 'test-only-secret' });
  const configText = await fetch(`${base}/api/model`).then(r => r.text());
  assert.equal(JSON.parse(configText).configured, true);
  assert.ok(!configText.includes('test-only-secret'));
  const engine = new DuetEngine(), observation = engine.observation(engine.agents[0]);
  const request = () => fetch(`${base}/api/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(observation) });
  const response = await request();
  assert.equal(response.status, 200);
  assert.equal((await response.json()).move, 'mirror');
  assert.equal(captured.auth, 'Bearer test-only-secret');
  assert.equal(captured.body.model, 'test-lfm3');
  assert.equal(JSON.parse(captured.body.messages[1].content).partner.name, 'Sol');
  mode = 'invalid';
  const bad = await request();
  assert.equal(bad.status, 502);
  assert.ok(!(await bad.text()).includes('test-only-secret'));
  const malformed = await fetch(`${base}/api/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(malformed.status, 400);
});
