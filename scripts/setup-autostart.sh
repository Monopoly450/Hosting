#!/usr/bin/env bash

# Скрипт настройки автозапуска сетевого моста и панели управления Aegis после перезагрузки
# Должен запускаться от имени root (sudo)

set -e

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"

echo "=== Настройка автозапуска Aegis Cloud Engine ==="

if [ "$EUID" -ne 0 ]; then
    echo "Ошибка: Скрипт должен быть запущен от имени root (через sudo)."
    exit 1
fi

# 1. Создание службы автозапуска сетевого моста (aegis-network.service)
echo "Создание службы автозапуска сетевого моста..."
cat <<EOF > /etc/systemd/system/aegis-network.service
[Unit]
Description=Aegis VM Network Bridge Setup
Before=k3s.service docker.service dnsmasq.service
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c "ip link show br-vms &>/dev/null || (ip link add br-vms type bridge && ip addr add 172.20.0.1/24 dev br-vms && ip link set br-vms up)"

[Install]
WantedBy=multi-user.target
EOF

# 2. Создание службы автозапуска панели управления (aegis-hosting.service)
echo "Создание службы автозапуска панели управления..."
cat <<EOF > /etc/systemd/system/aegis-hosting.service
[Unit]
Description=Aegis Cloud Engine hosting control panel
Requires=docker.service k3s.service aegis-network.service
After=docker.service k3s.service aegis-network.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose restart

[Install]
WantedBy=multi-user.target
EOF

# 3. Перезапуск конфигурации systemd и включение служб
echo "Активация служб в systemd..."
systemctl daemon-reload

systemctl enable aegis-network.service
systemctl enable aegis-hosting.service

# Попытка запустить сетевую службу прямо сейчас для проверки
systemctl restart aegis-network.service

echo "=========================================================="
echo "Автозапуск успешно настроен!"
echo "При перезагрузке система автоматически:"
echo " 1. Поднимет сетевой мост br-vms и настроит DHCP (dnsmasq)."
echo " 2. Запустит контейнеры панели управления в ${PROJECT_DIR}."
echo "=========================================================="
