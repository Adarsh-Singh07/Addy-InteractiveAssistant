/**
 * voice.js — Main voice session controller.
 *
 * Captures microphone audio (PCM for Gemini Live or WebM for Cascaded Fallback),
 * communicates with the FastAPI backend WebSocket, handles barge-in interrupts,
 * updates UI metrics, and drives the real-time audio-reactive Canvas orb visualizer.
 */

// Resolve backend URLs from window.API_BASE or fallback to host location
const API_BASE = window.API_BASE || (
  window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8001'
    : window.location.origin
);

const wsProtocol = API_BASE.startsWith('https:') ? 'wss:' : 'ws:';
const wsHostPart = API_BASE.replace(/^https?:\/\//, '');
const BASE_WS_URL = `${wsProtocol}//${wsHostPart}/ws/voice`;


// ── State variables ──────────────────────────────────────────────────────────
let ws = null;
let audioStream = null;
let isListening = false;
let agentState = 'idle'; // idle | listening | thinking | speaking | interrupted | connecting | error

// Active parameters
let selectedCharacter = 'addy';
let selectedModel = 'gemini-3.1-flash-live-preview';
let selectedVoice = 'Aoede';
let selectedThinkingLevel = 'minimal';
let selectedAffective = false;
let selectedEngine = 'gemini_live'; // gemini_live | cascaded
let isAdminAuthenticated = false;


// Web Audio API context for raw mic capture and VAD
let captureContext = null;
let micSource = null;
let micAnalyser = null;
let scriptProcessor = null;
let mediaRecorder = null; // Used as fallback for cascaded mode

// Visualizer animation frame
let animFrameId = null;

// VAD barge-in cooldown — prevent spam interrupts
let lastInterruptTime = 0;
const INTERRUPT_COOLDOWN_MS = 1500;

// WebSocket reconnect state
let reconnectTimeout = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// VAD activity tracking — for activity_start / activity_end signals
let vadUserSpeaking = false;         // true while user is talking
let vadSilenceFrames = 0;            // consecutive silent frames after speech
const VAD_SPEECH_THRESHOLD = 0.025; // RMS above = speech
const VAD_SILENCE_THRESHOLD = 0.012;// RMS below = silence
const VAD_SILENCE_FRAMES_END = 18;  // ~18×128ms = ~2.3s silence → activity_end
                                     // Lower = faster STT, higher = catches trailing words

// AudioPlayer instance
window.audioPlayer = new AudioPlayer();

// ── DOM Elements ─────────────────────────────────────────────────────────────
const micBtn        = document.getElementById('mic-btn');
const micIcon       = document.getElementById('mic-icon');
const micHint       = document.getElementById('mic-hint');
const statusValue   = document.getElementById('status-value');
const connBadge     = document.getElementById('connection-badge');
const connDot       = document.getElementById('conn-dot');
const connLabel     = document.getElementById('conn-label');
const interimText   = document.getElementById('interim-text');
const transcriptEl  = document.getElementById('transcript-scroll');
const providerStrip = document.getElementById('provider-strip');

// Segmented controls
const btnCharAddy   = document.getElementById('btn-char-addy');
const btnCharNova   = document.getElementById('btn-char-nova');
const btnCharAtlas  = document.getElementById('btn-char-atlas');
const btnModel31    = document.getElementById('btn-model-31');
const btnModel25    = document.getElementById('btn-model-25');

// Admin elements
const adminToggleBtn     = document.getElementById('admin-toggle-btn');
const adminLoginModal    = document.getElementById('admin-login-modal');
const adminModalClose    = document.getElementById('admin-modal-close');
const adminPasscodeInput = document.getElementById('admin-passcode-input');
const adminSubmitBtn     = document.getElementById('admin-submit-btn');
const adminLoginError    = document.getElementById('admin-login-error');


// Form controls
const voiceSelect         = document.getElementById('voice-select');
const thinkingLevelSelect = document.getElementById('thinking-level-select');
const affectiveCheckbox   = document.getElementById('affective-checkbox');
const engineSelect        = document.getElementById('engine-select');

// Advanced fields visibility containers
const rowThinkingLevel = document.getElementById('row-thinking-level');
const rowAffective     = document.getElementById('row-affective');

// Session Controls
const btnMute       = document.getElementById('btn-mute');
const btnInterrupt  = document.getElementById('btn-interrupt');
const btnClear      = document.getElementById('btn-clear');

// Latency board
const latencyE2e    = document.getElementById('latency-e2e');
const latencyStt    = document.getElementById('latency-stt');
const latencyLlm    = document.getElementById('latency-llm');
const latencyTts    = document.getElementById('latency-tts');

let currentAssistantBubble = null;

// ── Initialize App ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  updateUIForModelCapabilities();
  checkAdminStatus().then(() => {
    connectWebSocket();
  });
  startOrbAnimation();
});


