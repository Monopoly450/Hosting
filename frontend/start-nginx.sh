#!/bin/sh
mkdir -p /etc/nginx/ssl
if [ ! -f /etc/nginx/ssl/nginx.key ]; then
    echo "Generating self-signed SSL certificate for Aegis Admin Panel..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/nginx.key \
        -out /etc/nginx/ssl/nginx.crt \
        -subj "/C=RU/ST=Aegis/L=Aegis/O=Aegis/CN=localhost"
fi
exec nginx -g "daemon off;"
