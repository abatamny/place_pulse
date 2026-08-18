#!/bin/sh
set -eu

commit_sha="${1:-}"
repository_dir="/opt/placepulse"

case "$commit_sha" in
    ""|*[!0-9a-f]*)
        echo "A full Git commit SHA is required." >&2
        exit 2
        ;;
esac
if [ "${#commit_sha}" -ne 40 ]; then
    echo "A full Git commit SHA is required." >&2
    exit 2
fi
if [ ! -d "$repository_dir/.git" ] || [ ! -f "$repository_dir/.env" ]; then
    echo "PlacePulse must be provisioned in $repository_dir before automatic deployment." >&2
    exit 3
fi

cd "$repository_dir"
git fetch --depth=1 origin "$commit_sha"
git reset --hard FETCH_HEAD
test "$(git rev-parse HEAD)" = "$commit_sha"

docker compose up --build -d --remove-orphans

attempt=1
while [ "$attempt" -le 60 ]; do
    if docker compose exec -T web \
        wget -qO- http://127.0.0.1/api/health 2>/dev/null \
        | grep -q '"status":"ok"'; then
        docker compose ps
        echo "Deployed and verified commit $commit_sha."
        exit 0
    fi
    sleep 2
    attempt=$((attempt + 1))
done

docker compose ps
docker compose logs --tail=150
echo "The deployment did not become healthy in time." >&2
exit 1
