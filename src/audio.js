// Original procedural soundtrack. No microphone, uploads, or external audio files.
export class Soundtrack {
  constructor() { this.enabled = false; this.context = null; this.nextBeat = 0; this.index = 0; }
  async enable() {
    this.context ||= new AudioContext();
    await this.context.resume();
    if (!this.master) {
      this.master = this.context.createGain();
      this.master.gain.value = 0.28;
      this.master.connect(this.context.destination);
    }
    this.enabled = true;
    this.nextBeat = 0;
  }
  disable() { this.enabled = false; this.context?.suspend(); }
  tick(music, playing, beat = 0) {
    if (!this.enabled || !this.context || !playing) return;
    const now = this.context.currentTime;
    if (!this.nextBeat || this.nextBeat < now - 0.2) {
      this.index = Math.floor(beat) + 1;
      this.nextBeat = now + (this.index - beat) * 60 / music.bpm;
    }
    while (this.nextBeat < now + 0.1) {
      this.schedule(this.nextBeat, this.index++, music);
      this.nextBeat += 60 / music.bpm;
    }
  }
  tone(time, frequency, duration, type, volume) {
    const ctx = this.context, osc = ctx.createOscillator(), gain = ctx.createGain();
    osc.type = type; osc.frequency.value = frequency;
    gain.gain.setValueAtTime(0, time);
    gain.gain.linearRampToValueAtTime(volume, time + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.001, time + duration);
    osc.connect(gain); gain.connect(this.master); osc.start(time); osc.stop(time + duration + 0.05);
    osc.onended = () => { osc.disconnect(); gain.disconnect(); };
  }
  schedule(time, beat, music) {
    const ctx = this.context, quarter = 60 / music.bpm;
    const chords = [1, 0.7937, 1.1892, 0.8909];
    const root = music.key * chords[Math.floor(beat / 16) % 4];
    if (beat % 4 === 0) {
      const osc = ctx.createOscillator(), g = ctx.createGain();
      osc.frequency.setValueAtTime(110, time); osc.frequency.exponentialRampToValueAtTime(38, time + 0.18);
      g.gain.setValueAtTime(0.65, time); g.gain.exponentialRampToValueAtTime(0.001, time + 0.28);
      osc.connect(g); g.connect(this.master); osc.start(time); osc.stop(time + 0.3);
      osc.onended = () => { osc.disconnect(); g.disconnect(); };
    }
    const notes = [1, 1.5, 2, 1.25, 1.5, 2, 2.5, 1.5];
    this.tone(time, root * notes[beat % 8], quarter * 1.7, 'sine', 0.18);
    if (beat % 8 === 0) {
      for (const n of [1, 1.25, 1.5]) this.tone(time, root * n / 2, quarter * 7.5, 'triangle', 0.045);
    }
    if (music.energy > 0.7) this.tone(time + quarter / 2, root * 4 * notes[(beat + 3) % 8], quarter * 0.5, 'sine', 0.06);
  }
}
