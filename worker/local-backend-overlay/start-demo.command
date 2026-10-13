#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ -f /Users/emilia/Downloads/SecretKey.csv ]]; then
  export FORME_HUNYUAN_KEY_FILE=/Users/emilia/Downloads/SecretKey.csv
fi
export FORME_START_WORKERS=1
exec ./run-local.sh
