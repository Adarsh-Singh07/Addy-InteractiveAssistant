# Addy Voice Assistant — Backend Service

FastAPI-based real-time voice backend for Addy.

## Setup & Run (Local Development)

1. Create a virtual environment and activate it:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the environment variables template and configure it:
   ```bash
   cp .env.example .env
   ```
4. Start the development server on port 8001:
   ```bash
   uvicorn app.main:app --reload --port 8001
   ```

## Running Tests
Run tests to verify the setup:
```bash
PYTHONPATH=. pytest
```
