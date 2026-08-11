/**
 * audio.js — Audio playback manager.
 *
 * Receives raw PCM (linear16) audio bytes from the WebSocket and plays them
 * through the Web Audio API with precise scheduling and a real-time analyser.
 */

class AudioPlayer {
  constructor() {
    this._ctx = null;
    this._nextPlayTime = 0;
    this._sampleRate = 24000;
    this._channels = 1;
    this._sources = [];
    this._analyser = null;
    this._gainNode = null;
  }

  setSampleRate(rate) {
    if (this._sampleRate !== rate) {
      logInfo(`Updating AudioPlayer sample rate to ${rate}Hz`);
      this._sampleRate = rate;
      this.stop();
    }
  }

  _ensureContext() {
    if (!this._ctx || this._ctx.state === 'closed') {
      this._ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: this._sampleRate });
      this._nextPlayTime = 0;

      // Shared node pipeline for real-time visualization
      this._analyser = this._ctx.createAnalyser();
      this._analyser.fftSize = 256;
      this._gainNode = this._ctx.createGain();

      this._gainNode.connect(this._analyser);
      this._analyser.connect(this._ctx.destination);
    }
    if (this._ctx.state === 'suspended') {
      this._ctx.resume();
    }
    return this._ctx;
  }

  /**
   * Enqueue raw PCM bytes for playback.
   * Bytes are expected as 16-bit signed integers, little-endian, mono.
   */
  enqueue(pcmBytes) {
    const ctx = this._ensureContext();

    // Convert Int16 bytes to Float32 samples
    const int16 = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, pcmBytes.byteLength / 2);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0;
    }

    const buffer = ctx.createBuffer(this._channels, float32.length, this._sampleRate);
    buffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this._gainNode);

    // Precise Web Audio scheduling to ensure gap-free playback
    const now = ctx.currentTime;
    let startTime = this._nextPlayTime;
    if (startTime < now) {
      startTime = now;
    }

    source.start(startTime);
    this._sources.push(source);

    // Advance the playback schedule timeline
    this._nextPlayTime = startTime + buffer.duration;

    // Remove source from list when it ends
    source.onended = () => {
      const idx = this._sources.indexOf(source);
      if (idx > -1) {
        this._sources.splice(idx, 1);
      }
    };
  }

  /**
   * Get real-time RMS playback volume (value between 0.0 and 1.0).
   */
  getPlaybackVolume() {
    if (!this._analyser || this._ctx?.state !== 'running') return 0;
    const dataArray = new Uint8Array(this._analyser.frequencyBinCount);
    this._analyser.getByteTimeDomainData(dataArray);

    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const v = (dataArray[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / dataArray.length);
  }

  /**
   * Stop playback immediately and cancel all scheduled buffers.
   * Called on barge-in interrupt.
   *
   * IMPORTANT: Do NOT close the AudioContext here. Closing it requires a fresh
   * user gesture to recreate (browser autoplay policy). Keep the context alive.
   */
  stop() {
    this._sources.forEach(src => {
      try {
        src.stop();
      } catch (e) {
        // Source might not have started or already finished — ignore
      }
    });
    this._sources = [];
    this._nextPlayTime = 0;
    // Reset gain node to ensure clean state
    if (this._gainNode) {
      this._gainNode.gain.setValueAtTime(1.0, this._ctx?.currentTime || 0);
    }
    // Do NOT close _ctx — we keep the AudioContext alive across interrupts
  }

  /**
   * Fully tear down the AudioContext (only call on page unload / mic stop).
   */
  destroy() {
    this.stop();
    if (this._ctx) {
      try { this._ctx.close(); } catch (e) {}
      this._ctx = null;
      this._analyser = null;
      this._gainNode = null;
    }
  }

  get isPlaying() {
    return this._sources.length > 0;
  }
}

function logInfo(msg) {
  console.log(`[AudioPlayer] ${msg}`);
}
