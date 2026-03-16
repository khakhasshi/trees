#!/usr/bin/env bash
set -euo pipefail

APP_NAME="trees-app"
APP_PORT="7006"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

PURGE_ALL="${PURGE_ALL:-0}"
FORCE="${FORCE:-0}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 sudo 运行：sudo bash uninstall_ubuntu.sh"
  exit 1
fi

echo "将执行以下卸载操作："
echo "1) 停止并禁用 systemd 服务: ${APP_NAME}"
echo "2) 删除服务文件: ${SERVICE_FILE}"
echo "3) 删除项目运行产物: .venv trees.db db_backups __pycache__ .pytest_cache"
echo "4) 尝试移除 ufw 端口规则: ${APP_PORT}"
if [[ "${PURGE_ALL}" == "1" ]]; then
  echo "5) 彻底删除项目目录: ${APP_DIR}"
fi

if [[ "${FORCE}" != "1" ]]; then
  read -r -p "确认继续卸载? 输入 YES: " ANSWER
  if [[ "${ANSWER}" != "YES" ]]; then
    echo "已取消。"
    exit 0
  fi
fi

echo "[1/5] 停止并禁用服务..."
if systemctl list-unit-files | grep -q "^${APP_NAME}.service"; then
  systemctl stop "${APP_NAME}" || true
  systemctl disable "${APP_NAME}" || true
fi

echo "[2/5] 删除服务文件并重载 systemd..."
rm -f "${SERVICE_FILE}"
systemctl daemon-reload
systemctl reset-failed || true

echo "[3/5] 删除项目运行产物..."
rm -rf "${APP_DIR}/.venv"
rm -f "${APP_DIR}/trees.db"
rm -rf "${APP_DIR}/db_backups"
rm -rf "${APP_DIR}/__pycache__"
rm -rf "${APP_DIR}/.pytest_cache"
find "${APP_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "${APP_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true

echo "[4/5] 清理防火墙规则(如果有)..."
if command -v ufw >/dev/null 2>&1; then
  ufw delete allow "${APP_PORT}" >/dev/null 2>&1 || true
fi

echo "[5/5] 完成基础卸载。"

if [[ "${PURGE_ALL}" == "1" ]]; then
  if [[ "${APP_DIR}" == "/" || "${APP_DIR}" == "" ]]; then
    echo "安全检查失败: APP_DIR 异常，终止删除目录。"
    exit 1
  fi
  echo "正在删除项目目录: ${APP_DIR}"
  rm -rf "${APP_DIR}"
fi

echo "卸载完成 ✅"
echo "可检查服务是否仍存在: systemctl status ${APP_NAME}"
