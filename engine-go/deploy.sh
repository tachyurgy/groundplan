#!/usr/bin/env bash
# Build the linux/amd64 binary here, build the tiny image on Box B, (re)start gp-go-api and register it with kamal-proxy.
set -euo pipefail
cd "$(dirname "$0")"
SHA=$(git rev-parse --short HEAD)
BOX=${BOX:-root@5.78.227.227}
KEY=${KEY:-$HOME/.ssh/hetzner_ed25519}
STAGE=$(mktemp -d)
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -tags timetzdata -trimpath -ldflags "-s -w -X main.version=$SHA" -o "$STAGE/gp-api" ./cmd/gp-api
cp Dockerfile "$STAGE/"
cp ../fixtures/documents/eval-latest.json "$STAGE/" 2>/dev/null || echo '{}' > "$STAGE/eval-latest.json"
tar czf "$STAGE.tgz" -C "$STAGE" .
scp -q -i "$KEY" "$STAGE.tgz" "$BOX:/root/groundplan/gp-go-api.tgz"
rm -rf "$STAGE" "$STAGE.tgz"
ssh -i "$KEY" "$BOX" "set -e
  rm -rf /root/groundplan/src-go && mkdir -p /root/groundplan/src-go && tar xzf /root/groundplan/gp-go-api.tgz -C /root/groundplan/src-go && rm /root/groundplan/gp-go-api.tgz
  cd /root/groundplan/src-go && flock /root/groundplan/.build.lock docker build -q -t gp-go-api:$SHA -t gp-go-api:latest .
  docker rm -f gp-go-api 2>/dev/null || true
  SEED=''
  # optional seed override (GP_SEED_PATH): lets the live twin pin the seed the live Python API is running
  if [ -f /root/groundplan/go-seed.json ]; then SEED='-v /root/groundplan/go-seed.json:/app/seed.json:ro -e GP_SEED_PATH=/app/seed.json'; fi
  docker run -d --name gp-go-api --restart unless-stopped --network kamal --memory 96m --env-file /root/groundplan/go-api.env \$SEED gp-go-api:latest
  for i in \$(seq 1 30); do [ \"\$(docker inspect -f '{{.State.Health.Status}}' gp-go-api)\" = healthy ] && break; sleep 1; done
  docker logs --tail 5 gp-go-api
  docker exec kamal-proxy kamal-proxy deploy gp-go-api --target gp-go-api:8080 --host gp-go-api.levelbrook.com --tls --health-check-path /health --deploy-timeout 60s
  docker image prune -f >/dev/null"
echo "deployed gp-go-api $SHA"
