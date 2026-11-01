import test from 'node:test';
import assert from 'node:assert/strict';
import { DanceAgent, DuetEngine, MIN_SEPARATION, MOVES, TRACKS, seededRandom } from '../src/engine.js';

test('agents make independent, staggered decisions and explore the vocabulary', () => {
  const events = [];
  const engine = new DuetEngine({ seed: 42, onDecision: event => events.push(event) });
  for (let i = 0; i < 60 * 120; i++) engine.step(1 / 60);
  assert.equal(events[0].name, 'Sol');
  assert.equal(events[1].name, 'Ari');
  assert.ok(events[0].beat < events[1].beat);
  assert.ok(engine.agents.every(a => a.decisions > 10));
  assert.ok(new Set(events.map(e => e.move)).size >= 5);
  assert.ok(events.every(event => MOVES.includes(event.move)));
});

test('partner observation changes the connector’s decision with identical randomness', () => {
  const a = new DanceAgent(1, seededRandom(7)), b = new DanceAgent(1, seededRandom(7));
  const decisionA = a.choose({ name: 'Ari', move: 'orbit' }, TRACKS.liquid);
  const decisionB = b.choose({ name: 'Ari', move: 'ripple' }, TRACKS.liquid);
  assert.notEqual(decisionA.move, decisionB.move);
});

test('separation and finite, bounded motion hold across all tracks and seeds', () => {
  for (const track of Object.keys(TRACKS)) for (const seed of [1, 42, 2026]) {
    const engine = new DuetEngine({ seed, track });
    for (let i = 0; i < 60 * 180; i++) {
      engine.step(1 / 60);
      assert.ok(engine.distance >= MIN_SEPARATION - 1e-8, `${track}/${seed}: clearance ${engine.distance}`);
      for (const agent of engine.agents) {
        assert.ok([...agent.pos, ...agent.vel].every(Number.isFinite));
        assert.ok(Math.hypot(...agent.vel) <= 2.100001);
        assert.ok(Math.abs(agent.pos[0]) < 5 && Math.abs(agent.pos[2]) < 5);
        assert.ok(agent.pos[1] >= 0.79 && agent.pos[1] <= 4.01);
      }
      assert.ok(engine.sync >= 0 && engine.sync <= 100);
    }
  }
});

test('guard resolves an overlapping initial condition without NaNs', () => {
  const engine = new DuetEngine();
  engine.agents[0].pos = [0, 2, 0]; engine.agents[1].pos = [0, 2, 0];
  engine.step(1 / 60);
  assert.ok(engine.distance >= MIN_SEPARATION);
  assert.ok(engine.guardActivations > 0);
});

test('a seed reproduces the same decisions and motion', () => {
  const a = new DuetEngine({ seed: 108 }), b = new DuetEngine({ seed: 108 });
  for (let i = 0; i < 3600; i++) { a.step(1 / 60); b.step(1 / 60); }
  assert.deepEqual(a.agents.map(x => x.pos), b.agents.map(x => x.pos));
  assert.deepEqual(a.history, b.history);
});

test('invalid high-level model actions cannot enter the controller', () => {
  const engine = new DuetEngine();
  assert.throws(() => engine.record(engine.agents[0], { move: 'takeoff', reason: 'bad move' }, 'model'), /Unknown dance move/);
  assert.equal(engine.agents[0].move, 'orbit');
});