// ── WebSocket Connection ─────────────────────────────────────────────────────
function connectWebSocket() {
  if (ws) {
    // Prevent old socket events from triggering reconnects or status updates
    ws.onopen = null;
    ws.onclose = null;
    ws.onerror = null;
    ws.onmessage = null;
    try {
      ws.close();
    } catch (e) {}
    ws = null;
  }

  setConnStatus('connecting');
  setStatus('connecting', 'Connecting WebSocket…');

  // Build query string
  const query = `character=${selectedCharacter}&model=${selectedModel}&voice=${selectedVoice}&engine=${selectedEngine}`;
  const url = `${BASE_WS_URL}?${query}`;
  logInfo(`Connecting WS: ${url}`);

  ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    setConnStatus('connected');
    setStatus('idle', 'Ready');
    reconnectAttempts = 0;
    logInfo('WebSocket opened successfully');
  };

  ws.onclose = (event) => {
    setConnStatus('disconnected');
    logInfo(`WebSocket closed (code: ${event.code}, reason: ${event.reason || 'none'})`);
    // Don't stop listening — attempt to reconnect automatically
    // so the user doesn't have to refresh the page
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS && event.code !== 1000) {
      const delay = Math.min(1000 * Math.pow(1.5, reconnectAttempts), 8000);
      reconnectAttempts++;
      setStatus('connecting', `Reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})…`);
      logInfo(`Auto-reconnect in ${(delay/1000).toFixed(1)}s (attempt ${reconnectAttempts})`);
      reconnectTimeout = setTimeout(() => {
        connectWebSocket();
        // Re-start audio if it was active
        if (isListening) {
          stopListening();
          startListening();
        }
      }, delay);
    } else {
      setStatus('error', 'Disconnected — refresh to reconnect');
      stopListening();
    }
  };

  ws.onerror = (err) => {
    console.error('WebSocket connection error:', err);
    setConnStatus('error');
    setStatus('error', 'WebSocket Error');
  };

  ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      // Received raw binary audio chunk from backend
      const bytes = new Uint8Array(event.data);
      window.audioPlayer.enqueue(bytes);
    } else {
      // Received JSON event
      try {
        const payload = JSON.parse(event.data);
        handleServerEvent(payload);
      } catch (err) {
        console.error('Failed to parse JSON server message:', err);
      }
    }
  };
}

// ── Event Handlers ───────────────────────────────────────────────────────────
function handleServerEvent(event) {
  logInfo(`Received event type: ${event.type}`);

  switch (event.type) {
    case 'status': {
      // Backend sends flat: {type: 'status', state: 'listening'} (no payload wrapper)
      const st = event.state || event.payload?.state || 'idle';
      setStatus(st, st.charAt(0).toUpperCase() + st.slice(1));
      break;
    }

    case 'transcript': {
      // Backend sends flat: {type: 'transcript', text: '...', is_final: bool}
      const payload = event.text !== undefined ? event : (event.payload || {});
      handleTranscript(payload);
      break;
    }

    case 'response_token': {
      // Backend sends flat: {type: 'response_token', token: '...'}
      const tok = event.token || event.payload?.token || '';
      if (tok) appendResponseToken(tok);
      break;
    }

    case 'response_complete':
      currentAssistantBubble = null;
      setStatus('listening', 'Listening');
      break;

    case 'interrupted':
      logInfo('Interrupted event received from server. Stopping player.');
      window.audioPlayer.stop();
      currentAssistantBubble = null;
      setStatus('listening', 'Listening');
      break;

    case 'metrics': {
      // Backend sends flat: {type: 'metrics', total_duration: ..., ...}
      updateMetrics(event.payload || event);
      break;
    }

    case 'error': {
      const errMsg = event.message || event.payload?.message || 'Unknown error';
      logInfo(`Error from server: ${errMsg}`);
      setStatus('error', errMsg.substring(0, 60));
      break;
    }

    case 'pong':
      break; // keepalive reply, no action needed

    default:
      logInfo(`Unhandled event: ${JSON.stringify(event)}`);
  }
}

