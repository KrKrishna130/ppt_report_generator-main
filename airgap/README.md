# PPT generator: air-gapped install

Two bundles, built on an online machine by `airgap/build_bundle.sh`. Copy **one** of them to the air-gapped
machine (Linux x86_64). Neither one downloads anything during install or at run time.

| Bundle | Use when | Target needs |
|---|---|---|
| `ppt-generator-airgap-docker-<ver>.tar.gz` | Docker is available | Docker Engine + Compose v2 |
| `ppt-generator-airgap-baremetal-<ver>.tar.gz` | No Docker | glibc ≥ 2.28 (RHEL/Rocky/Alma 8+, Ubuntu 20.04+, Debian 11+). For PDF and thumbnails: LibreOffice and poppler-utils from the target's own OS packages |

Both run the full stack: API, Temporal worker, dashboard, Redis, Temporal, OpenTelemetry collector, Jaeger,
Prometheus, Loki and Grafana. The LLM servers are **not** included: point the app at the ones already on the
network (`GEMMA_BASE_URL`, `GLM_BASE_URL`, OpenAI-compatible `/v1` endpoints).

## 1. Copy and verify

```bash
# on the air-gapped machine, in the folder holding the bundle and its .sha256 file
sha256sum -c ppt-generator-airgap-<kind>-<ver>.tar.gz.sha256
tar -xzf ppt-generator-airgap-<kind>-<ver>.tar.gz
cd ppt-generator-airgap-<kind>-<ver>
```

## 2a. Docker install

```bash
# point the app at your LLM server first (these are read by docker-compose.yml)
vi .env        # GEMMA_BASE_URL=http://<llm-host>:11434/v1   GLM_BASE_URL=http://<llm-host>:8001/v1
./install.sh   # verifies checksums, docker load of every image, docker compose up -d, waits for /health
```

- `host.docker.internal` in the URLs means "the Docker host" (mapped for Linux in the compose file). Use it when
  the LLM server runs on the same machine; otherwise use the LLM host's name or IP.
- Host ports can be changed in `.env`: `API_PORT`, `DASHBOARD_PORT`, `TEMPORAL_UI_PORT`, `GRAFANA_PORT`,
  `PROMETHEUS_PORT`, `JAEGER_UI_PORT`, `LOKI_PORT`, `REDIS_PORT`, `TEMPORAL_PORT`, `OTEL_GRPC_PORT`, `OTEL_HTTP_PORT`,
  `OTEL_PROM_PORT`, `JAEGER_OTLP_PORT`. Grafana login: `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` (default admin/admin).
- Day to day: `docker compose ps`, `docker compose logs -f api worker`, `docker compose down`, `docker compose up -d`.
- `./install.sh --load-only` loads the images without starting anything.

## 2b. Bare-metal install (no Docker, no root)

```bash
./install.sh            # verifies checksums, builds .venv from wheelhouse/, installs fonts, runs the test suite
vi ppt.env              # GEMMA_BASE_URL / GLM_BASE_URL, ports, ENABLE_OBSERVABILITY
./pptctl start          # starts everything in order and waits for Redis, Temporal and the API
./pptctl status         # ./pptctl logs api | worker | temporal | ... ; ./pptctl stop ; ./pptctl restart
```

- Everything lives in the bundle folder: data and logs in `var/`, generated decks in `generated/`.
- Redis, Temporal, Loki, Jaeger and the OTel collector listen on 127.0.0.1 only. The API, dashboard, Temporal UI,
  Grafana and Prometheus listen on `PUBLIC_HOST` (default `0.0.0.0`). Jaeger UI listens on port 16686.
- If ports 6379 or 7233 are already taken on the host, set `REDIS_PORT` / `TEMPORAL_PORT` in `ppt.env`.
- Temporal keeps its state in `var/temporal/temporal.db`, so queued jobs survive a restart. In the first
  ~30 s after start it may log a few `context deadline exceeded` errors for its own system workflow; they stop
  on their own.
- Grafana's first start takes about 90 s (database setup); later starts take a few seconds.
- `ENABLE_OBSERVABILITY=0` runs only Redis, Temporal, the API, worker and dashboard.
- To start the stack at boot, add `@reboot /path/to/bundle/pptctl start` to the service user's crontab, or wrap
  `pptctl start` / `pptctl stop` in a systemd unit.

## 3. Check it works

| URL | What |
|---|---|
| `http://<host>:8000/health` | `{"redis":"ok",...,"status":"ok"}` |
| `http://<host>:8000/health/temporal` | `{"status":"ok",...}` |
| `http://<host>:8000/docs` | Swagger UI |
| `http://<host>:5173` | Dashboard |
| `http://<host>:8233` | Temporal UI |
| `http://<host>:3000` | Grafana (Prometheus, Loki and Jaeger data sources are preconfigured) |
| `http://<host>:16686` / `:9090` | Jaeger / Prometheus |

Then send the sample request in `Payload_ppt.txt` (bare-metal bundle) or use the dashboard's
"Create presentation" page, and watch the job in the Temporal UI.

## Notes

- **Dashboard from other machines:** both installers add this host's names and IPs to `CORS_ORIGINS`. If users
  reach the server by another name, add `http://<name>:5173` to `CORS_ORIGINS` (`.env` for Docker, `ppt.env` for
  bare metal) and restart.
- **Proxy variables:** `pptctl` clears `ALL_PROXY` / `HTTP(S)_PROXY`; a SOCKS `ALL_PROXY` breaks the app's LLM calls.
- **Jobs fail with `quality score ... below MIN_QUALITY_SCORE`:** the validator found numbers that are not in the
  source (common with small models). Use a stronger model, or lower `MIN_QUALITY_SCORE` in `.env` for testing.
- Full app guide: `PPT_Backend_Guide.md` (bare-metal bundle).

## Building the bundles (online machine)

```bash
airgap/build_bundle.sh                 # both bundles into dist/
airgap/build_bundle.sh --docker-only   # or --baremetal-only
```

Needs Docker, git, curl, npm and a Python 3.12 environment with `requirements.txt` installed (`.venv`, or set
`PYTHON=`). Versions are pinned in `airgap/versions.env`; download checksums in `airgap/downloads.sha256`
(checked against the upstream release checksums when they were pinned). Ship a commit, not a dirty tree: the
bundle version is the git commit, with `-dirty` added if the tree has uncommitted changes.
