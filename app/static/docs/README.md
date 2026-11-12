Swagger UI and ReDoc files for the API's /docs and /redoc pages, so they work without internet.

They are not stored in git. `airgap/fetch_docs_assets.sh` downloads the versions pinned in
`airgap/versions.env` (swagger-ui-dist, redoc) from the npm registry, checks each against its sha512 hash,
and writes them here; `airgap/build_bundle.sh` runs it, so the air-gapped bundles always contain them.
When these files are missing (for example in a fresh checkout), /docs and /redoc fall back to the CDN.