// ── Audio Capture & Streaming ────────────────────────────────────────────────

async function startListening() {
  if (isListening) return;

  logInfo('Requesting microphone access…');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    });

    audioStream = stream;
    playActivationTone();
    isListening = true;
    micBtn.classList.add('active');
    micIcon.textContent = '⏹️';
    micHint.textContent = 'Tap to mute / finish turn';


    // Establish AudioContext for player and mic visualizer
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;

    if (selectedEngine === 'gemini_live') {
      // Raw PCM Mode: 16kHz sample rate mono capture
      captureContext = new AudioContextClass({ sampleRate: 16000 });
      micSource = captureContext.createMediaStreamSource(stream);

      // Create mic analyser for UI reactive orb
      micAnalyser = captureContext.createAnalyser();
      micAnalyser.fftSize = 256;
      micSource.connect(micAnalyser);

      // Raw PCM script processor — do NOT connect to destination.
      // Connecting to destination would play mic audio back through speakers,
      // creating a feedback loop that triggers false VAD interrupts.
      scriptProcessor = captureContext.createScriptProcessor(2048, 1, 1);
      micSource.connect(scriptProcessor);
      // Route to a silent gain node instead of destination
      const silentGain = captureContext.createGain();
      silentGain.gain.value = 0;
      scriptProcessor.connect(silentGain);
      silentGain.connect(captureContext.destination);

      scriptProcessor.onaudioprocess = (e) => {
        if (!isListening) return;
        const inputData = e.inputBuffer.getChannelData(0); // Float32

        // ── VAD: activity_start / activity_end signals ──────────────────
        // These tell Gemini exactly when the user starts and stops talking,
        // eliminating the 2-3s silence wait for automatic turn detection.
        const rms = computeRMS(inputData);

        if (!agentState || agentState === 'listening' || agentState === 'idle') {
          if (!vadUserSpeaking && rms > VAD_SPEECH_THRESHOLD) {
            // User just started speaking
            vadUserSpeaking = true;
            vadSilenceFrames = 0;
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'activity_start' }));
            }
          } else if (vadUserSpeaking) {
            if (rms < VAD_SILENCE_THRESHOLD) {
              vadSilenceFrames++;
              if (vadSilenceFrames >= VAD_SILENCE_FRAMES_END) {
                // User stopped speaking — signal end of turn
                vadUserSpeaking = false;
                vadSilenceFrames = 0;
                if (ws && ws.readyState === WebSocket.OPEN) {
                  ws.send(JSON.stringify({ type: 'activity_end' }));
                }
              }
            } else {
              vadSilenceFrames = 0; // Reset on speech resumption
            }
          }
        } else {
          // Agent is speaking — check for barge-in
          detectBargeIn(rms);
        }

        // ── Send raw PCM bytes to backend ──────────────────────────────
        const pcmBuffer = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const sample = Math.max(-1, Math.min(1, inputData[i]));
          pcmBuffer[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(pcmBuffer.buffer);
        }
      };

      // In Gemini Live mode we play back 24kHz audio
      window.audioPlayer.setSampleRate(24000);

    } else {
      // Cascaded Fallback Mode: webm/opus MediaRecorder
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0 && ws && ws.readyState === WebSocket.OPEN) {
          e.data.arrayBuffer().then(buf => {
            ws.send(buf);
          });
        }
      };

      // Set up simple context only for mic visualizer
      captureContext = new AudioContextClass();
      micSource = captureContext.createMediaStreamSource(stream);
      micAnalyser = captureContext.createAnalyser();
      micAnalyser.fftSize = 256;
      micSource.connect(micAnalyser);

      mediaRecorder.start(250); // 250ms audio chunk slices

      // In Cascaded mode, backend sends 24kHz
      window.audioPlayer.setSampleRate(24000);
    }

  } catch (err) {
    console.error('Microphone initialization failed:', err);
    setStatus('error', 'Microphone failed');
  }
}

