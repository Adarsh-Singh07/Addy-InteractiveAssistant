#!/bin/bash
# Generates the client-side config file from Vercel's environment variables.
echo "window.API_BASE = \"${VITE_API_BASE_URL:-}\";" > js/config.js
echo "Generated js/config.js successfully with API_BASE=${VITE_API_BASE_URL:-}"
