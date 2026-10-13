#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 user@cloud-server" >&2
  exit 2
fi

# The cloud server listens only on its loopback interface. A live SSH process
# alone does not prove that the server-side reverse listener still exists.
server=$1
tunnel_pid=
cleanup() {
  if [ -n "$tunnel_pid" ]; then
    kill -TERM "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
}
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap cleanup EXIT

while :; do
  ssh -NT -o BatchMode=yes -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R 127.0.0.1:18001:127.0.0.1:8001 "$server" &
  tunnel_pid=$!
  sleep 3
  failures=0
  while kill -0 "$tunnel_pid" 2>/dev/null; do
    if ssh -T -o BatchMode=yes -o ConnectTimeout=8 "$server" \
      'curl -fsS --max-time 5 http://127.0.0.1:18001/health >/dev/null' 2>/dev/null; then
      failures=0
    else
      failures=$((failures + 1))
      if [ "$failures" -ge 2 ]; then break; fi
    fi
    sleep 20
  done
  cleanup
  tunnel_pid=
  sleep 3
done