function stopListening() {
  if (!isListening) return;
  logInfo('Stopping audio capture');

  isListening = false;
  micBtn.classList.remove('active');
  micIcon.textContent = '🎙️';
  micHint.textContent = 'Tap the mic to start conversation';

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    try {
      mediaRecorder.stop();
    } catch (e) {}
  }
  mediaRecorder = null;

  if (scriptProcessor) {
    scriptProcessor.disconnect();
  }
  scriptProcessor = null;

  if (micSource) {
    micSource.disconnect();
  }
  micSource = null;

  if (audioStream) {
    audioStream.getTracks().forEach(track => track.stop());
  }
  audioStream = null;

  if (captureContext) {
    captureContext.close();
  }
  captureContext = null;
  micAnalyser = null;

  // Fully tear down the audio player context when user stops mic session
  window.audioPlayer.destroy();
}

// ── RMS helper ────────────────────────────────────────────────────────────────
function computeRMS(float32Samples) {
  let sum = 0;
  for (let i = 0; i < float32Samples.length; i++) {
    sum += float32Samples[i] * float32Samples[i];
  }
  return Math.sqrt(sum / float32Samples.length);
}

// ── Client-side VAD Barge-in Detection ───────────────────────────────────────
// Called with pre-computed RMS when agent is speaking.
// Only stops local audio — Gemini handles the actual interruption server-side.
function detectBargeIn(rms) {
  if (!window.audioPlayer.isPlaying) return;

  const now = Date.now();
  if (now - lastInterruptTime < INTERRUPT_COOLDOWN_MS) return;

  if (rms > VAD_SPEECH_THRESHOLD) {
    logInfo(`Barge-in detected (RMS: ${rms.toFixed(4)}). Stopping local playback.`);
    lastInterruptTime = now;
    window.audioPlayer.stop();
    vadUserSpeaking = false;
    vadSilenceFrames = 0;
  }
}

function triggerInterrupt() {
  // Stop local player immediately
  window.audioPlayer.stop();

  // Send interrupt signal to backend
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'interrupt' }));
  }

  // Update local UI state
  currentAssistantBubble = null;
  setStatus('listening', 'Interrupted');
}

// ── UI Updates & Text Appenders ──────────────────────────────────────────────

function handleTranscript(payload) {
  const { text, is_final } = payload;

  if (is_final) {
    interimText.textContent = '';
    // Append completed bubble to logs
    appendTranscriptBubble('user', text);
  } else {
    // Show live interim translation text
    interimText.textContent = text;
  }
}

