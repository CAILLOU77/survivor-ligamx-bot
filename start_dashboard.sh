#!/usr/bin/env bash
cd /Users/mac/projects/survivor-ligamx-bot
mkdir -p reports
python3 -m http.server 8080 -d reports &
echo "🌐 Dashboard activo en http://localhost:8080 (PID: $!)"
