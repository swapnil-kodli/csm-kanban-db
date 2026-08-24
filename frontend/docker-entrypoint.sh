#!/bin/sh
set -e

# Give the backend's DNS name up to 30s to appear. nginx resolves upstreams at
# config-load time, so starting before the name exists is a hard failure.
i=0
while [ "$i" -lt 30 ]; do
  if getent hosts backend >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

if ! getent hosts backend >/dev/null 2>&1; then
  echo "signal-cs: 'backend' still unresolved after ${i}s; starting nginx anyway" >&2
fi

exec nginx -g 'daemon off;'
