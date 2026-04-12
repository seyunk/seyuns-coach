#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     Seyun's Personal Coach           ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Optionally accept API key as argument or env var
if [ -n "$1" ]; then
  export ANTHROPIC_API_KEY="$1"
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "  Tip: Run with your API key to skip the modal:"
  echo "  ./start.sh sk-ant-..."
  echo ""
fi

echo "  Opening → http://localhost:5001"
echo ""

# Open browser after short delay
(sleep 1.5 && open "http://localhost:5001") &

python3 server.py
