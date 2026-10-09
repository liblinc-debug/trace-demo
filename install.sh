#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$PROJECT_DIR"

case "$(uname -s)" in
  Darwin) OS_NAME="macOS" ;;
  Linux) OS_NAME="Linux" ;;
  *) echo "错误：仅支持 macOS 与 Linux。" >&2; exit 1 ;;
esac

RUN_MODE="${1:-systemd}"
case "$RUN_MODE" in
  development|dev|production|prod|systemd|service) ;;
  *) echo "错误：启动模式只能是 development/dev 或 production/prod/systemd/service。" >&2; exit 1 ;;
esac

if [[ "$RUN_MODE" != "development" && "$RUN_MODE" != "dev" && "$OS_NAME" != "Linux" ]]; then
  echo "错误：systemd 服务只能安装在 Linux；macOS 开发环境请执行 ./install.sh development。" >&2
  exit 1
fi

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
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$PROJECT_DIR/${ENV_FILE#./}"
fi
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

echo "系统：${OS_NAME}；环境文件：${ENV_FILE}；启动模式：${RUN_MODE}"
echo "正在安装项目依赖..."
npm ci

case "$RUN_MODE" in
  development|dev)
    exec npm run dev
    ;;
  production|prod|systemd|service)
    if ! command -v systemctl >/dev/null 2>&1; then
      echo "错误：未找到 systemctl，请确认目标 Linux 使用 systemd。" >&2
      exit 1
    fi
    if (( EUID != 0 )) && ! command -v sudo >/dev/null 2>&1; then
      echo "错误：安装 systemd 服务需要 root 权限，且当前系统未安装 sudo。" >&2
      exit 1
    fi

    npm run build

    SERVICE_NAME="${SERVICE_NAME:-trace-demo}"
    if [[ ! "$SERVICE_NAME" =~ ^[A-Za-z0-9_.@-]+$ ]]; then
      echo "错误：SERVICE_NAME 包含非法字符：$SERVICE_NAME" >&2
      exit 1
    fi

    SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
      echo "错误：服务用户不存在：$SERVICE_USER" >&2
      exit 1
    fi
    SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
    NODE_BIN="$(command -v node)"
    UNIT_NAME="${SERVICE_NAME}.service"
    UNIT_PATH="/etc/systemd/system/$UNIT_NAME"
    UNIT_FILE="$(mktemp)"
    trap 'rm -f "$UNIT_FILE"' EXIT

    {
      echo '[Unit]'
      echo 'Description=Drone flight trace demo'
      echo 'Wants=network-online.target'
      echo 'After=network-online.target'
      echo
      echo '[Service]'
      echo 'Type=simple'
      printf 'User=%s\n' "$SERVICE_USER"
      printf 'Group=%s\n' "$SERVICE_GROUP"
      printf 'WorkingDirectory=%s\n' "$PROJECT_DIR"
      printf 'EnvironmentFile=%s\n' "$ENV_FILE"
      echo 'Environment=NODE_ENV=production'
      printf 'ExecStart=%s %s\n' "$NODE_BIN" "$PROJECT_DIR/server.js"
      echo 'Restart=on-failure'
      echo 'RestartSec=3'
      echo 'TimeoutStopSec=20'
      echo 'NoNewPrivileges=true'
      echo 'PrivateTmp=true'
      echo
      echo '[Install]'
      echo 'WantedBy=multi-user.target'
    } > "$UNIT_FILE"

    if (( EUID == 0 )); then
      ROOT_COMMAND=()
    else
      ROOT_COMMAND=(sudo)
    fi

    "${ROOT_COMMAND[@]}" install -m 0644 "$UNIT_FILE" "$UNIT_PATH"
    if command -v systemd-analyze >/dev/null 2>&1; then
      "${ROOT_COMMAND[@]}" systemd-analyze verify "$UNIT_PATH"
    fi
    "${ROOT_COMMAND[@]}" systemctl daemon-reload
    "${ROOT_COMMAND[@]}" systemctl enable "$UNIT_NAME"
    "${ROOT_COMMAND[@]}" systemctl restart "$UNIT_NAME"

    sleep 1
    if ! "${ROOT_COMMAND[@]}" systemctl is-active --quiet "$UNIT_NAME"; then
      echo "错误：$UNIT_NAME 启动失败，最近日志如下：" >&2
      "${ROOT_COMMAND[@]}" systemctl --no-pager --full status "$UNIT_NAME" || true
      exit 1
    fi

    echo "systemd 服务已安装并启动：$UNIT_NAME"
    echo "服务地址：http://localhost:${PORT:-4000}"
    echo "查看状态：systemctl status $UNIT_NAME"
    echo "查看日志：journalctl -u $UNIT_NAME -f"
    ;;
esac