function appendResponseToken(token) {
  if (!currentAssistantBubble) {
    currentAssistantBubble = appendTranscriptBubble('assistant', '');
  }

  const p = currentAssistantBubble.querySelector('.msg-bubble');
  p.textContent += token;
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function appendTranscriptBubble(sender, text) {
  const msg = document.createElement('div');
  msg.className = `msg msg-${sender}`;

  const label = document.createElement('span');
  label.className = 'msg-label';
  label.textContent = sender === 'user' ? 'You' : selectedCharacter.toUpperCase();

  const bubble = document.createElement('p');
  bubble.className = 'msg-bubble';
  bubble.textContent = text;

  msg.appendChild(label);
  msg.appendChild(bubble);

  transcriptEl.appendChild(msg);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
  return msg;
}

function updateMetrics(payload) {
  // Render calculated benchmark metrics
  const formatTime = (ts) => (ts ? (ts * 1000).toFixed(0) : '—');
  const formatDiff = (d) => (d ? (d * 1000).toFixed(0) : '—');

  if (payload.total_duration !== undefined) {
    latencyE2e.textContent = (payload.total_duration * 1000).toFixed(0);
  }

  // In Cascaded mode, specific metrics are present
  if (payload.stt_latency !== undefined) {
    latencyStt.textContent = (payload.stt_latency * 1000).toFixed(0);
  }
  if (payload.llm_latency !== undefined) {
    latencyLlm.textContent = (payload.llm_latency * 1000).toFixed(0);
  }
  if (payload.tts_latency !== undefined) {
    latencyTts.textContent = (payload.tts_latency * 1000).toFixed(0);
  }
}

// ── Setting Updates ──────────────────────────────────────────────────────────

function setupEventListeners() {
  // Mic btn click toggle
  micBtn.addEventListener('click', () => {
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  });

  // Persona buttons
  btnCharAddy.addEventListener('click', () => {
    selectCharacterPreset('addy');
  });

  btnCharNova.addEventListener('click', () => {
    selectCharacterPreset('nova');
  });

  btnCharAtlas.addEventListener('click', () => {
    if (!isAdminAuthenticated) {
      // Show admin auth modal first
      adminLoginModal.classList.remove('hidden');
      adminPasscodeInput.focus();
    } else {
      selectCharacterPreset('atlas');
    }
  });

  // Admin login actions
  adminToggleBtn.addEventListener('click', () => {
    if (isAdminAuthenticated) {
      logoutAdmin();
    } else {
      adminLoginModal.classList.remove('hidden');
      adminPasscodeInput.focus();
    }
  });

  adminModalClose.addEventListener('click', () => {
    adminLoginModal.classList.add('hidden');
    adminLoginError.classList.add('hidden');
    adminPasscodeInput.value = '';
  });

  adminSubmitBtn.addEventListener('click', () => {
    performAdminLogin();
  });

  adminPasscodeInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      performAdminLogin();
    }
  });


  // Model buttons
  btnModel31.addEventListener('click', () => {
    btnModel31.classList.add('active');
    btnModel25.classList.remove('active');
    selectedModel = 'gemini-3.1-flash-live-preview';
    updateUIForModelCapabilities();
    reconnect();
  });

  btnModel25.addEventListener('click', () => {
    btnModel25.classList.add('active');
    btnModel31.classList.remove('active');
    selectedModel = 'gemini-2.5-flash-native-audio-preview-12-2025';
    updateUIForModelCapabilities();
    reconnect();
  });

  // Dynamic selector changes
  voiceSelect.addEventListener('change', () => {
    selectedVoice = voiceSelect.value;
    sendSettingsUpdate();
  });

  thinkingLevelSelect.addEventListener('change', () => {
    selectedThinkingLevel = thinkingLevelSelect.value;
    sendSettingsUpdate();
  });

  affectiveCheckbox.addEventListener('change', () => {
    selectedAffective = affectiveCheckbox.checked;
    sendSettingsUpdate();
  });

  engineSelect.addEventListener('change', () => {
    selectedEngine = engineSelect.value;
    reconnect();
  });

  // Controls bar
  btnMute.addEventListener('click', () => {
    if (isListening) {
      stopListening();
      btnMute.textContent = '🔊 Unmute';
    } else {
      startListening();
      btnMute.textContent = '🔇 Mute';
    }
  });

  btnInterrupt.addEventListener('click', () => {
    triggerInterrupt();
  });

  btnClear.addEventListener('click', () => {
    transcriptEl.innerHTML = '';
    interimText.textContent = '';
    currentAssistantBubble = null;
  });
}

function updateUIForModelCapabilities() {
  if (selectedModel.includes('3.1')) {
    rowThinkingLevel.style.display = 'flex';
    rowAffective.style.display = 'none';
  } else {
    rowThinkingLevel.style.display = 'none';
    rowAffective.style.display = 'flex';
  }
}

function sendSettingsUpdate() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'settings',
      payload: {
        character: selectedCharacter,
        model: selectedModel,
        voice: selectedVoice,
        thinking_level: selectedThinkingLevel,
        affective_dialogue: selectedAffective,
        engine: selectedEngine
      }
    }));
  }
}

// ── Visualizer Animation Loop ────────────────────────────────────────────────

