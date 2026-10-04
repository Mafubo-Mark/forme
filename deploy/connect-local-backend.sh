#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 user@cloud-server" >&2
  exit 2
fi

# The cloud server listens only on its loopback interface. Nginx exposes only
# /api/customer/* and /api/uploads/* under the same HTTPS origin as the site.
exec ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 -R 127.0.0.1:18001:127.0.0.1:8001 "$1"
