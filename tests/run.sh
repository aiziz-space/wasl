#!/usr/bin/env bash
# Runs the end-to-end tests: local PeerServer (signaling) + static server + two headless Chrome contexts.
# Needs: node/npm, python3, `pip install playwright opencv-python-headless numpy`, and Chrome (or `playwright install chromium`).
set -euo pipefail
cd "$(dirname "$0")/.."
PEER=/tmp/wasl-peer
[ -f "$PEER/node_modules/peer/dist/bin/peerjs.js" ] || npm i --prefix "$PEER" peer@1.0.2 --silent
node "$PEER/node_modules/peer/dist/bin/peerjs.js" --port 9000 -H 127.0.0.1 --path / > /tmp/wasl-peer.log 2>&1 &
P1=$!
python3 -m http.server 8080 --bind 127.0.0.1 > /tmp/wasl-http.log 2>&1 &
P2=$!
trap 'kill $P1 $P2 2>/dev/null' EXIT
sleep 2
WASL_URL=http://localhost:8080/ python3 tests/e2e.py
WASL_URL=http://localhost:8080/ python3 tests/extra.py
WASL_URL=http://localhost:8080/ python3 tests/lang.py
echo "ALL TESTS PASSED (screenshots in ${WASL_SHOTS:-/tmp})"