function startOrbAnimation() {
  const canvas = document.getElementById('orb-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  function render() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const cx = canvas.width / 2;
    const cy = canvas.height / 2;

    // Calculate real mic volume
    let micVolume = 0;
    if (micAnalyser && isListening) {
      const dataArray = new Uint8Array(micAnalyser.frequencyBinCount);
      micAnalyser.getByteTimeDomainData(dataArray);
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        const v = (dataArray[i] - 128) / 128;
        sum += v * v;
      }
      micVolume = Math.sqrt(sum / dataArray.length);
    }

    // Calculate real playback volume
    const playbackVolume = window.audioPlayer ? window.audioPlayer.getPlaybackVolume() : 0;
    const time = Date.now() * 0.003;

    let baseRadius = 45;
    let centerColor = '#6c8ef4';
    let glowColor = 'rgba(108, 142, 244, 0.35)';

    // Dynamic character colors
    if (selectedCharacter === 'addy') {
      centerColor = '#00e5ff';
      glowColor = 'rgba(0, 229, 255, 0.35)';
    } else if (selectedCharacter === 'nova') {
      centerColor = '#8b5cf6';
      glowColor = 'rgba(139, 92, 246, 0.35)';
    } else if (selectedCharacter === 'atlas') {
      centerColor = '#f59e0b';
      glowColor = 'rgba(245, 158, 11, 0.35)';
    }

    if (agentState === 'listening') {
      baseRadius = 45 + micVolume * 140;
      if (selectedCharacter === 'addy') {
        glowColor = `rgba(0, 229, 255, ${0.3 + micVolume * 0.7})`;
      } else if (selectedCharacter === 'nova') {
        glowColor = `rgba(139, 92, 246, ${0.3 + micVolume * 0.7})`;
      } else {
        glowColor = `rgba(245, 158, 11, ${0.3 + micVolume * 0.7})`;
      }
    } else if (agentState === 'thinking') {
      baseRadius = 50 + Math.sin(time * 2.5) * 4;
      if (selectedCharacter === 'addy') {
        glowColor = 'rgba(0, 229, 255, 0.45)';
      } else if (selectedCharacter === 'nova') {
        glowColor = 'rgba(139, 92, 246, 0.45)';
      } else {
        glowColor = 'rgba(245, 158, 11, 0.45)';
      }
    } else if (agentState === 'speaking') {
      baseRadius = 52 + playbackVolume * 160;
      if (selectedCharacter === 'addy') {
        glowColor = `rgba(0, 229, 255, ${0.4 + playbackVolume * 0.6})`;
      } else if (selectedCharacter === 'nova') {
        glowColor = `rgba(139, 92, 246, ${0.4 + playbackVolume * 0.6})`;
      } else {
        glowColor = `rgba(245, 158, 11, ${0.4 + playbackVolume * 0.6})`;
      }
    } else if (agentState === 'interrupted') {
      baseRadius = 15;
      glowColor = 'rgba(239, 68, 68, 0.2)';
      centerColor = '#ef4444';
    } else {
      // idle
      baseRadius = 45 + Math.sin(time) * 3;
    }


    // Outer glow ring
    const grad = ctx.createRadialGradient(cx, cy, baseRadius * 0.4, cx, cy, baseRadius * 2);
    grad.addColorStop(0, centerColor);
    grad.addColorStop(0.3, glowColor);
    grad.addColorStop(1, 'transparent');

    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, baseRadius * 2, 0, Math.PI * 2);
    ctx.fill();

    // Solid inner core
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(cx, cy, baseRadius * 0.5, 0, Math.PI * 2);
    ctx.fill();

    // Visual effect rings for thinking/speaking states
    if (agentState === 'thinking' || agentState === 'speaking') {
      ctx.strokeStyle = centerColor;
      ctx.lineWidth = 2.5;

      ctx.beginPath();
      ctx.arc(cx, cy, baseRadius * 0.85, time, time + Math.PI * 0.6);
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(cx, cy, baseRadius * 1.05, -time * 1.4, -time * 1.4 + Math.PI * 0.5);
      ctx.stroke();
    }

    animFrameId = requestAnimationFrame(render);
  }

  render();
}

// ── Helper Utilities ─────────────────────────────────────────────────────────

function setStatus(state, label) {
  agentState = state;
  const engineSuffix = selectedEngine === 'gemini_live' ? ' (Gemini Live)' : ' (Deepgram)';
  
  if (state === 'listening' || state === 'thinking' || state === 'speaking') {
    statusValue.textContent = label + engineSuffix;
  } else {
    statusValue.textContent = label;
  }
  statusValue.className = `status-value ${state}`;

  // Update mic button class during active play
  if (state === 'speaking') {
    micBtn.className = 'mic-btn speaking';
  } else if (isListening) {
    micBtn.className = 'mic-btn active';
  } else {
    micBtn.className = 'mic-btn';
  }
}

function setConnStatus(status) {
  connBadge.className = `connection-badge ${status}`;
  if (status === 'connected') {
    connLabel.textContent = 'Online';
  } else if (status === 'connecting') {
    connLabel.textContent = 'Connecting…';
  } else if (status === 'disconnected') {
    connLabel.textContent = 'Offline';
  } else {
    connLabel.textContent = 'Error';
  }
}

function reconnect() {
  logInfo('Reconnecting WebSocket session...');
  connectWebSocket();
}

