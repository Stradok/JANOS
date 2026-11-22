/**
 * Web Audio API cinematic ambient drone generator.
 * Creates an ominous, soothing, weighty sub-bass resonance and harmonic chime.
 */

class AudioDroneEngine {
  private ctx: AudioContext | null = null;
  private isPlaying = false;
  private masterGain: GainNode | null = null;
  private subOsc: OscillatorNode | null = null;
  private midOsc: OscillatorNode | null = null;
  private highOsc: OscillatorNode | null = null;
  private filter: BiquadFilterNode | null = null;

  public init() {
    if (this.ctx) return;
    try {
      const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new AudioContextClass();
    } catch {
      console.warn('Web Audio not supported');
    }
  }

  public start() {
    this.init();
    if (!this.ctx) return;

    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }

    if (this.isPlaying) return;
    this.isPlaying = true;

    const now = this.ctx.currentTime;

    // Master Gain with gentle fade in
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.setValueAtTime(0, now);
    this.masterGain.gain.linearRampToValueAtTime(0.35, now + 3);
    this.masterGain.connect(this.ctx.destination);

    // Lowpass filter for smooth weighty warmth
    this.filter = this.ctx.createBiquadFilter();
    this.filter.type = 'lowpass';
    this.filter.frequency.setValueAtTime(140, now);
    this.filter.Q.setValueAtTime(3.0, now);
    this.filter.connect(this.masterGain);

    // Deep Sub oscillator (55Hz - A1)
    this.subOsc = this.ctx.createOscillator();
    this.subOsc.type = 'sine';
    this.subOsc.frequency.setValueAtTime(55, now);

    const subGain = this.ctx.createGain();
    subGain.gain.setValueAtTime(0.6, now);
    this.subOsc.connect(subGain);
    subGain.connect(this.filter);
    this.subOsc.start();

    // Mid Harmonic Drone (110Hz - A2 with subtle vibrato)
    this.midOsc = this.ctx.createOscillator();
    this.midOsc.type = 'triangle';
    this.midOsc.frequency.setValueAtTime(110.3, now);

    const midGain = this.ctx.createGain();
    midGain.gain.setValueAtTime(0.25, now);
    this.midOsc.connect(midGain);
    midGain.connect(this.filter);
    this.midOsc.start();

    // High crystalline harmonic (220Hz - A3)
    this.highOsc = this.ctx.createOscillator();
    this.highOsc.type = 'sine';
    this.highOsc.frequency.setValueAtTime(220.5, now);

    const highGain = this.ctx.createGain();
    highGain.gain.setValueAtTime(0.08, now);
    this.highOsc.connect(highGain);
    highGain.connect(this.filter);
    this.highOsc.start();
  }

  public updatePhase(expansionRatio: number) {
    if (!this.ctx || !this.isPlaying || !this.filter) return;
    const now = this.ctx.currentTime;
    // As orb expands, filter frequency rises slightly to reveal harmonic overtones
    const targetFreq = 120 + expansionRatio * 220;
    this.filter.frequency.setTargetAtTime(targetFreq, now, 0.2);
  }

  public stop() {
    if (!this.ctx || !this.isPlaying || !this.masterGain) return;
    const now = this.ctx.currentTime;
    this.masterGain.gain.linearRampToValueAtTime(0.001, now + 1.2);
    setTimeout(() => {
      try {
        this.subOsc?.stop();
        this.midOsc?.stop();
        this.highOsc?.stop();
        this.subOsc?.disconnect();
        this.midOsc?.disconnect();
        this.highOsc?.disconnect();
      } catch {
        // ignore already stopped
      }
      this.isPlaying = false;
    }, 1300);
  }
}

export const audioDrone = new AudioDroneEngine();
