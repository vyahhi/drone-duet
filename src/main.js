import './style.css';
import { DuetEngine, TRACKS, MIN_SEPARATION } from './engine.js';
import { DanceScene } from './scene.js';
import { Soundtrack } from './audio.js';

const icons = {
  play: '<path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M8 5v14M16 5v14" stroke-width="3"/>',
  reset: '<path d="M4 10a8 8 0 1 1 1 8M4 4v6h6"/>',
  volume: '<path d="M11 5 6 9H3v6h3l5 4ZM15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14"/>',
  mute: '<path d="M11 5 6 9H3v6h3l5 4ZM16 9l6 6m0-6-6 6"/>',
  expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  trail: '<path d="M3 18c8 0 1-12 9-12s1 12 9 12"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  record: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]}</svg>`;

document.querySelector('#app').innerHTML = `
  <header class="topbar">
    <a class="brand" href="/" aria-label="Drone Duet home"><span class="brandmark"><i></i><i></i><i></i><i></i></span>drone<span class="brand-light">duet</span><span class="brand-tag">EXPERIMENT 001</span></a>
    <div class="header-right"><span class="simulation-label"><span></span> SIMULATION ONLY</span><button id="about-button" class="quiet-button">About the experiment ${icon('info')}</button></div>
  </header>
  <main>
    <section class="intro">
      <div><p class="eyebrow"><span class="tiny-line"></span>A STUDY IN AUTONOMOUS CHOREOGRAPHY</p><h1>It takes two<span class="mint">.</span></h1><p class="subtitle">Two independent minds. One shared rhythm. A dance that unfolds on its own.</p></div>
      <div class="session"><span class="live-dot"></span><span>LIVE SESSION</span><strong id="session-time">00:00</strong></div>
    </section>
    <div class="workspace">
      <section class="stage-card" aria-label="Live dance simulation">
        <div class="stage-top"><div class="stage-heading"><span class="live-dot"></span><span id="stage-status">THE DANCE FLOOR</span><span class="stage-divider"></span><span class="stage-detail">3D / LIVE</span></div><button id="fullscreen" class="stage-icon" aria-label="Enter fullscreen" title="Fullscreen">${icon('expand')}</button></div>
        <div id="scene"><div class="scene-glow"></div><div id="drone-labels"></div><div id="render-error" class="render-error" hidden><strong>3D rendering is unavailable.</strong><p>Enable hardware acceleration in your browser and reload.</p></div></div>
        <div class="scene-caption"><span class="coordinate">Y ↑<span>X →</span></span><span>DRAG TO ORBIT <b>·</b> SCROLL TO EXPLORE</span></div>
        <div class="stage-bottom"><div class="view-picker" role="group" aria-label="Camera view"><button class="active" data-view="orbit">Perspective</button><button data-view="top">Top</button><button data-view="front">Front</button></div><div class="stage-bottom-right"><span id="separation"><i></i> SEPARATION GUARDED</span><button id="trails" class="stage-icon active" aria-label="Toggle motion trails" aria-pressed="true" title="Motion trails">${icon('trail')}</button></div></div>
      </section>
      <aside class="sidebar">
        <div class="panel-heading"><h2>Meet the minds</h2><span>02 AGENTS</span></div>
        <article class="agent-card ari"><div class="agent-top"><span class="agent-avatar"><span>✳</span></span><div><h3>Ari <span>01</span></h3><p>The explorer</p></div><span class="autonomous-tag">AUTONOMOUS</span></div><div class="move-line"><span>CURRENT PHRASE</span><strong id="ari-move">Orbit</strong></div><p class="agent-thought" id="ari-thought">“An opening invitation. Let’s find our rhythm.”</p><div class="agent-footer"><span><i></i><span id="ari-source">LOCAL AGENT</span></span><span id="ari-next">NEXT IN 8 BEATS</span></div></article>
        <article class="agent-card sol"><div class="agent-top"><span class="agent-avatar"><span>✳</span></span><div><h3>Sol <span>02</span></h3><p>The connector</p></div><span class="autonomous-tag">AUTONOMOUS</span></div><div class="move-line"><span>CURRENT PHRASE</span><strong id="sol-move">Mirror</strong></div><p class="agent-thought" id="sol-thought">“Watching Ari. Finding a way to answer.”</p><div class="agent-footer"><span><i></i><span id="sol-source">LOCAL AGENT</span></span><span id="sol-next">NEXT IN 4 BEATS</span></div></article>
        <section class="conversation"><div class="panel-heading"><h2>The conversation</h2><span class="conversation-symbol">↗</span></div><p class="conversation-hint">Movement is their language.</p><ol id="decision-log" aria-label="Recent autonomous decisions"></ol><div class="conversation-empty" id="conversation-empty"><span class="conversation-line"></span><p>Watching. Listening. Finding a rhythm.</p></div></section>
      </aside>
    </div>
    <section class="transport" aria-label="Dance controls">
      <div class="playback"><button id="play-pause" class="play-button" aria-label="Pause dance">${icon('pause')}</button><button id="reset" class="quiet-icon" aria-label="Start a new duet" title="New duet">${icon('reset')}</button><div class="track-info"><span class="eyebrow">ORIGINAL GENERATIVE SCORE</span><label class="sr-only" for="track-select">Soundtrack</label><select id="track-select">${Object.entries(TRACKS).map(([id, track]) => `<option value="${id}">${track.name}</option>`).join('')}</select><span id="track-genre">DOWNTEMPO / SYNTH</span></div></div>
      <div class="beat-section"><div class="beat-meta"><span>SHARED PULSE</span><strong><span id="bpm">96</span> <small>BPM</small></strong></div><div id="beat-dots" class="beat-dots">${Array.from({ length: 8 }, () => '<i></i>').join('')}</div><span id="bar-number">BAR 01</span></div>
      <div class="transport-right"><button id="sound" class="sound-button" aria-pressed="false">${icon('mute')}<span>Enable sound</span></button><div class="control-divider"></div><button id="record" class="quiet-icon" aria-label="Record dance video" title="Record 3D scene (up to 60 seconds)" aria-pressed="false">${icon('record')}</button><button id="export" class="quiet-icon" aria-label="Export session data" title="Export session JSON">${icon('download')}</button></div>
    </section>
    <section class="metrics" aria-label="Live dance metrics"><div><span class="metric-label">RHYTHM AFFINITY ${icon('info')}</span><strong><span id="sync">—</span><small>%</small><svg id="sync-spark" viewBox="0 0 100 24" width="100" height="24" aria-hidden="true"><path d="M0 12H100"/></svg></strong><p>Rolling speed correlation</p></div><div><span class="metric-label">PARTNER DISTANCE</span><strong><span id="distance">4.60</span><small>m</small></strong><p>Minimum separation ${MIN_SEPARATION.toFixed(2)} m</p></div><div><span class="metric-label">CREATIVE VOCABULARY</span><strong><span id="vocabulary">02</span><small>/ 06 moves</small><span class="vocab-dots" id="vocab-dots">${Array.from({ length: 6 }, (_, i) => `<i class="${i < 2 ? 'lit' : ''}"></i>`).join('')}</span></strong><p>Distinct moves explored this session</p></div><div><span class="metric-label">DECISIONS MADE</span><strong id="decisions">00</strong><p>Independently, every eight beats</p></div></section>
    <footer><span><span class="footer-dot"></span> NO PILOT. NO SCRIPT. JUST A CONVERSATION.</span><div><button id="model-button">Local autonomy ${icon('arrow')}</button><span>SUNDAI / NOV 2026</span></div></footer>
  </main>
  <dialog id="about-dialog"><div class="dialog-header"><span class="eyebrow">EXPERIMENT 001</span><button class="quiet-icon close-dialog" aria-label="Close about">${icon('close')}</button></div><h2>A dance between minds.</h2><p>Ari and Sol share a beat clock, but choose their own dance phrases. Ari favors novelty. Sol favors complementary responses. Each observes the other’s current move and motion before deciding.</p><p>A separate controller turns their choices into smooth trajectories and maintains ${MIN_SEPARATION.toFixed(2)} metres of separation. The simulation starts on its own; sound is optional.</p><div class="dialog-note"><strong>What’s autonomous?</strong><p>The choice and sequence of moves. The six movement primitives are designed; this is not learned flight control or real hardware. “Rhythm affinity” maps rolling speed correlation onto a 0–100 scale, not a measure of artistic quality.</p></div><p class="small-copy">Procedural 3D models inspired by the Ryze Tello. Original synthesized soundtrack. No microphone or physical drone connection.</p><button class="primary-button close-dialog">Back to the dance ${icon('arrow')}</button></dialog>
  <dialog id="model-dialog"><div class="dialog-header"><span class="eyebrow">THE DECISION LAYER</span><button class="quiet-icon close-dialog" aria-label="Close model settings">${icon('close')}</button></div><h2>Choose their minds.</h2><p>Local agents use independent scoring policies: partner response, novelty, musical energy, and a little randomness. No model download is needed.</p><div class="model-status" id="model-status"></div><p id="model-explanation"></p><button id="toggle-model" class="primary-button">Use LFM3 endpoint ${icon('arrow')}</button><p class="small-copy">Only dance state is sent to your configured endpoint. API keys stay on the server. Failed or late decisions visibly fall back to local agents.</p></dialog>
  <div id="toast" role="status"></div>
`;

const $ = id => document.getElementById(id);
const soundtrack = new Soundtrack();
let engine, scene, playing = true, seed = 42, useModel = false, generation = 0, modelConfig = { configured: false, model: 'LFM3-1.7B' };
let lastFrame = performance.now(), accumulator = 0, uiTime = 0, lastSyncSample = -1, syncValues = [], toastTimer;
let recorder, recordingTimeout;
const logItems = [];

function toast(message) { $('toast').textContent = message; $('toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('visible'), 4000); }

function onDecision(event) {
  const item = document.createElement('li');
  item.className = event.agent === 0 ? 'ari-event' : 'sol-event';
  const marker = document.createElement('i'), text = document.createElement('div'), title = document.createElement('p'), sub = document.createElement('span'), time = document.createElement('time');
  const name = document.createElement('strong'); name.textContent = event.name;
  title.append(name, document.createTextNode(` ${event.agent === 0 ? 'initiates' : 'answers with'} ${event.move}`));
  sub.textContent = event.reason; time.textContent = `${Math.floor(event.time / 60).toString().padStart(2, '0')}:${Math.floor(event.time % 60).toString().padStart(2, '0')}`;
  text.append(title, sub); item.append(marker, text, time);
  $('decision-log').prepend(item); logItems.unshift(item); if (logItems.length > 4) logItems.pop().remove();
  $('conversation-empty').hidden = true;
  refreshAgent(event.agent);
}

function refreshAgent(id) {
  const agent = engine.agents[id], prefix = id === 0 ? 'ari' : 'sol';
  $(`${prefix}-move`).textContent = agent.move[0].toUpperCase() + agent.move.slice(1);
  $(`${prefix}-thought`).textContent = `“${agent.reason}”`;
  $(`${prefix}-source`).textContent = agent.pending ? 'MODEL THINKING' : agent.source === 'model' ? 'MODEL AGENT' : agent.source === 'fallback' ? 'LOCAL FALLBACK' : 'LOCAL AGENT';
}

function newEngine() {
  const track = engine?.track || 'liquid';
  generation++;
  engine = new DuetEngine({ seed, track, onDecision });
  scene?.resetTrails();
  logItems.splice(0).forEach(item => item.remove());
  $('conversation-empty').hidden = false;
  syncValues = []; lastSyncSample = -1; accumulator = 0;
  [0, 1].forEach(refreshAgent);
}
newEngine();

function decide(agent, currentEngine) {
  if (!useModel) { currentEngine.record(agent, agent.choose(currentEngine.agents[1 - agent.id], currentEngine.music), 'local'); return; }
  if (agent.pending) return;
  agent.pending = true; refreshAgent(agent.id);
  const version = generation, requestedBeat = currentEngine.beat;
  fetch('/api/decide', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(currentEngine.observation(agent)), signal: AbortSignal.timeout(11000) })
    .then(async response => {
      if (!response.ok) throw new Error('Model unavailable');
      return response.json();
    })
    .then(decision => {
      if (version !== generation || !useModel) return;
      if (currentEngine.beat - requestedBeat > 8) throw new Error('Late model decision');
      currentEngine.record(agent, decision, 'model');
    })
    .catch(() => {
      if (version !== generation || !useModel) return;
      currentEngine.record(agent, agent.choose(currentEngine.agents[1 - agent.id], currentEngine.music), 'fallback');
      toast('Model decision unavailable. Local agent takes this phrase.');
    })
    .finally(() => { if (version === generation) { agent.pending = false; refreshAgent(agent.id); } });
}

try { scene = new DanceScene($('scene'), $('drone-labels')); }
catch (error) { console.error('3D initialization failed:', error); $('render-error').hidden = false; playing = false; }
document.addEventListener('duet-render-error', () => { playing = false; $('render-error').hidden = false; updatePlaying(); });

function updatePlaying() {
  $('play-pause').innerHTML = icon(playing ? 'pause' : 'play');
  $('play-pause').setAttribute('aria-label', playing ? 'Pause dance' : 'Resume dance');
  $('stage-status').textContent = playing ? 'THE DANCE FLOOR' : 'A MOMENT OF STILLNESS';
  document.body.classList.toggle('paused', !playing);
  if (!playing) soundtrack.context?.suspend();
  else if (soundtrack.enabled) soundtrack.context?.resume();
}
$('play-pause').addEventListener('click', () => { playing = !playing; updatePlaying(); });
$('reset').addEventListener('click', () => { seed++; newEngine(); playing = Boolean(scene); updatePlaying(); toast('A new conversation begins.'); });
$('track-select').addEventListener('change', e => {
  engine.track = e.target.value;
  $('bpm').textContent = engine.music.bpm; $('track-genre').textContent = engine.music.genre;
  soundtrack.nextBeat = 0;
  toast(`Now dancing to ${engine.music.name}.`);
});
$('sound').addEventListener('click', async () => {
  try {
    if (soundtrack.enabled) soundtrack.disable(); else { await soundtrack.enable(); if (!playing) await soundtrack.context.suspend(); }
    $('sound').innerHTML = `${icon(soundtrack.enabled ? 'volume' : 'mute')}<span>${soundtrack.enabled ? 'Sound on' : 'Enable sound'}</span>`;
    $('sound').setAttribute('aria-pressed', String(soundtrack.enabled));
  } catch { toast('Audio could not start. The dance continues silently.'); }
});
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  scene?.setView(button.dataset.view);
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active', b === button));
}));
$('trails').addEventListener('click', () => {
  if (!scene) return;
  scene.trailVisible = !scene.trailVisible;
  $('trails').classList.toggle('active', scene.trailVisible); $('trails').setAttribute('aria-pressed', String(scene.trailVisible));
});
$('fullscreen').addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.querySelector('.stage-card').requestFullscreen();
  } catch { toast('Fullscreen is unavailable in this browser.'); }
});
$('export').addEventListener('click', () => {
  const data = { format: 'drone-duet-session-v1', seed: engine.seed, simulatedSeconds: engine.time, track: engine.track, mode: useModel ? modelConfig.model : 'local-agents', minimumSeparation: engine.minDistance, guardActivations: engine.guardActivations, agents: engine.agents.map(a => ({ name: a.name, role: a.role, position: a.pos, moves: a.visits, decisions: a.decisions })), decisions: engine.history };
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = `drone-duet-${Date.now()}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('Session exported.');
});
$('record').addEventListener('click', () => {
  if (recorder?.state === 'recording') { recorder.stop(); return; }
  if (!scene || !window.MediaRecorder || !scene.renderer.domElement.captureStream) { toast('Video recording is unavailable in this browser.'); return; }
  try {
    const stream = scene.renderer.domElement.captureStream(30), chunks = [];
    const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4'].find(type => MediaRecorder.isTypeSupported(type));
    const sessionRecorder = new MediaRecorder(stream, mimeType ? { mimeType, videoBitsPerSecond: 6000000 } : {});
    recorder = sessionRecorder;
    sessionRecorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    sessionRecorder.onstop = () => {
      clearTimeout(recordingTimeout); stream.getTracks().forEach(track => track.stop());
      const type = sessionRecorder.mimeType, url = URL.createObjectURL(new Blob(chunks, { type }));
      const link = document.createElement('a'); link.href = url; link.download = `drone-duet-${Date.now()}.${type.includes('mp4') ? 'mp4' : 'webm'}`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      $('record').setAttribute('aria-pressed', 'false'); $('record').setAttribute('aria-label', 'Record dance video');
      toast('Dance video saved (3D scene, without audio).');
    };
    sessionRecorder.start(); $('record').setAttribute('aria-pressed', 'true'); $('record').setAttribute('aria-label', 'Stop recording');
    recordingTimeout = setTimeout(() => { if (sessionRecorder.state === 'recording') sessionRecorder.stop(); }, 60000);
    toast('Recording the 3D scene. Click again to save; maximum 60 seconds.');
  } catch { toast('Video recording could not start.'); }
});
$('about-button').addEventListener('click', () => $('about-dialog').showModal());
$('model-button').addEventListener('click', () => { refreshModelDialog(); $('model-dialog').showModal(); });
document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } }));

function refreshModelDialog() {
  $('model-status').textContent = modelConfig.configured ? `Configured model: ${modelConfig.model}` : 'Local autonomy is ready · Model endpoint not configured';
  $('model-explanation').textContent = modelConfig.configured ? 'Enable the configured endpoint to let a language model select each drone’s next move.' : 'To connect LFM3, copy .env.example to .env, set your OpenAI-compatible model endpoint and exact model identifier, then restart the server. See the README for setup.';
  $('toggle-model').disabled = !modelConfig.configured;
  $('toggle-model').innerHTML = `${useModel ? 'Use local agents' : 'Use configured model'} ${icon('arrow')}`;
}
$('toggle-model').addEventListener('click', () => {
  useModel = !useModel;
  generation++;
  engine.agents.forEach(agent => { agent.pending = false; });
  $('model-button').innerHTML = `${useModel ? 'Model autonomy' : 'Local autonomy'} ${icon('arrow')}`;
  refreshModelDialog(); $('model-dialog').close(); toast(useModel ? `Connected choreography to ${modelConfig.model}.` : 'Local autonomous agents are dancing.');
});
fetch('/api/model').then(r => r.json()).then(config => { modelConfig = config; }).catch(() => {});

function updateUI() {
  $('session-time').textContent = `${Math.floor(engine.time / 60).toString().padStart(2, '0')}:${Math.floor(engine.time % 60).toString().padStart(2, '0')}`;
  $('bar-number').textContent = `BAR ${String(Math.floor(engine.beat / 4) + 1).padStart(2, '0')}`;
  [...$('beat-dots').children].forEach((dot, i) => dot.classList.toggle('on', i === Math.floor(engine.beat) % 8));
  $('distance').textContent = engine.distance.toFixed(2);
  $('sync').textContent = engine.time > 2 ? Math.round(engine.sync) : '—';
  const vocab = new Set(engine.agents.flatMap(a => Object.entries(a.visits).filter(([, n]) => n).map(([m]) => m))).size;
  $('vocabulary').textContent = String(vocab).padStart(2, '0');
  [...$('vocab-dots').children].forEach((dot, i) => dot.classList.toggle('lit', i < vocab));
  $('decisions').textContent = String(engine.agents.reduce((s, a) => s + a.decisions, 0)).padStart(2, '0');
  engine.agents.forEach((a, i) => $(`${i === 0 ? 'ari' : 'sol'}-next`).textContent = a.pending ? 'CHOOSING A PHRASE' : `NEXT IN ${Math.max(1, Math.ceil(a.nextDecisionBeat - engine.beat))} BEATS`);
  if (engine.time - lastSyncSample > 0.3) {
    lastSyncSample = engine.time; syncValues.push(engine.sync); if (syncValues.length > 40) syncValues.shift();
    $('sync-spark').querySelector('path').setAttribute('d', syncValues.map((v, i) => `${i === 0 ? 'M' : 'L'}${i / Math.max(1, syncValues.length - 1) * 100} ${23 - v * 0.22}`).join(' '));
  }
}

function animate(now) {
  const dt = Math.min((now - lastFrame) / 1000, 0.08); lastFrame = now;
  if (playing && !document.hidden) {
    accumulator += dt;
    while (accumulator >= 1 / 60) { engine.step(1 / 60, decide); accumulator -= 1 / 60; }
    soundtrack.tick(engine.music, playing, engine.beat);
  }
  scene?.render(engine, playing, dt);
  if (now - uiTime > 100) { updateUI(); uiTime = now; }
  requestAnimationFrame(animate);
}
updatePlaying(); requestAnimationFrame(animate);
document.addEventListener('visibilitychange', () => {
  lastFrame = performance.now(); accumulator = 0;
  if (document.hidden) soundtrack.context?.suspend();
  else if (soundtrack.enabled && playing) soundtrack.context?.resume();
});
window.addEventListener('keydown', e => {
  if (e.code === 'Space' && !['BUTTON', 'SELECT', 'INPUT', 'TEXTAREA'].includes(document.activeElement.tagName) && !document.querySelector('dialog[open]')) { e.preventDefault(); playing = !playing; updatePlaying(); }
});
