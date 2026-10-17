#!/bin/zsh
set -eu
cd "${0:A:h}"
.venv/bin/python - <<'PY'
import socket
from pathlib import Path

path = Path('data/service-logs/control.sock')
if not path.exists():
    print('后台链路未运行。')
else:
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.sendto(b'stop', str(path))
    print('已请求停止后台链路。')
PY
