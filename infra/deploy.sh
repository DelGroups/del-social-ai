#!/usr/bin/env bash
# Deploy the latest origin/main on this server.
#
# Run by GitHub Actions over SSH as a *forced command*: the deploy key in
# ~/.ssh/authorized_keys can execute only this script, with no shell, no PTY
# and no forwarding. Any command the client sends is ignored.
# Migrations are NOT run here (see docs/decisions/001-multi-tenant-rls.md).
set -euo pipefail

APP_DIR=/opt/del-social-ai

# Everything lives in main() so bash has parsed the whole file before the
# `git reset` below replaces it on disk.
main() {
    cd "$APP_DIR"

    exec 9>/run/lock/del-social-deploy.lock
    if ! flock -n 9; then
        echo "!! another deploy is already running"
        exit 1
    fi

    echo "==> fetching origin/main"
    git fetch --quiet origin main
    local before after
    before=$(git rev-parse --short HEAD)
    # The server mirrors main exactly. Untracked and ignored files (.env) are kept.
    git reset --hard --quiet origin/main
    after=$(git rev-parse --short HEAD)
    echo "==> $before -> $after"

    echo "==> building and starting containers"
    docker compose up -d --build --remove-orphans

    echo "==> waiting for services to be healthy"
    for _ in $(seq 1 45); do
        if services_healthy && api_ready; then
            echo "==> deploy ok ($after)"
            docker image prune -f >/dev/null
            return 0
        fi
        sleep 2
    done

    echo "!! not healthy after 90s"
    docker compose ps
    docker compose logs --tail=40 api web
    exit 1
}

# True when every service that defines a healthcheck reports "healthy".
services_healthy() {
    ! docker compose ps --format '{{.Health}}' | grep -qvE '^(healthy|)$'
}

# API is up and can reach Postgres + Redis.
api_ready() {
    docker compose exec -T api python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)" \
        >/dev/null 2>&1
}

main "$@"
exit
