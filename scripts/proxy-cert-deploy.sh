#!/bin/sh
# Certbot deploy hook: runs inside Nginx Proxy Manager after successful renewal.
set -eu

/usr/sbin/nginx -t
/usr/sbin/nginx -s reload
printf '%s\n' 'OPIHA: renewed certificate deployed; nginx gracefully reloaded.'
