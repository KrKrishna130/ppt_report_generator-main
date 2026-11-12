#!/usr/bin/env bash
# Build the air-gapped bundles for the PPT generator. Run on a Linux x86_64 machine WITH internet,
# from a clean checkout of the commit you want to ship:
#   airgap/build_bundle.sh                  # both bundles
#   airgap/build_bundle.sh --docker-only    # or --baremetal-only
# Output in dist/:
#   ppt-generator-airgap-docker-<ver>.tar.gz      Docker images (app, dashboard, Redis, Temporal, monitoring) + compose
#   ppt-generator-airgap-baremetal-<ver>.tar.gz   portable Python + wheels, Redis/Temporal/monitoring binaries
# Each comes with a .sha256 file. Copy only the bundle you need to the air-gapped machine.
# Needs here: docker, git, curl, npm, sha256sum, python3 (3.12 for the wheel lock: .venv or PYTHON=...).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a; . airgap/versions.env; set +a

DO_DOCKER=1; DO_BARE=1
case "${1:-}" in
  --docker-only) DO_BARE=0 ;;
  --baremetal-only) DO_DOCKER=0 ;;
  "") ;;
  *) echo "usage: $0 [--docker-only|--baremetal-only]"; exit 1 ;;
esac

VERSION=$(git rev-parse --short HEAD)
if [ -n "$(git status --porcelain -- . ":!bench")" ]; then
  echo "warning: uncommitted changes; they are included and the version is marked -dirty"
  VERSION="$VERSION-dirty"
fi
DIST="$ROOT/dist"; DL="$DIST/downloads"; WORK="$DIST/work"
mkdir -p "$DL"
rm -rf "$WORK"; mkdir -p "$WORK"
echo "== version $VERSION"

# Swagger UI / ReDoc for offline /docs: downloaded and hash-checked into app/static/docs (git-ignored).
# Both the app image (COPY app/) and the bare-metal source copy pick them up from there.
airgap/fetch_docs_assets.sh

fetch() {  # url file
  if [ ! -s "$DL/$2" ]; then curl -fL --retry 3 -o "$DL/$2.part" "$1" && mv "$DL/$2.part" "$DL/$2"; fi
}
verify_downloads() { (cd "$DL" && sha256sum -c --quiet "$ROOT/airgap/downloads.sha256"); }

# Copy the tracked source tree as committed (plus uncommitted edits to tracked files), without bench/ etc.
export_source() {  # dest
  mkdir -p "$1"
  git ls-files -z --cached --others --exclude-standard -- app tests scripts examples/payloads examples/render_reference_samples.py pytest.ini \
      requirements.txt .env PPT_Backend_Guide.md Payload_ppt.txt OTel_Guide.md \
    | xargs -0 -I{} cp --parents {} "$1"
}