function selectCharacterPreset(char) {
  selectedCharacter = char;
  
  // Set default voices
  if (char === 'atlas') {
    selectedVoice = 'Charon';
  } else {
    selectedVoice = 'Aoede';
  }
  if (voiceSelect) {
    voiceSelect.value = selectedVoice;
  }

  // Update UI display
  const nameEl = document.getElementById('active-char-name');
  const descEl = document.getElementById('active-char-desc');
  if (nameEl) nameEl.textContent = char.charAt(0).toUpperCase() + char.slice(1);
  if (descEl) descEl.textContent = getCharacterDesc(char);

  // Update segmented control buttons
  const chars = ['addy', 'nova', 'atlas'];
  chars.forEach(c => {
    const el = document.getElementById(`btn-char-${c}`);
    if (el) {
      if (c === char) {
        el.classList.add('active');
      } else {
        el.classList.remove('active');
      }
    }
  });

  reconnect();
}

async function checkAdminStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/auth/status`);
    if (resp.ok) {
      const data = await resp.json();
      if (data.access_mode === 'ADMIN') {
        isAdminAuthenticated = true;
        adminToggleBtn.classList.add('authenticated');
        adminToggleBtn.textContent = '🔓 Admin';
      } else {
        isAdminAuthenticated = false;
        adminToggleBtn.classList.remove('authenticated');
        adminToggleBtn.textContent = '🔑 Lock';
      }
    }
  } catch (err) {
    console.error('Failed to check admin status:', err);
  }
}

async function performAdminLogin() {
  const passcode = adminPasscodeInput.value.trim();
  if (!passcode) {
    adminLoginError.textContent = 'Please enter a passcode';
    adminLoginError.classList.remove('hidden');
    return;
  }

  try {
    const resp = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passcode })
    });

    if (resp.ok) {
      const data = await resp.json();
      if (data.access_mode === 'ADMIN') {
        isAdminAuthenticated = true;
        adminToggleBtn.classList.add('authenticated');
        adminToggleBtn.textContent = '🔓 Admin';
        
        // Hide modal and clear input
        adminLoginModal.classList.add('hidden');
        adminLoginError.classList.add('hidden');
        adminPasscodeInput.value = '';

        // Switch to Atlas
        selectCharacterPreset('atlas');
      }
    } else {
      const errData = await resp.json();
      adminLoginError.textContent = errData.detail || 'Authorization failed';
      adminLoginError.classList.remove('hidden');
    }
  } catch (err) {
    console.error('Login error:', err);
    adminLoginError.textContent = 'Connection error';
    adminLoginError.classList.remove('hidden');
  }
}

async function logoutAdmin() {
  try {
    const resp = await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' });
    if (resp.ok) {
      isAdminAuthenticated = false;
      adminToggleBtn.classList.remove('authenticated');
      adminToggleBtn.textContent = '🔑 Lock';
      
      // Fallback to Addy
      selectCharacterPreset('addy');
    }
  } catch (err) {
    console.error('Logout error:', err);
  }
}

function getCharacterDesc(char) {
  if (char === 'addy') return "Adarsh's AI Twin";
  if (char === 'nova') return "Concierge & Recruiter";
  if (char === 'atlas') return "AI OS Core (Admin)";
  return "Assistant";
}

function logInfo(msg) {
  console.log(`[VoiceSession] ${msg}`);
}

function playActivationTone() {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const ctx = new AudioContextClass();
    
    // Note 1: E5 (659.25 Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(659.25, ctx.currentTime);
    gain1.gain.setValueAtTime(0, ctx.currentTime);
    gain1.gain.linearRampToValueAtTime(0.08, ctx.currentTime + 0.04);
    gain1.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.3);
    
    // Note 2: B5 (987.77 Hz) slightly delayed
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(987.77, ctx.currentTime + 0.06);
    gain2.gain.setValueAtTime(0, ctx.currentTime);
    gain2.gain.setValueAtTime(0, ctx.currentTime + 0.06);
    gain2.gain.linearRampToValueAtTime(0.12, ctx.currentTime + 0.1);
    gain2.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.45);
    
    // Lowpass filter for analog warmth
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(1400, ctx.currentTime);
    
    osc1.connect(gain1);
    osc2.connect(gain2);
    gain1.connect(filter);
    gain2.connect(filter);
    filter.connect(ctx.destination);
    
    osc1.start();
    osc2.start();
    osc1.stop(ctx.currentTime + 0.4);
    osc2.stop(ctx.currentTime + 0.5);
  } catch (err) {
    console.warn('Could not play activation tone:', err);
  }
}


