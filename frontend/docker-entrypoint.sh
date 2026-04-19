#!/bin/sh
set -e

if [ -z "$BASIC_AUTH_USER" ] || [ -z "$BASIC_AUTH_PASS" ]; then
    echo "ERROR: BASIC_AUTH_USER and BASIC_AUTH_PASS must be set" >&2
    exit 1
fi

printf '%s:%s\n' \
    "$BASIC_AUTH_USER" \
    "$(openssl passwd -apr1 "$BASIC_AUTH_PASS")" \
    > /etc/nginx/.htpasswd

exec nginx -g 'daemon off;'
