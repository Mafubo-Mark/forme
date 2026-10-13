#!/bin/zsh
cd "${0:A:h}" || exit 1
export FORME_CLOUD_CONFIG="$PWD/.cloud-bridge.json"
export FORME_DATA_DIR="$PWD/data"
exec .venv/bin/python -m forme_backend.cloud_bridge
