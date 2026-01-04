#!/usr/bin/env bash
# 自动更新并按需热重启 Amaya 服务的脚本（低优先级，可选启用）。
# 使用前请将 SERVICE_NAME 设置为你的 systemd 服务名，或改为自定义重启命令。

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-amaya}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[auto-update] 项目目录: ${PROJECT_DIR}"
cd "${PROJECT_DIR}"

echo "[auto-update] 获取最新代码..."
git fetch --all --prune
git status --short

echo "[auto-update] 合并远端（仅 fast-forward）..."
git merge --ff-only origin/main || {
  echo "[auto-update] Fast-forward 失败，请手动处理冲突。"
  exit 1
}

echo "[auto-update] 运行依赖安装（可根据需要调整）..."
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

echo "[auto-update] 重启服务 ${SERVICE_NAME}（如果存在）..."
if command -v systemctl >/dev/null 2>&1 && systemctl list-units --type=service | grep -q "${SERVICE_NAME}.service"; then
  sudo systemctl restart "${SERVICE_NAME}.service"
  systemctl status "${SERVICE_NAME}.service" --no-pager
else
  echo "[auto-update] 未检测到 systemd 服务，跳过重启。"
fi

echo "[auto-update] 完成。"