finish() {  # staging dir name -> dist/<name>.tar.gz + .sha256
  local name=$1
  # .env is left out: users edit it before running install.sh.
  (cd "$WORK/$name" && find . -type f ! -name SHA256SUMS ! -path ./.env -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
  tar -C "$WORK" -czf "$DIST/$name.tar.gz" "$name"
  (cd "$DIST" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
  du -h "$DIST/$name.tar.gz"
}

if [ "$DO_DOCKER" = 1 ]; then
  NAME="ppt-generator-airgap-docker-$VERSION"; S="$WORK/$NAME"
  APP_IMAGE="$IMG_APP_REPO:$VERSION"; DASH_IMAGE="$IMG_DASHBOARD_REPO:$VERSION"
  echo "== [docker] building $APP_IMAGE and $DASH_IMAGE"
  docker build -q -t "$APP_IMAGE" -f Dockerfile .
  docker build -q -t "$DASH_IMAGE" ppt_api_dashboard
  echo "== [docker] pulling pinned images"
  THIRD_PARTY="$IMG_REDIS $IMG_TEMPORAL $IMG_OTEL $IMG_JAEGER $IMG_PROMETHEUS $IMG_LOKI $IMG_GRAFANA"
  for img in $THIRD_PARTY; do docker pull -q --platform linux/amd64 "$img"; done

  mkdir -p "$S/images" "$S/observability"
  echo "== [docker] saving images"
  : > "$S/images/IMAGES.txt"
  for img in $APP_IMAGE $DASH_IMAGE $THIRD_PARTY; do
    f="$S/images/$(echo "$img" | tr '/:' '__').tar.gz"
    docker save "$img" | gzip -1 > "$f"
    echo "$img  $(docker image inspect -f '{{.Id}}' "$img")" >> "$S/images/IMAGES.txt"
    echo "   $img"
  done

  sed -e "s|@APP_IMAGE@|$APP_IMAGE|" -e "s|@DASHBOARD_IMAGE@|$DASH_IMAGE|" \
      -e "s|@IMG_REDIS@|$IMG_REDIS|" -e "s|@IMG_TEMPORAL@|$IMG_TEMPORAL|" -e "s|@IMG_OTEL@|$IMG_OTEL|" \
      -e "s|@IMG_JAEGER@|$IMG_JAEGER|" -e "s|@IMG_PROMETHEUS@|$IMG_PROMETHEUS|" -e "s|@IMG_LOKI@|$IMG_LOKI|" \
      -e "s|@IMG_GRAFANA@|$IMG_GRAFANA|" airgap/docker/docker-compose.yml > "$S/docker-compose.yml"
  if grep -q '@[A-Z_]*@' "$S/docker-compose.yml"; then echo "unreplaced placeholder in compose file"; exit 1; fi
  cp observability/otel-collector.yaml observability/prometheus.yml observability/loki-config.yaml "$S/observability/"
  cp airgap/docker/grafana-datasources.yaml "$S/observability/"
  cp .env "$S/.env"
  cp airgap/docker/install.sh "$S/install.sh"; chmod +x "$S/install.sh"
  cp airgap/README.md "$S/README.md"
  echo "$VERSION" > "$S/VERSION"
  finish "$NAME"
fi

if [ "$DO_BARE" = 1 ]; then
  NAME="ppt-generator-airgap-baremetal-$VERSION"; S="$WORK/$NAME"
  echo "== [bare metal] downloads"
  fetch "$PY_URL" "$PY_FILE";             fetch "$REDIS_URL" "$REDIS_FILE"
  fetch "$TEMPORAL_URL" "$TEMPORAL_FILE"; fetch "$OTEL_URL" "$OTEL_FILE"
  fetch "$JAEGER_URL" "$JAEGER_FILE";     fetch "$PROM_URL" "$PROM_FILE"
  fetch "$LOKI_URL" "$LOKI_FILE";         fetch "$GRAFANA_URL" "$GRAFANA_FILE"
  fetch "$FONTS_URL" "$FONTS_FILE"
  verify_downloads

  echo "== [bare metal] app source"
  export_source "$S"
  cp -r app/static/docs/. "$S/app/static/docs/"   # git-ignored, so export_source skips them
  mkdir -p "$S/bin" "$S/opt" "$S/fonts" "$S/licenses" "$S/runtime"

  echo "== [bare metal] Python runtime and wheelhouse (cp312, manylinux x86_64)"
  tar -xzf "$DL/$PY_FILE" -C "$S/runtime"                       # -> runtime/python
  PY=${PYTHON:-$ROOT/.venv/bin/python}
  "$PY" -c 'import sys; assert sys.version_info[:2]==(3,12), sys.version' \
    || { echo "set PYTHON to a Python 3.12 with requirements.txt installed (or create .venv)"; exit 1; }
  "$PY" -m pip install -q -r requirements.txt
  "$PY" -m pip freeze --exclude-editable | grep -v '^-e ' > "$S/requirements.lock"
  "$PY" -m pip download -q --no-cache-dir --only-binary=:all: --platform manylinux2014_x86_64 \
      --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 --python-version 3.12 \
      --implementation cp --abi cp312 -d "$S/wheelhouse" -r "$S/requirements.lock"

  echo "== [bare metal] dashboard (static build)"
  rm -rf "$WORK/dashboard-src" && mkdir -p "$WORK/dashboard-src"
  git ls-files -z --cached --others --exclude-standard ppt_api_dashboard | xargs -0 -I{} cp --parents {} "$WORK/dashboard-src"
  (cd "$WORK/dashboard-src/ppt_api_dashboard" && npm ci --no-audit --no-fund --loglevel=error && npm run -s build)
  cp -r "$WORK/dashboard-src/ppt_api_dashboard/dist" "$S/dashboard"

  echo "== [bare metal] Redis $REDIS_VER (compiled in $REDIS_BUILD_IMAGE for glibc >= 2.28)"
  docker run --rm --platform linux/amd64 -v "$DL:/dl:ro" -v "$S/bin:/out" "$REDIS_BUILD_IMAGE" bash -euc "
    dnf -y -q install gcc make tar gzip >/dev/null
    cd /tmp && tar -xzf /dl/$REDIS_FILE && cd redis-$REDIS_VER
    make -s -j\$(nproc) BUILD_TLS=no >/dev/null 2>&1
    install -m 755 src/redis-server src/redis-cli /out/
    cp LICENSE.txt /out/redis.LICENSE
    chown $(id -u):$(id -g) /out/redis-server /out/redis-cli /out/redis.LICENSE"
  mv "$S/bin/redis.LICENSE" "$S/licenses/redis.txt"

  echo "== [bare metal] Temporal, OTel collector, Jaeger, Prometheus, Loki, Grafana"
  X="$WORK/extract"; rm -rf "$X"; mkdir -p "$X"
  tar -xzf "$DL/$TEMPORAL_FILE" -C "$X" temporal LICENSE && mv "$X/temporal" "$S/bin/" && mv "$X/LICENSE" "$S/licenses/temporal-cli.txt"
  tar -xzf "$DL/$OTEL_FILE" -C "$X" otelcol-contrib && mv "$X/otelcol-contrib" "$S/bin/"
  tar -xzf "$DL/$JAEGER_FILE" -C "$X" && mv "$X/jaeger-$JAEGER_VER-linux-amd64/jaeger" "$S/bin/"
  tar -xzf "$DL/$PROM_FILE" -C "$X" && mv "$X/prometheus-$PROM_VER.linux-amd64/prometheus" "$S/bin/" \
    && cp "$X/prometheus-$PROM_VER.linux-amd64/LICENSE" "$S/licenses/prometheus.txt"
  python3 -c 'import sys,zipfile;zipfile.ZipFile(sys.argv[1]).extract("loki-linux-amd64",sys.argv[2])' "$DL/$LOKI_FILE" "$X" \
    && mv "$X/loki-linux-amd64" "$S/bin/loki"
  tar -xzf "$DL/$GRAFANA_FILE" -C "$X" && mv "$X/grafana-v$GRAFANA_VER" "$S/opt/grafana" \
    && cp "$S/opt/grafana/LICENSE" "$S/licenses/grafana.txt"
  tar -xzf "$DL/$FONTS_FILE" -C "$X" && cp "$X"/liberation-fonts-ttf-*/*.ttf "$S/fonts/" \
    && cp "$X"/liberation-fonts-ttf-*/LICENSE "$S/licenses/liberation-fonts.txt"
  chmod +x "$S"/bin/*

  cp -r airgap/baremetal/conf "$S/conf"
  cp airgap/baremetal/install.sh airgap/baremetal/pptctl airgap/baremetal/ppt.env.example "$S/"
  chmod +x "$S/install.sh" "$S/pptctl"
  cp airgap/README.md "$S/README.md"
  echo "$VERSION" > "$S/VERSION"
  finish "$NAME"
fi

rm -rf "$WORK"
echo "== done"; ls -lh "$DIST"/*.tar.gz*
