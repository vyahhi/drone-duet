// Simulation-only choreography. No device connection or physical flight commands.
export const MOVES = ['orbit', 'mirror', 'weave', 'ripple', 'spiral', 'solo'];
export const TRACKS = {
  liquid: { name: 'Liquid geometry', genre: 'DOWNTEMPO / SYNTH', bpm: 96, energy: 0.55, key: 146.83 },
  waltz: { name: 'Weightless', genre: 'AMBIENT / WALTZ', bpm: 72, energy: 0.35, key: 130.81 },
  neon: { name: 'After hours', genre: 'ELECTRONIC / PULSE', bpm: 124, energy: 0.85, key: 164.81 },
};
export const MIN_SEPARATION = 1.35;
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const length = v => Math.hypot(...v);
const norm = v => { const n = length(v) || 1; return v.map(x => x / n); };

export function seededRandom(seed) {
  let state = seed >>> 0;
  return () => { state += 0x6d2b79f5; let t = state; t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

const RESPONSES = {
  orbit: ['spiral', 'orbit', 'mirror'], mirror: ['ripple', 'mirror', 'weave'],
  weave: ['weave', 'orbit', 'ripple'], ripple: ['mirror', 'ripple', 'solo'],
  spiral: ['orbit', 'spiral', 'weave'], solo: ['mirror', 'orbit', 'ripple'],
};

export class DanceAgent {
  constructor(id, random) {
    this.id = id;
    this.name = id === 0 ? 'Ari' : 'Sol';
    this.role = id === 0 ? 'The explorer' : 'The connector';
    this.side = id === 0 ? -1 : 1;
    this.pos = [this.side * 2.3, 2.05, 0];
    this.vel = [0, 0, 0];
    this.acc = [0, 0, 0];
    this.move = id === 0 ? 'orbit' : 'mirror';
    this.reason = id === 0 ? 'An opening invitation. Let’s find our rhythm.' : 'Watching Ari. Finding a way to answer.';
    this.visits = Object.fromEntries(MOVES.map(m => [m, 0]));
    this.visits[this.move] = 1;
    this.random = random;
    this.decisions = 0;
    this.nextDecisionBeat = id === 0 ? 8 : 4;
    this.lastDecisionBeat = 0;
    this.source = 'local';
    this.pending = false;
    this.parameter = random() * Math.PI * 2;
  }

  choose(partner, music) {
    // Each agent evaluates its own options from partner observation + private history.
    // Ari prefers novelty; Sol gives more weight to a complementary response.
    const noveltyWeight = this.id === 0 ? 1.5 : 0.65;
    const responseWeight = this.id === 0 ? 0.75 : 1.8;
    const preferred = RESPONSES[partner.move];
    const scores = MOVES.map(move => {
      const novelty = 1 / (1 + this.visits[move]);
      const response = preferred.includes(move) ? 1 - preferred.indexOf(move) * 0.18 : 0;
      const contrast = move !== this.move ? 0.45 : -0.3;
      const energy = music.energy > 0.7 ? (['weave', 'spiral'].includes(move) ? 0.7 : 0) : (['ripple', 'mirror'].includes(move) ? 0.4 : 0);
      return { move, score: novelty * noveltyWeight + response * responseWeight + contrast + energy + this.random() * 0.8 };
    });
    scores.sort((a, b) => b.score - a.score);
    const move = scores[0].move;
    const reasons = {
      orbit: `Answering ${partner.name}’s ${partner.move} with a wide, open orbit.`,
      mirror: `Echoing ${partner.name}’s energy. Two sides of the same phrase.`,
      weave: `A little counterpoint to ${partner.name}. Crossing rhythms, separate paths.`,
      ripple: `Letting ${partner.name} lead. Sending a wave back across the floor.`,
      spiral: `Building on ${partner.name}’s ${partner.move}. Taking the phrase upward.`,
      solo: `A brief solo while ${partner.name} holds the conversation.`,
    };
    return { move, reason: reasons[move] };
  }

  applyDecision(decision, beat, source = 'local') {
    if (!MOVES.includes(decision.move)) throw new Error('Unknown dance move');
    this.move = decision.move;
    this.reason = String(decision.reason).slice(0, 180);
    this.visits[this.move]++;
    this.decisions++;
    this.lastDecisionBeat = beat;
    this.source = source;
  }

  target(beat, music) {
    const p = beat * Math.PI / 8;
    const side = this.side;
    const phase = this.id * Math.PI;
    const pulse = Math.sin(beat * Math.PI / 2);
    const energy = 0.7 + music.energy * 0.6;
    let x, y, z;
    switch (this.move) {
      case 'orbit':
        x = Math.cos(p + phase) * 2.65; z = Math.sin(p + phase) * 2.25; y = 2.2 + pulse * 0.22; break;
      case 'mirror':
        x = side * (2.0 + 0.65 * Math.sin(p)); z = 1.6 * Math.cos(p); y = 2.25 + 0.45 * Math.sin(p * 2); break;
      case 'weave':
        x = side * (1.8 + 0.7 * Math.cos(p * 2)); z = 2 * Math.sin(p); y = 2.2 + side * Math.sin(p * 2) * 0.45; break;
      case 'ripple':
        x = side * 2.2 + Math.sin(p) * 0.55; z = Math.cos(p) * 1.3; y = 2.2 + Math.sin(p * 2 + this.id * 0.8) * 0.75; break;
      case 'spiral': {
        const r = 2.15 + 0.5 * Math.sin(p * 0.5);
        x = Math.cos(p + phase) * r; z = Math.sin(p + phase) * r; y = 2.3 + Math.sin(p * 0.75 + phase) * 0.8; break;
      }
      case 'solo':
        x = side * 2.1 + Math.cos(p * 2 + this.parameter) * 0.65; z = Math.sin(p * 2) * 0.85; y = 2.3 + Math.sin(p * 3) * 0.65; break;
    }
    return [x * energy, clamp(y, 0.9, 3.8), z * energy];
  }
}

export class DuetEngine {
  constructor({ seed = 42, track = 'liquid', onDecision = () => {} } = {}) {
    this.seed = seed;
    this.random = seededRandom(seed);
    this.agents = [new DanceAgent(0, this.random), new DanceAgent(1, this.random)];
    this.track = track;
    this.time = 0;
    this.beat = 0;
    this.minDistance = Infinity;
    this.distance = 4.6;
    this.onDecision = onDecision;
    this.history = [];
    this.motionHistory = [];
    this.sync = 0;
    this.guardActivations = 0;
  }

  get music() { return TRACKS[this.track]; }

  observation(agent) {
    const partner = this.agents[1 - agent.id];
    return {
      name: agent.name, role: agent.role, beat: +this.beat.toFixed(2),
      music: this.music, position: agent.pos.map(n => +n.toFixed(2)),
      currentMove: agent.move, recentMoves: this.history.filter(h => h.agent === agent.id).slice(-4).map(h => h.move),
      partner: { name: partner.name, move: partner.move, position: partner.pos.map(n => +n.toFixed(2)), velocity: partner.vel.map(n => +n.toFixed(2)) },
      separation: +this.distance.toFixed(2), availableMoves: MOVES,
    };
  }

  record(agent, decision, source) {
    agent.applyDecision(decision, this.beat, source);
    const event = { agent: agent.id, name: agent.name, move: agent.move, reason: agent.reason, beat: this.beat, time: this.time, source };
    this.history.push(event);
    if (this.history.length > 300) this.history.shift();
    this.onDecision(event);
  }

  step(dt, decisionHandler) {
    dt = clamp(dt, 0, 1 / 30);
    this.time += dt;
    this.beat += dt * this.music.bpm / 60;
    for (const agent of this.agents) {
      if (this.beat >= agent.nextDecisionBeat) {
        agent.nextDecisionBeat = this.beat + 8;
        if (decisionHandler) decisionHandler(agent, this);
        else this.record(agent, agent.choose(this.agents[1 - agent.id], this.music), 'local');
      }
      const target = agent.target(this.beat, this.music);
      agent.acc = target.map((n, i) => (n - agent.pos[i]) * 3.3 - agent.vel[i] * 2.7);
    }

    // Predictive repulsion and a hard position constraint provide a deterministic
    // simulation guard independently of either agent or language-model output.
    const [a, b] = this.agents;
    const delta = b.pos.map((n, i) => n - a.pos[i]);
    const distance = length(delta);
    const direction = distance > 1e-8 ? norm(delta) : [1, 0, 0];
    const closing = b.vel.reduce((s, n, i) => s + (n - a.vel[i]) * direction[i], 0);
    if (distance < 2.3) {
      const force = (2.3 - distance) * 5 + Math.max(0, -closing) * 2;
      for (let i = 0; i < 3; i++) { a.acc[i] -= direction[i] * force; b.acc[i] += direction[i] * force; }
    }
    for (const agent of this.agents) {
      const accelLength = length(agent.acc);
      if (accelLength > 3.8) agent.acc = agent.acc.map(n => n * 3.8 / accelLength);
      agent.vel = agent.vel.map((v, i) => v + agent.acc[i] * dt);
      const speed = length(agent.vel);
      if (speed > 2.1) agent.vel = agent.vel.map(v => v * 2.1 / speed);
      agent.pos = agent.pos.map((v, i) => v + agent.vel[i] * dt);
      agent.pos[1] = clamp(agent.pos[1], 0.8, 4.0);
    }
    const after = b.pos.map((n, i) => n - a.pos[i]);
    const d = length(after);
    if (d < MIN_SEPARATION) {
      this.guardActivations++;
      const unit = d > 1e-8 ? norm(after) : [1, 0, 0];
      for (let i = 0; i < 3; i++) {
        const correction = unit[i] * (MIN_SEPARATION - d + 0.0001) / 2;
        a.pos[i] -= correction; b.pos[i] += correction;
      }
      const relativeClosing = b.vel.reduce((s, v, i) => s + (v - a.vel[i]) * unit[i], 0);
      if (relativeClosing < 0) for (let i = 0; i < 3; i++) {
        a.vel[i] += unit[i] * relativeClosing / 2;
        b.vel[i] -= unit[i] * relativeClosing / 2;
      }
      // The constraint impulse redistributes velocity; reapply the speed bound.
      for (const agent of this.agents) {
        const speed = length(agent.vel);
        if (speed > 2.1) agent.vel = agent.vel.map(v => v * 2.1 / speed);
      }
    }
    this.distance = length(b.pos.map((v, i) => v - a.pos[i]));
    this.minDistance = Math.min(this.minDistance, this.distance);
    this.motionHistory.push([length(a.vel), length(b.vel)]);
    if (this.motionHistory.length > 480) this.motionHistory.shift();
    if (this.motionHistory.length > 30) {
      const n = this.motionHistory.length;
      const mean = [0, 1].map(k => this.motionHistory.reduce((s, v) => s + v[k], 0) / n);
      let cov = 0, va = 0, vb = 0;
      for (const v of this.motionHistory) { const x = v[0] - mean[0], y = v[1] - mean[1]; cov += x * y; va += x * x; vb += y * y; }
      const correlation = va * vb > 1e-10 ? cov / Math.sqrt(va * vb) : 0;
      this.sync = clamp((correlation + 1) * 50, 0, 100);
    }
  }
}
