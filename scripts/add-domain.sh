#!/usr/bin/env bash
#
# Привязывает домены служебных сервисов (панель, почта, хранилище) к уже
# УСТАНОВЛЕННОМУ серверу — не трогая остальные пароли и настройки в .env.
# Использование:
#
#   sudo bash scripts/add-domain.sh
#
# В .env правит только четыре строки: PANEL_DOMAIN, MAIL_DOMAIN,
# STORAGE_DOMAIN, TIMEWEB_DNS_API_TOKEN — заменяет их (даже если сейчас
# закомментированы) или дописывает в конец, если их ещё не было вовсе.
# Остальной .env (пароли БД, ADMIN_TOKEN, AEGIS_SECRET_KEY и т.д.) не
# трогается ни при каких условиях — в отличие от install.sh, который на
# уже существующем .env либо спросит все пароли заново, либо вообще
# пропустит вопрос про домен.
#
# В конце сам перезапускает backend/worker (чтобы подхватить новые
# переменные) и просит панель применить конфиг Caddy без пересоздания
# контейнера (POST /api/domains/reapply) — сертификаты выпустятся сами
# через DNS-01 в течение одной-двух минут.

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"; }
error() { echo -e "${RED}[ERROR]$(date +'%Y-%m-%d %H:%M:%S')${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    error "Этот скрипт должен быть запущен с правами root: sudo bash scripts/add-domain.sh"
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
ENV_FILE="${PROJECT_DIR}/.env"

[ -f "$ENV_FILE" ] || error "Файл .env не найден в ${PROJECT_DIR} — сначала запустите install.sh."

# get_env_var KEY — значение переменной, только если строка не закомментирована.
get_env_var() {
    grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-
}

# set_env_var KEY VALUE — заменяет существующую строку KEY=... (даже
# закомментированную — install.sh пишет такие как "# KEY=  — комментарий",
# с пробелом после решётки) на новую, либо дописывает в конец файла, если
# такой переменной ещё не было. Больше ничего в файле не трогает.
set_env_var() {
    local key="$1" value="$2"
    if grep -qE "^#?[[:space:]]*${key}=" "$ENV_FILE"; then
        sed -i -E "s|^#?[[:space:]]*${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

echo -e "${CYAN}"
echo "=========================================================="
echo "  ByteBurners Hosting — домены служебных сервисов"
echo "=========================================================="
echo -e "${NC}"
echo "Любой пункт можно пропустить (Enter) — сервис останется доступен"
echo "как сейчас, по IP и порту. Меняются только эти строки в .env,"
echo "остальные пароли и настройки не трогаются."
echo

current_panel=$(get_env_var PANEL_DOMAIN)
current_mail=$(get_env_var MAIL_DOMAIN)
current_storage=$(get_env_var STORAGE_DOMAIN)
current_token=$(get_env_var TIMEWEB_DNS_API_TOKEN)

read -rp "Домен для панели управления [${current_panel:-нет}]: " panel_domain
panel_domain="${panel_domain:-$current_panel}"

read -rp "Домен для почты/вебмейла (Roundcube) [${current_mail:-нет}]: " mail_domain
mail_domain="${mail_domain:-$current_mail}"

read -rp "Домен для консоли хранилища (MinIO) [${current_storage:-нет}]: " storage_domain
storage_domain="${storage_domain:-$current_storage}"

token="$current_token"
if [ -n "$panel_domain$mail_domain$storage_domain" ]; then
    echo
    echo -e "${CYAN}Указан хотя бы один домен. Сервер стоит на приватном IP, поэтому обычный"
    echo -e "сертификат Let's Encrypt не выпустится — нужен API-токен Timeweb Cloud"
    echo -e "(Настройки -> API-ключи) для подтверждения через DNS.${NC}"
    if [ -n "$current_token" ]; then
        read -rp "API-токен Timeweb [уже задан, Enter — оставить как есть]: " input_token
    else
        read -rp "API-токен Timeweb: " input_token
    fi
    token="${input_token:-$current_token}"
    if [ -z "$token" ]; then
        warn "Токен не указан — домены запишутся в .env, но сертификаты не выпустятся,"
        warn "пока не допишете TIMEWEB_DNS_API_TOKEN в .env вручную и не примените снова."
    fi
fi

if [ -z "$panel_domain$mail_domain$storage_domain" ]; then
    log "Доменов не указано — .env не менялся, всё осталось как есть."
    exit 0
fi

[ -n "$panel_domain" ] && set_env_var PANEL_DOMAIN "$panel_domain"
[ -n "$mail_domain" ] && set_env_var MAIL_DOMAIN "$mail_domain"
[ -n "$storage_domain" ] && set_env_var STORAGE_DOMAIN "$storage_domain"
[ -n "$token" ] && set_env_var TIMEWEB_DNS_API_TOKEN "$token"
chmod 600 "$ENV_FILE"
log ".env обновлён."

echo
read -rp "Перезапустить backend/worker и применить изменения сейчас? [Y/n]: " apply
case "$apply" in
    [nN]*)
        log "Хорошо. Примените вручную: docker compose up -d backend worker"
        exit 0
        ;;
esac

log "Перезапуск backend и worker (подхватят новые переменные из .env)..."
docker compose up -d backend worker

log "Ожидание готовности API..."
ready=false
for i in $(seq 1 30); do
    if curl -sf -o /dev/null "http://127.0.0.1:8000/"; then
        ready=true
        break
    fi
    sleep 2
done

if [ "$ready" != true ]; then
    warn "Backend не ответил за отведённое время. Проверьте: docker compose logs backend --tail=50"
    warn "Конфиг Caddy можно применить вручную позже: панель -> «Домены» -> «Переприменить»."
    exit 0
fi

admin_token=$(get_env_var ADMIN_TOKEN)
if [ -z "$admin_token" ]; then
    warn "Не нашёл ADMIN_TOKEN в .env — не могу сам применить конфиг Caddy."
    warn "Зайдите в панель -> «Домены» -> «Переприменить»."
    exit 0
fi

log "Применяю конфиг Caddy (POST /api/domains/reapply)..."
# X-Admin-Token, не Authorization: Bearer — тот зарезервирован под JWT
# сессии после логина через веб (см. backend/app/core/auth.py,
# get_current_user: сырой ADMIN_TOKEN распознаётся только в X-Admin-Token).
REAPPLY=$(curl -s -X POST "http://127.0.0.1:8000/api/domains/reapply" \
    -H "X-Admin-Token: ${admin_token}")

if echo "$REAPPLY" | grep -q '"applied":true'; then
    log "Конфиг применён. Caddy подхватит домены в течение минуты и выпустит сертификаты через DNS-01."
else
    warn "Не удалось автоматически применить конфиг (ответ сервера: ${REAPPLY})."
    warn "Откройте панель -> «Домены» -> «Переприменить» вручную."
fi

echo
echo -e "${GREEN}=========================================================="
echo " Готово. Через 1-2 минуты проверьте:"
echo -e "==========================================================${NC}"
[ -n "$panel_domain" ] && echo "   https://${panel_domain}"
[ -n "$mail_domain" ] && echo "   https://${mail_domain}"
[ -n "$storage_domain" ] && echo "   https://${storage_domain}"
echo
echo " Логи Caddy, если сертификат не выпустился:"
echo "   docker logs aegis-caddy --tail 50"
