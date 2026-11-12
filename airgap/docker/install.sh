#!/usr/bin/env bash
# Install and start the PPT generator on an air-gapped machine with Docker + Compose v2.
# Makes NO network calls: images come from images/*.tar.gz, and pull_policy is "never".
#   tar -xzf ppt-generator-airgap-docker-*.tar.gz && cd ppt-generator-airgap-docker-* && ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "docker not found"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 ('docker compose') not found"; exit 1; }

echo "== verifying bundle checksums"
sha256sum -c --quiet SHA256SUMS

echo "== loading images (this takes a few minutes)"
for f in images/*.tar.gz; do
  echo "   $f"
  docker load -q -i "$f"
done

mkdir -p generated tmp
chmod 777 generated tmp   # the app containers write here

# Let browsers on other machines use the dashboard: allow this host's names/IPs as CORS origins,
# unless CORS_ORIGINS was already changed from the default.
if grep -qxF 'CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173' .env; then
  origins="http://localhost:5173,http://127.0.0.1:5173"
  for h in $(hostname) $(hostname -f 2>/dev/null) $(hostname -I 2>/dev/null); do
    case ",$origins," in *",http://$h:5173,"*) ;; *) origins="$origins,http://$h:5173" ;; esac
  done
  sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$origins|" .env
  echo "== CORS now allows: $origins"
fi

if [ "${1:-}" = "--load-only" ]; then
  echo "Images loaded. Start with: docker compose up -d"
  exit 0
fi

echo "== starting the stack"
docker compose up -d

echo "== waiting for the API"
port() { local v; v=$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2 || true); echo "${v:-$2}"; }
API_PORT=$(port API_PORT 8000)
for _ in $(seq 1 60); do
  if curl -fsS --noproxy '*' "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS --noproxy '*' "http://127.0.0.1:${API_PORT}/health" && echo || { echo "API did not become healthy; see: docker compose logs api"; exit 1; }
docker compose ps
cat <<EOF

PPT generator is running.
  API + Swagger   http://$(hostname):${API_PORT}/docs
  Dashboard       http://$(hostname):$(port DASHBOARD_PORT 5173)
  Temporal UI     http://$(hostname):$(port TEMPORAL_UI_PORT 8233)
  Grafana         http://$(hostname):$(port GRAFANA_PORT 3000)   (admin / admin unless changed in .env)
  Jaeger          http://$(hostname):$(port JAEGER_UI_PORT 16686)
  Prometheus      http://$(hostname):$(port PROMETHEUS_PORT 9090)
Set GEMMA_BASE_URL / GLM_BASE_URL in .env to your LLM server, then: docker compose up -d
EOF
