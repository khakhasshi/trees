#!/usr/bin/env bash
set -euo pipefail

APP_NAME="trees-app"
APP_PORT="7006"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
REBUILD_DB="${REBUILD_DB:-0}"
DB_PATH="${APP_DIR}/trees.db"
BACKUP_DIR="${APP_DIR}/db_backups"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 sudo 运行：sudo bash deploy_ubuntu.sh"
  exit 1
fi

echo "[1/6] 安装系统依赖..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip

echo "[2/6] 创建虚拟环境..."
python3 -m venv "${APP_DIR}/.venv"


echo "[3/6] 安装 Python 依赖..."
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
"${APP_DIR}/.venv/bin/pip" install gunicorn

echo "[4/6] 写入 systemd 服务..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Trees Flask App Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/gunicorn -w 2 -b 0.0.0.0:${APP_PORT} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "[5/6] 启动并设置开机自启..."
systemctl daemon-reload
systemctl enable "${APP_NAME}"
systemctl restart "${APP_NAME}"

if [[ "${REBUILD_DB}" == "1" ]]; then
  echo "[额外步骤] 检测到 REBUILD_DB=1，执行数据库重建..."
  systemctl stop "${APP_NAME}"
  mkdir -p "${BACKUP_DIR}"
  if [[ -f "${DB_PATH}" ]]; then
    BACKUP_FILE="${BACKUP_DIR}/trees_$(date +%Y%m%d_%H%M%S).db"
    cp "${DB_PATH}" "${BACKUP_FILE}"
    echo "已备份旧数据库到: ${BACKUP_FILE}"
    rm -f "${DB_PATH}"
  fi
  cd "${APP_DIR}"
  "${APP_DIR}/.venv/bin/python" -c "from app import init_db; init_db()"
  systemctl start "${APP_NAME}"
  echo "数据库已重建并重启服务。"
fi

if command -v ufw >/dev/null 2>&1; then
  echo "[6/6] 放行防火墙端口 ${APP_PORT}..."
  ufw allow "${APP_PORT}" || true
else
  echo "[6/6] 未检测到 ufw，跳过防火墙放行。"
fi

LAN_IP="$(hostname -I | awk '{print $1}')"

echo "部署完成 ✅"
echo "服务名: ${APP_NAME}"
echo "查看状态: systemctl status ${APP_NAME}"
echo "查看日志: journalctl -u ${APP_NAME} -f"
echo "本机访问: http://127.0.0.1:${APP_PORT}"
echo "局域网访问: http://${LAN_IP}:${APP_PORT}"
echo "如需重建数据库并自动备份旧库: REBUILD_DB=1 sudo bash deploy_ubuntu.sh"
