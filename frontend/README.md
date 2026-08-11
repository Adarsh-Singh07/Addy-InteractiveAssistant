# Addy Voice Assistant — Immersive Orb Frontend

This folder contains the plain HTML, CSS, and JS assets for Addy's web interface.

## Local Development
Since this is a simple static website, you do not need an active bundler or compiler:
1. Copy `.env.example` to `.env` (Vercel uses this to pass the production variables).
2. Open `index.html` directly in the browser, or serve it using any simple static HTTP server:
   ```bash
   npx serve .
   ```
3. By default, it will attempt to connect to the backend running locally at `http://localhost:8001`.

## Vercel Deployment
To deploy this frontend to Vercel:
1. Connect this repository to your Vercel account.
2. Set the project **Root Directory** to `frontend`.
3. In Project Settings, set the **Build Command** to `bash vercel-build.sh` (or `sh vercel-build.sh`).
4. Set the **Output Directory** to `.` (since the directory already contains `index.html`).
5. Configure the Environment Variable `VITE_API_BASE_URL` to `https://api.adarshsingh.in`.
