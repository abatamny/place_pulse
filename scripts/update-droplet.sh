#!/bin/sh
set -eu

repository_dir="${PLACEPULSE_REPOSITORY_DIR:-/opt/placepulse}"
branch="${1:-main}"
https_override="$repository_dir/deploy/digitalocean/compose.https.yaml"
https_config="$repository_dir/deploy/digitalocean/nginx.https.conf"
health_url="${PLACEPULSE_HEALTH_URL:-https://159.89.52.96/api/health}"

case "$branch" in
    ""|-*|*[!A-Za-z0-9._/-]*)
        echo "The branch name contains unsupported characters." >&2
        exit 2
        ;;
esac

if [ ! -d "$repository_dir/.git" ] || [ ! -f "$repository_dir/.env" ]; then
    echo "PlacePulse must be provisioned in $repository_dir first." >&2
    exit 3
fi
if [ ! -f "$https_override" ] || [ ! -f "$https_config" ]; then
    echo "The DigitalOcean HTTPS deployment files are missing." >&2
    exit 4
fi

cd "$repository_dir"

current_branch="$(git branch --show-current)"
if [ "$current_branch" != "$branch" ]; then
    echo "Expected branch $branch, but the repository is on $current_branch." >&2
    exit 5
fi

git pull --ff-only origin "$branch"

docker compose \
    -f compose.yaml \
    -f "$https_override" \
    config --quiet

docker compose \
    -f compose.yaml \
    -f "$https_override" \
    up -d --build --remove-orphans

attempt=1
while [ "$attempt" -le 60 ]; do
    if response="$(curl -fsS --max-time 5 "$health_url" 2>/dev/null)" \
        && printf '%s' "$response" | grep -q '"status":"ok"'; then
        docker compose \
            -f compose.yaml \
            -f "$https_override" \
            ps
        echo "Updated $branch and verified $health_url."
        exit 0
    fi
    sleep 2
    attempt=$((attempt + 1))
done

docker compose \
    -f compose.yaml \
    -f "$https_override" \
    ps
docker compose \
    -f compose.yaml \
    -f "$https_override" \
    logs --tail=150
echo "The deployment did not become healthy in time." >&2
exit 1
