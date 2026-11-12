#!/usr/bin/env bash
# Download the Swagger UI and ReDoc files the API serves at /docs and /redoc into app/static/docs
# (git-ignored), so the air-gapped bundles need no CDN. Versions and sha512 hashes are pinned in
# airgap/versions.env; a download that does not match is rejected. Called by build_bundle.sh;
# run it by hand to get offline /docs on a development machine.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a; . airgap/versions.env; set +a
DL="$ROOT/dist/downloads"; OUT="$ROOT/app/static/docs"
mkdir -p "$DL" "$OUT"

fetch_npm() {  # package version sha512 -> path of the verified tarball
  local pkg=$1 ver=$2 want=$3 file="$DL/$1-$2.tgz"
  if [ ! -s "$file" ]; then
    curl -fsSL --retry 3 -o "$file.part" "https://registry.npmjs.org/$pkg/-/$pkg-$ver.tgz"
    mv "$file.part" "$file"
  fi
  python3 - "$file" "$want" <<'PY' || { rm -f "$file"; exit 1; }
import base64, hashlib, sys
got = base64.b64encode(hashlib.sha512(open(sys.argv[1], "rb").read()).digest()).decode()
if got != sys.argv[2]:
    sys.exit(f"sha512 mismatch for {sys.argv[1]}")
PY
  echo "$file"
}

SWAGGER_TGZ=$(fetch_npm swagger-ui-dist "$SWAGGER_UI_VER" "$SWAGGER_UI_SHA512")
REDOC_TGZ=$(fetch_npm redoc "$REDOC_VER" "$REDOC_SHA512")
X=$(mktemp -d); trap 'rm -rf "$X"' EXIT
tar -xzf "$SWAGGER_TGZ" -C "$X" \
  package/swagger-ui-bundle.js package/swagger-ui.css package/favicon-32x32.png package/LICENSE
cp "$X"/package/swagger-ui-bundle.js "$X"/package/swagger-ui.css "$X"/package/favicon-32x32.png "$OUT/"
cp "$X/package/LICENSE" "$OUT/swagger-ui-LICENSE"
rm -rf "$X/package"
tar -xzf "$REDOC_TGZ" -C "$X" package/bundles/redoc.standalone.js package/LICENSE
cp "$X/package/bundles/redoc.standalone.js" "$OUT/"
cp "$X/package/LICENSE" "$OUT/redoc-LICENSE"
echo "docs assets: swagger-ui-dist $SWAGGER_UI_VER, redoc $REDOC_VER -> app/static/docs"
