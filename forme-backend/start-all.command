#!/bin/zsh
set -eu
cd "${0:A:h}"
umask 077
for required in .venv/bin/uvicorn .venv/bin/python .cloud-bridge.json .local-operator-token data/forme-cloud-tunnel-ed25519; do
  if [[ ! -f "$required" ]]; then
    print -u2 "缺少 $required；后台链路尚不能启动。"
    exit 1
  fi
done
exec .venv/bin/python scripts/run_all.py
