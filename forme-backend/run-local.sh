#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "请先按 README 安装本地虚拟环境与依赖。" >&2
  exit 1
fi

if [ -f "$project_dir/.local-operator-token" ]; then
  FORME_DEV_TOKEN=$(cat "$project_dir/.local-operator-token")
  [ -n "$FORME_DEV_TOKEN" ] || { echo "管理代理令牌文件不能为空。" >&2; exit 1; }
  export FORME_DEV_TOKEN
elif [ -z "${FORME_DEV_TOKEN:-}" ]; then
  FORME_DEV_TOKEN=$(openssl rand -hex 24)
  export FORME_DEV_TOKEN
fi

if [ -z "${FORME_CUSTOMER_ACCESS_KEY:-}" ]; then
  key_file="$project_dir/.customer-access-key"
  if [ ! -f "$key_file" ]; then
    umask 077
    openssl rand -hex 24 > "$key_file"
  fi
  FORME_CUSTOMER_ACCESS_KEY=$(cat "$key_file")
  export FORME_CUSTOMER_ACCESS_KEY
fi

FORME_DATA_DIR=${FORME_DATA_DIR:-"$project_dir/data"}
export FORME_DATA_DIR

tools_dir=/Volumes/extra/workspace1/colmap-metal/.pixi/envs/default/bin
if [ -z "${FORME_FFPROBE:-}" ] && [ -x "$tools_dir/ffprobe" ]; then
  FORME_FFPROBE="$tools_dir/ffprobe"
  export FORME_FFPROBE
fi
if [ -z "${FORME_FFMPEG:-}" ] && [ -x "$tools_dir/ffmpeg" ]; then
  FORME_FFMPEG="$tools_dir/ffmpeg"
  export FORME_FFMPEG
fi

geometry_python=/Volumes/extra/workspace1/apps/drawing-with-gaussians/.venv/bin/python
if [ -z "${FORME_GEOMETRY_PYTHON:-}" ] && [ -x "$geometry_python" ]; then
  FORME_GEOMETRY_PYTHON="$geometry_python"
  export FORME_GEOMETRY_PYTHON
fi

echo "操作后台：http://127.0.0.1:8001/operator/"
if [ -f "$project_dir/.local-operator-token" ]; then
  echo "管理代理令牌来自本机私有文件 .local-operator-token"
else
  echo "开发令牌（仅本次启动使用）：$FORME_DEV_TOKEN"
fi
echo "客户登录密钥保存在：$project_dir/.customer-access-key（仅本机读取，不要提交到仓库）"
if [ "${FORME_START_WORKERS:-0}" = "1" ]; then
  .venv/bin/python -m forme_backend.worker &
  media_pid=$!
  .venv/bin/python -m forme_backend.model_worker &
  model_pid=$!
  .venv/bin/python -m forme_backend.scan_worker &
  scan_pid=$!
  if [ -n "${FORME_HUNYUAN_KEY_FILE:-}" ]; then
    .venv/bin/python -m forme_backend.hunyuan_worker &
    hunyuan_pid=$!
  else
    hunyuan_pid=
  fi
  trap 'kill "$media_pid" "$model_pid" "$scan_pid" ${hunyuan_pid:+"$hunyuan_pid"} 2>/dev/null || true' EXIT INT TERM
  .venv/bin/uvicorn forme_backend.api:create_app --factory --host 127.0.0.1 --port 8001
else
  exec .venv/bin/uvicorn forme_backend.api:create_app --factory --host 127.0.0.1 --port 8001
fi
