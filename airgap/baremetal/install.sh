#!/usr/bin/env bash
# Install the PPT generator on an air-gapped Linux x86_64 machine without Docker. Makes NO network calls.
#   tar -xzf ppt-generator-airgap-baremetal-*.tar.gz && cd ppt-generator-airgap-baremetal-* && ./install.sh
# Then: ./pptctl start
# Needs: Linux x86_64, glibc >= 2.28. For PDF export and thumbnails, LibreOffice (soffice) and
# poppler-utils (pdftoppm) must be installed from the target's own OS packages; PPTX works without them.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

[ "$(uname -m)" = "x86_64" ] || { echo "this bundle is for x86_64, not $(uname -m)"; exit 1; }
glibc=$(ldd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+$' || echo 0)
if [ "$(printf '%s\n2.28\n' "$glibc" | sort -V | head -1)" != "2.28" ]; then
  echo "glibc $glibc found; 2.28 or newer is required"; exit 1
fi

echo "== verifying bundle checksums"
sha256sum -c --quiet SHA256SUMS

echo "== Python environment (portable CPython 3.12, wheels from wheelhouse/ only)"
rm -rf .venv
runtime/python/bin/python3 -m venv .venv
.venv/bin/pip install -q --no-index --find-links wheelhouse -r requirements.lock

echo "== fonts (Liberation, used by the deck themes and PDF export)"
FONT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/fonts/ppt-generator"
mkdir -p "$FONT_DIR" && cp fonts/*.ttf "$FONT_DIR/"
if command -v fc-cache >/dev/null; then fc-cache -f "$FONT_DIR" >/dev/null; else echo "   warning: fc-cache not found; LibreOffice may not see the fonts"; fi

echo "== folders and config"
mkdir -p var/grafana/provisioning/datasources var/grafana/provisioning/dashboards generated tmp
cp conf/grafana-datasources.yaml var/grafana/provisioning/datasources/datasources.yaml
if [ ! -f ppt.env ]; then
  cp ppt.env.example ppt.env
  origins="http://localhost:5173,http://127.0.0.1:5173"
  for h in $(hostname) $(hostname -f 2>/dev/null) $(hostname -I 2>/dev/null); do
    case ",$origins," in *",http://$h:5173,"*) ;; *) origins="$origins,http://$h:5173" ;; esac
  done
  sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$origins|" ppt.env
  echo "   wrote ppt.env (CORS allows: $origins)"
fi

echo "== PDF tools"
command -v soffice >/dev/null || command -v libreoffice >/dev/null \
  && echo "   LibreOffice: found" || echo "   warning: LibreOffice not found; decks are PPTX only (PDF export is skipped)"
command -v pdftoppm >/dev/null && echo "   pdftoppm: found" || echo "   warning: pdftoppm (poppler-utils) not found; no slide thumbnails"

echo "== self-check (test suite)"
.venv/bin/python -m pytest -q -p no:cacheprovider tests | tail -3

cat <<EOF

Installed. Next:
  1. Edit ppt.env: GEMMA_BASE_URL / GLM_BASE_URL must point at your LLM server.
  2. ./pptctl start        (./pptctl status, ./pptctl logs api, ./pptctl stop)
EOF
