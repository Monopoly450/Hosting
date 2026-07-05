#!/usr/bin/env bash
#
# Скрипт настройки безопасности (безопасность хост-системы Aegis VM)
# Выполняет ограничение прав файлов конфигурации и устанавливает/настраивает Fail2Ban.
#

set -e

# Цветовая разметка вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Начало настройки безопасности хост-системы ===${NC}\n"

# Проверка прав root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Ошибка: Этот скрипт должен быть запущен от имени суперпользователя root (sudo).${NC}"
  exit 1
fi

# 1. Ограничение прав на файл .env в текущей и родительской папке
ENV_FILE=""
if [ -f ".env" ]; then
  ENV_FILE=".env"
elif [ -f "../.env" ]; then
  ENV_FILE="../.env"
elif [ -f "/root/Hosting/.env" ]; then
  ENV_FILE="/root/Hosting/.env"
fi

if [ -n "$ENV_FILE" ]; then
  echo -e "${GREEN}[1/3] Найдена конфигурация: ${ENV_FILE}. Ограничиваем права...${NC}"
  chmod 600 "$ENV_FILE"
  echo -e "Права на файл конфигурации успешно установлены в 600 (только чтение/запись для root)."
else
  echo -e "${YELLOW}[1/3] Файл .env не найден в стандартных папках. Пропустите этот шаг или задайте права вручную через 'chmod 600 .env'.${NC}"
fi

# 2. Установка Fail2Ban
echo -e "\n${GREEN}[2/3] Проверка и установка Fail2Ban...${NC}"
if command -v fail2ban-client &> /dev/null; then
  echo "Fail2Ban уже установлен на сервере."
else
  echo "Fail2Ban не найден. Устанавливаем..."
  apt-get update -y
  apt-get install -y fail2ban
  echo -e "${GREEN}Fail2Ban успешно установлен.${NC}"
fi

# 3. Настройка Fail2Ban
echo -e "\n${GREEN}[3/3] Настройка конфигурации Fail2Ban...${NC}"
JAIL_LOCAL="/etc/fail2ban/jail.local"

echo "Создаем/обновляем конфигурационный файл ${JAIL_LOCAL}..."
cat <<EOT > "$JAIL_LOCAL"
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
destemail = root@localhost
sender = root@localhost
action = %(action_mwl)s

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 1d
EOT

echo "Перезапуск службы Fail2Ban для применения настроек..."
systemctl restart fail2ban
systemctl enable fail2ban

echo -e "\n${GREEN}=== Настройка безопасности успешно завершена! ===${NC}"
echo -e "${YELLOW}Текущий статус службы Fail2Ban:${NC}"
systemctl status fail2ban --no-pager | grep -E "Active:|Loaded:"
echo -e "\n${YELLOW}Активные защищаемые фильтры Fail2Ban:${NC}"
fail2ban-client status
