#!/bin/zsh
cd "${0:A:h}" || exit 1

host=forme_tunnel@156.233.235.150
key=data/forme-cloud-tunnel-ed25519
tunnel_pid=

cleanup() {
  if [[ -n "$tunnel_pid" ]]; then
    kill -TERM "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
}
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap cleanup EXIT

while true; do
  /usr/bin/ssh -i "$key" -N -T \
    -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R 127.0.0.1:18001:127.0.0.1:8001 "$host" &
  tunnel_pid=$!
  print "$(date '+%Y-%m-%d %H:%M:%S') 隧道已启动，PID $tunnel_pid"
  sleep 3
  failures=0
  while kill -0 "$tunnel_pid" 2>/dev/null; do
    if /usr/bin/ssh -i "$key" -T \
      -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
      -o ConnectTimeout=8 "$host" \
      'curl -fsS --max-time 5 http://127.0.0.1:18001/health >/dev/null' 2>/dev/null; then
      failures=0
    else
      failures=$((failures + 1))
      print "$(date '+%Y-%m-%d %H:%M:%S') 服务器端隧道探测失败 $failures 次"
      if (( failures >= 2 )); then
        break
      fi
    fi
    sleep 20
  done
  cleanup
  tunnel_pid=
  print "$(date '+%Y-%m-%d %H:%M:%S') 重新建立隧道"
  sleep 3
done
