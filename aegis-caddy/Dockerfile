# Обычный образ caddy:2 не умеет проходить ACME DNS-01 — нужен плагин
# провайдера DNS, а он собирается в бинарник статически (модули Caddy —
# Go-плагины без динамической загрузки). Отсюда сборка через xcaddy вместо
# простого docker pull, см. backend/app/services/domains.py (_ensure_caddy_image).
FROM caddy:2-builder AS builder

# Оба провайдера сразу: какой из них использовать, решает Caddyfile по тому,
# какой токен задан в .env (см. domains.py, DNS_PROVIDERS). Собирать образ
# заново при смене провайдера не нужно — плагин без токена просто не
# задействуется, а пересборка на живом сервере это лишние пара минут простоя.
RUN xcaddy build \
    --with github.com/caddy-dns/timeweb \
    --with github.com/caddy-dns/cloudflare

FROM caddy:2

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
