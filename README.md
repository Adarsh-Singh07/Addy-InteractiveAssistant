# Addy — Personal AI Voice Assistant

> **Phase 1 — Voice Loop** | Private · Voice-First · Multilingual

Addy is Adarsh's personal AI agent. A voice-first assistant that understands English, Hindi, and Hinglish, remembers context, delegates tasks to Hermes, and runs privately on your own infrastructure.

## Quick Start

### Prerequisites

- Docker + Docker Compose
- API keys: Deepgram, Gemini or Groq (see `.env.example`)

### 1. Configure

```bash
cp .env.example .env
# Fill in: DEEPGRAM_API_KEY, GEMINI_API_KEY (or GROQ_API_KEY)
# Also set: APP_SECRET_KEY, ADMIN_PASSWORD
```

### 2. Start

```bash
docker compose up --build
```

### 3. Open

| Service | URL |
|---|---|
| Voice UI | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Metrics | http://localhost:8000/api/metrics |
| Diagnostics | http://localhost:8000/api/diagnostics |
| Qdrant (Phase 3) | http://localhost:6333/dashboard |

### 4. Talk

1. Open http://localhost:3000
2. Tap the microphone button (or press **Space**)
3. Speak in English, Hindi, or Hinglish
4. Press **Esc** or tap **Interrupt** to stop Addy mid-sentence

---

## Architecture

```
Browser
  │  MediaRecorder audio (webm/opus)
  │  WebSocket control events
  ▼
FastAPI /ws/voice
  │
  ├── VoiceTransport (WebSocketTransport)
  │     ↑ Audio format abstraction
  │     └── Future: WebRTCTransport
  │
  ├── Deepgram STT WebSocket (Nova-3, multilingual)
  │     └── UtteranceEnd → transcript
  │
  ├── AgentCore
  │     ├── GeminiProvider (primary)
  │     └── GroqProvider   (fallback)
  │           └── Streaming tokens → SentenceBuffer
  │
  └── Deepgram TTS REST (Aura-2)
        └── Audio bytes → WebSocket → Browser AudioContext
```

### Voice Barge-In

Client-side VAD (energy threshold via Web Audio API):
- If RMS energy > threshold while agent is speaking → send `{"type": "interrupt"}`
- Backend cancels TTS task + LLM stream
- Immediately resumes STT listening

### Latency Instrumentation

Every turn is measured at four points:

| Timestamp | Meaning |
|---|---|
| `speech_end_ts` | Deepgram UtteranceEnd fires |
| `llm_first_token_ts` | First LLM token arrives |
| `tts_first_audio_ts` | First TTS audio chunk received |
| `client_audio_sent_ts` | Audio chunk sent through WebSocket |

View at `GET /api/metrics` after a few turns.

---

## Provider Switching

Change `LLM_PROVIDER` in `.env` — no code changes needed:

```env
LLM_PROVIDER=gemini   # Gemini 2.5 Flash (default)
LLM_PROVIDER=groq     # Groq llama-3.1-8b-instant (fastest)
LLM_PROVIDER=luna     # GPT Luna (stub — implement when ready)
```

Set fallback:
```env
LLM_FALLBACK_PROVIDER=groq
```

---

## Local Development (without Docker)

### Backend Setup:
```bash
cd backend
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env       # fill in keys
uvicorn app.main:app --reload --port 8001
```

### Frontend Setup:
The frontend contains plain HTML/CSS/JS. For local development, simply serve the `frontend/` directory (e.g. using `npx serve frontend` or VS Code Live Server). By default, it connects to `http://localhost:8001` for the backend.

---

## Production Architecture & CI/CD

Addy is split into a static frontend hosted on Vercel and a FastAPI backend service running on your Oracle VPS.

```text
addy.adarshsingh.in (Vercel Frontend)
         │
         │ HTTPS / WSS
         ▼
api.adarshsingh.in (Cloudflare Proxy)
         │
         ▼
    Oracle VPS (Nginx Reverse Proxy)
         │
         ▼
    127.0.0.1:8001 (addy.service FastAPI)
```

### CI/CD Deployment Flow:

1. **Frontend**: Automatically deployed via Vercel when changes are pushed to `main`.
2. **Backend**: Deployed automatically to the Oracle VPS via GitHub Actions when backend files change on `main`.

---

## GitHub Actions Deployment (Backend)

The workflow `.github/workflows/backend-deploy.yml` triggers on pushes to the `main` branch. It SSHs into the VPS and executes `/home/ubuntu/Addy-TheVoiceAssistant/deploy/deploy-backend.sh` safely.

### Required GitHub Secrets:
Configure the following secrets in your GitHub repository settings under **Settings -> Secrets and variables -> Actions**:
- `VPS_HOST`: The IP or hostname of your VPS (`168.107.71.100`).
- `VPS_USER`: The SSH username (e.g. `ubuntu`).
- `VPS_SSH_KEY`: The private key used to authenticate.

---

## Zero-Downtime & Rollback Protection

The `deploy/deploy-backend.sh` script employs a safety mechanism:
1. Saves the current commit reference before pulling.
2. Checks syntax and compiles all Python files.
3. Runs the test suite via `pytest`.
4. Restarts `addy.service` and waits 3 seconds.
5. Performs a health check request against `/api/health`.
6. **Rollback**: If any of these steps fail, it resets the git repo back to the previous stable commit, restarts the service, and exits with a failure code, leaving the production server unaffected and running the last stable version.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| **Space** | Toggle microphone |
| **Esc** | Interrupt Addy |

