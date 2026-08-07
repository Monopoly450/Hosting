# Обычный образ caddy:2 не умеет проходить ACME DNS-01 — нужен плагин
# провайдера DNS, а он собирается в бинарник статически (модули Caddy —
# Go-плагины без динамической загрузки). Отсюда сборка через xcaddy вместо
# простого docker pull, см. backend/app/services/domains.py (_ensure_caddy_image).
FROM caddy:2-builder AS builder

RUN xcaddy build --with github.com/caddy-dns/timeweb

FROM caddy:2

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
