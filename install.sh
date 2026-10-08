#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$PROJECT_DIR"

case "$(uname -s)" in
  Darwin) OS_NAME="macOS" ;;
  Linux) OS_NAME="Linux" ;;
  *) echo "错误：仅支持 macOS 与 Linux。" >&2; exit 1 ;;
esac

for command_name in node npm zip; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "错误：未找到 $command_name，请先安装 Node.js 18+、npm 和 zip。" >&2
    exit 1
  fi
done

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
if (( NODE_MAJOR < 18 )); then
  echo "错误：Node.js 版本需为 18 或更高，当前版本为 $(node --version)。" >&2
  exit 1
fi

ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ "$ENV_FILE" == "$PROJECT_DIR/.env" ]]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "已创建 .env，请填写高德地图参数后重新执行 ./install.sh。" >&2
  else
    echo "错误：环境文件不存在：$ENV_FILE" >&2
  fi
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -z "${VITE_AMAP_KEY:-}" || -z "${VITE_AMAP_SECURITY:-}" ||
      "$VITE_AMAP_KEY" == "your_amap_web_key" ||
      "$VITE_AMAP_SECURITY" == "your_amap_security_code" ]]; then
  echo "错误：请在 $ENV_FILE 中配置 VITE_AMAP_KEY 和 VITE_AMAP_SECURITY。" >&2
  exit 1
fi

if [[ -z "${CLICKHOUSE_PASSWORD:-}" || "$CLICKHOUSE_PASSWORD" == "your_clickhouse_password" ]]; then
  echo "错误：请在 $ENV_FILE 中配置 CLICKHOUSE_PASSWORD。" >&2
  exit 1
fi

RUN_MODE="${1:-development}"
case "$RUN_MODE" in
  development|dev|production|prod) ;;
  *) echo "错误：启动模式只能是 development/dev 或 production/prod。" >&2; exit 1 ;;
esac

echo "系统：${OS_NAME}；环境文件：${ENV_FILE}；启动模式：${RUN_MODE}"
echo "正在安装项目依赖..."
npm ci

case "$RUN_MODE" in
  development|dev)
    exec npm run dev
    ;;
  production|prod)
    npm run build
    exec npm start
    ;;
esac
