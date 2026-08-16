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

// Local VAD state for Echo-Aware Barge-In
const PRE_ROLL_MAX_FRAMES = 5; // ~640ms at 2048 samples / 16kHz
let preRollBuffer = [];
let localBargeInActive = false;

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

// Public read-only bridge for the independent Three.js visualizer.
window.getAddyVisualState = () => ({
  state: agentState,
  character: selectedCharacter,
  isListening,
  micAnalyser,
  playbackVolume: window.audioPlayer ? window.audioPlayer.getPlaybackVolume() : 0,
});

// ── Initialize App ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  updateUIForModelCapabilities();
  checkAdminStatus().then(() => {
    connectWebSocket();
  });
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
      // Backend sends flat: {type: 'status', state: 'listening', character: '...'}
      const st = event.state || event.payload?.state || 'idle';
      const char = event.character || event.payload?.character;
      
      // Enforce backend authoritative character state
      if (char && char !== selectedCharacter) {
        selectedCharacter = char;
        const nameEl = document.getElementById('active-char-name');
        if (nameEl) nameEl.textContent = char.charAt(0).toUpperCase() + char.slice(1);
        
        ['addy', 'nova', 'atlas'].forEach(c => {
          const el = document.getElementById(`btn-char-${c}`);
          if (el) el.classList.toggle('active', c === char);
        });
        document.body.classList.remove('persona-nova', 'persona-atlas');
        if (char === 'nova')  document.body.classList.add('persona-nova');
        if (char === 'atlas') document.body.classList.add('persona-atlas');
      }

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

    case 'character_shift': {
      // Backend emitted a persona handoff — update frontend state completely
      const target = event.character || event.payload?.character || 'addy';
      const voice  = event.voice   || event.payload?.voice   || 'Aoede';
      const color  = event.color   || event.payload?.color   || 'cyan';
      const status = event.status  || event.payload?.status  || 'ready';
      logInfo(`character_shift: ${selectedCharacter} → ${target} (status: ${status})`);

      if (status === 'starting') {
        // Apply persona body class for CSS color transition
        document.body.classList.remove('persona-nova', 'persona-atlas');
        if (target === 'nova')  document.body.classList.add('persona-nova');
        if (target === 'atlas') document.body.classList.add('persona-atlas');
        
        const displayName = target.charAt(0).toUpperCase() + target.slice(1);
        setStatus('connecting', `Connecting to ${displayName}…`);
      } else if (status === 'ready') {
        // Update local state ONLY when backend says ready
        selectedCharacter = target;
        selectedVoice     = voice;
        if (voiceSelect) voiceSelect.value = voice;

        // Update character display
        const nameEl = document.getElementById('active-char-name');
        const descEl = document.getElementById('active-char-desc');
        if (nameEl) nameEl.textContent = target.charAt(0).toUpperCase() + target.slice(1);
        
        // Update persona tab active states
        ['addy', 'nova', 'atlas'].forEach(c => {
          const el = document.getElementById(`btn-char-${c}`);
          if (el) el.classList.toggle('active', c === target);
        });
        
        setStatus('listening', 'Ready');
      } else if (status === 'error') {
        setStatus('error', `Failed to connect to ${target}`);
      }

      break;
    }

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
        let shouldSendAudio = true;

        if (!agentState || agentState === 'listening' || agentState === 'idle') {
          localBargeInActive = false;
          preRollBuffer = [];
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
        } else if (agentState === 'speaking' || agentState === 'thinking') {
          // Agent is active. Prevent speaker echo from triggering Gemini VAD.
          const playbackVol = window.audioPlayer ? window.audioPlayer.getPlaybackVolume() : 0;
          
          if (!localBargeInActive) {
            // Configurable thresholds for barge-in detection
            const MIN_BARGE_IN_RMS = 0.02; // Minimum RMS to consider as speech
            const ECHO_MULTIPLIER = 1.5;   // Mic RMS must be higher than 1.5x the playback RMS
            
            if (rms > MIN_BARGE_IN_RMS && rms > playbackVol * ECHO_MULTIPLIER) {
               // Real user speech detected over speaker echo!
               logInfo(`Local VAD detected barge-in! Mic RMS: ${rms.toFixed(3)}, Playback Vol: ${playbackVol.toFixed(3)}`);
               localBargeInActive = true;
               
               // Flush the pre-roll buffer to Gemini to capture the start of the user's speech
               if (ws && ws.readyState === WebSocket.OPEN) {
                  for (const frame of preRollBuffer) {
                     ws.send(frame.buffer);
                  }
               }
               preRollBuffer = [];
            } else {
               // Not speech, likely just echo or silence. Suppress audio to Gemini.
               shouldSendAudio = false;
               
               // Save PCM to pre-roll
               const pcmBuffer = new Int16Array(inputData.length);
               for (let i = 0; i < inputData.length; i++) {
                 const sample = Math.max(-1, Math.min(1, inputData[i]));
                 pcmBuffer[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
               }
               preRollBuffer.push(pcmBuffer);
               if (preRollBuffer.length > PRE_ROLL_MAX_FRAMES) {
                  preRollBuffer.shift();
               }
            }
          }
        }

        // ── Send raw PCM bytes to backend ──────────────────────────────
        if (shouldSendAudio) {
           const pcmBuffer = new Int16Array(inputData.length);
           for (let i = 0; i < inputData.length; i++) {
             const sample = Math.max(-1, Math.min(1, inputData[i]));
             pcmBuffer[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
           }
           if (ws && ws.readyState === WebSocket.OPEN) {
             ws.send(pcmBuffer.buffer);
           }
        } else {
           // Send pure silence (zeros) to keep Gemini timestamp advancing without triggering VAD
           const pcmBuffer = new Int16Array(inputData.length); // initialized to 0
           if (ws && ws.readyState === WebSocket.OPEN) {
             ws.send(pcmBuffer.buffer);
           }
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
  // Disabling local audio cutoff to prevent false positives from speaker echo.
  // Gemini's server-side barge-in detection (interrupted event) is the authoritative source.
  return;
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
  msg.className = sender === 'user' ? 'transcript-bubble-user' : 'transcript-bubble-ai';

  const label = document.createElement('span');
  label.className = 'msg-label';
  label.textContent = sender === 'user' ? 'You' : selectedCharacter.charAt(0).toUpperCase() + selectedCharacter.slice(1);
  label.style.cssText = 'display:block;font-size:0.65rem;opacity:0.5;margin-bottom:2px;letter-spacing:0.06em;text-transform:uppercase;';

  const bubble = document.createElement('p');
  bubble.className = 'msg-bubble';
  bubble.style.margin = '0';
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
    requestCharacterShift('addy');
  });

  btnCharNova.addEventListener('click', () => {
    requestCharacterShift('nova');
  });

  btnCharAtlas.addEventListener('click', () => {
    if (!isAdminAuthenticated) {
      // Show admin auth modal first
      adminLoginModal.classList.remove('hidden');
      adminPasscodeInput.focus();
    } else {
      requestCharacterShift('atlas');
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

  // Gear button toggles settings panel
  const gearBtn    = document.getElementById('gear-btn');
  const settingsPanel = document.getElementById('settings-panel');
  const settingsClose = document.getElementById('settings-close');

  if (gearBtn && settingsPanel) {
    gearBtn.addEventListener('click', () => {
      settingsPanel.classList.toggle('open');
    });
  }
  if (settingsClose && settingsPanel) {
    settingsClose.addEventListener('click', () => {
      settingsPanel.classList.remove('open');
    });
  }
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
// NOTE: The live visualizer now runs from js/orb.js (Three.js WebGL module).
// This legacy Canvas 2D loop was removed to avoid a second, conflicting renderer.

// ── Helper Utilities ─────────────────────────────────────────────────────────

function setStatus(state, label) {
  agentState = state;
  window.dispatchEvent(new CustomEvent('addy:statechange', {
    detail: { state, character: selectedCharacter, label }
  }));
  const engineSuffix = selectedEngine === 'gemini_live' ? ' (Gemini Live)' : ' (Deepgram)';

  if (state === 'listening' || state === 'thinking' || state === 'speaking') {
    statusValue.textContent = label + engineSuffix;
  } else {
    statusValue.textContent = label;
  }
  statusValue.className = `status-value ${state}`;

  // Apply body state class for CSS ring/orb reactivity
  document.body.classList.remove('state-idle', 'state-listening', 'state-thinking', 'state-speaking', 'state-error', 'state-interrupted', 'state-connecting');
  document.body.classList.add(`state-${state}`);

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

function requestCharacterShift(char) {
  if (char === selectedCharacter) return;
  
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'settings',
      payload: {
        character: char
      }
    }));
  } else {
    // If not connected, we can just set the character locally and connect
    selectedCharacter = char;
    if (char === 'atlas') selectedVoice = 'Charon';
    else if (char === 'nova') selectedVoice = 'Kore';
    else selectedVoice = 'Aoede';
    if (voiceSelect) voiceSelect.value = selectedVoice;
    
    // update tabs
    ['addy', 'nova', 'atlas'].forEach(c => {
      const el = document.getElementById(`btn-char-${c}`);
      if (el) el.classList.toggle('active', c === char);
    });
    
    connectWebSocket();
  }
}

async function checkAdminStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/auth/status`, { credentials: 'include' });
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
      body: JSON.stringify({ passcode }),
      credentials: 'include'
    });

    if (resp.ok) {
      const data = await resp.json();
      if (data.access_mode === 'ADMIN') {
        isAdminAuthenticated = true;
        adminToggleBtn.classList.add('authenticated');
        adminToggleBtn.textContent = '🔓';

        // Unlock UI: show Atlas tab, apply admin body class
        document.body.classList.add('admin-unlocked');
        const atlasBtn = document.getElementById('btn-char-atlas');
        if (atlasBtn) atlasBtn.removeAttribute('hidden');

        // Hide modal and clear input
        adminLoginModal.classList.add('hidden');
        adminLoginError.classList.add('hidden');
        adminPasscodeInput.value = '';

        // Preselect Atlas so the reconnecting WebSocket requests it directly.
        // The session cookie is now stored (credentials: 'include'), so the
        // backend will accept the admin-only character on this connection.
        selectedCharacter = 'atlas';
        selectedVoice = 'Charon';
        if (voiceSelect) voiceSelect.value = 'Charon';
        document.body.classList.remove('persona-nova');
        document.body.classList.add('persona-atlas');
        ['addy', 'nova', 'atlas'].forEach(c => {
          const el = document.getElementById(`btn-char-${c}`);
          if (el) el.classList.toggle('active', c === 'atlas');
        });
        const nameEl = document.getElementById('active-char-name');
        if (nameEl) nameEl.textContent = 'Atlas';

        // Reconnect WS to pick up the new authenticated cookie for Admin access mode
        if (ws) {
          ws.close();
        }
        setTimeout(() => connectWebSocket(), 100);
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
    const resp = await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', credentials: 'include' });
    if (resp.ok) {
      isAdminAuthenticated = false;
      adminToggleBtn.classList.remove('authenticated');
      adminToggleBtn.textContent = '🔑';

      // Remove admin UI
      document.body.classList.remove('admin-unlocked');
      const atlasBtn = document.getElementById('btn-char-atlas');
      if (atlasBtn) atlasBtn.setAttribute('hidden', '');

      // Drop back to Addy before reconnecting (Atlas is admin-only)
      if (selectedCharacter === 'atlas') {
        selectedCharacter = 'addy';
        selectedVoice = 'Aoede';
        if (voiceSelect) voiceSelect.value = 'Aoede';
        document.body.classList.remove('persona-atlas');
        ['addy', 'nova', 'atlas'].forEach(c => {
          const el = document.getElementById(`btn-char-${c}`);
          if (el) el.classList.toggle('active', c === 'addy');
        });
        const nameEl = document.getElementById('active-char-name');
        if (nameEl) nameEl.textContent = 'Addy';
      }

      // Reconnect WS to drop Admin access mode
      if (ws) {
        ws.close();
      }
      setTimeout(() => connectWebSocket(), 100);
    }
  } catch (err) {
    console.error('Logout error:', err);
  }
}

function getCharacterDesc(char) {
  if (char === 'addy') return "Adarsh's AI Twin";
  if (char === 'nova') return 'Contact & Enquiry Specialist';
  if (char === 'atlas') return 'Private AI OS (Admin)';
  return 'Assistant';
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


