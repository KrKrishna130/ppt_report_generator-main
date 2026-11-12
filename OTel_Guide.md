# PP Generator Service — Observability & Monitoring Guide

Complete monitoring guide for the PP Generator Service built with FastAPI, React, Temporal, Redis, an LLM provider, Docker Compose, and OpenTelemetry.

This guide explains how to start the application, inspect application logs, trace requests, monitor service health, and observe CPU and memory usage.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Project Structure](#3-project-structure)
4. [Environment Configuration](#4-environment-configuration)
5. [Start the Application](#5-start-the-application)
6. [Service URLs](#6-service-urls)
7. [Docker Logs](#7-docker-logs)
8. [OpenTelemetry Configuration](#8-opentelemetry-configuration)
9. [Prometheus Metrics](#9-prometheus-metrics)
10. [Jaeger Distributed Tracing](#10-jaeger-distributed-tracing)
11. [Grafana Dashboards](#11-grafana-dashboards)
12. [Loki Application Logs](#12-loki-application-logs)
13. [CPU, RAM, and Memory Monitoring](#13-cpu-ram-and-memory-monitoring)
14. [Application and Service Health](#14-application-and-service-health)
15. [End-to-End Verification](#15-end-to-end-verification)
16. [Troubleshooting](#16-troubleshooting)
17. [Stop and Restart Services](#17-stop-and-restart-services)
18. [Security Recommendations](#18-security-recommendations)

---

## 1. Architecture

The application consists of the following services.

### Application services

| Service          | Responsibility                                                              |
| ---------------- | --------------------------------------------------------------------------- |
| React frontend   | User interface for submitting and monitoring presentation jobs              |
| FastAPI API      | Accepts requests, validates input, exposes health and status endpoints      |
| Temporal server  | Coordinates durable workflow execution                                      |
| Temporal worker  | Executes presentation generation activities                                 |
| Redis            | Supports application status, SSE, idempotency, or other configured features |
| LLM provider     | Generates presentation content                                              |
| PPT/PDF renderer | Produces PowerPoint and PDF outputs                                         |

### Observability services

| Service                 | Responsibility                                                              |
| ----------------------- | --------------------------------------------------------------------------- |
| OpenTelemetry SDK       | Creates traces and application metrics                                      |
| OpenTelemetry Collector | Receives and forwards telemetry                                             |
| Prometheus              | Stores and queries numerical metrics                                        |
| Jaeger                  | Stores and displays distributed traces                                      |
| Loki                    | Stores logs when a log ingestion pipeline is configured                     |
| Grafana                 | Displays dashboards, metrics, logs, and traces from configured data sources |

### Monitoring flow

```text
                         USER
                           |
                           v
                    React Frontend
                           |
                           v
                     FastAPI API
                           |
                           v
                    Temporal Server
                           |
                           v
                    Temporal Worker
                           |
                           v
                    LLM / PPT / PDF
                           |
             -----------------------------
             |             |             |
             v             v             v
           Traces        Metrics        Logs
             |             |             |
             v             v             v
       OTel Collector  Prometheus      Loki
             |             |             |
             v             +------|------+
           Jaeger                 |
             |                    v
             +----------------> Grafana
```

The diagram describes the intended architecture. Actual data flows depend on the exporters, receivers, and pipelines configured in Docker Compose and the Collector.

**Important distinction:**

- Prometheus is for metrics, not ordinary log lines.
- Jaeger is for distributed traces, not a general-purpose log viewer.
- Loki is for logs, provided logs are actually shipped to it.
- Grafana presents data from configured data sources; it does not automatically collect every kind of telemetry.

---

## 2. Prerequisites

Install or configure:

- Docker Desktop for Mac
- Docker Compose v2
- VS Code
- Git, if the project is managed with Git
- Ollama and the required model if using a local LLM

Verify Docker:

```bash
docker --version
docker compose version
docker info
```

If `docker info` fails, open Docker Desktop and wait until the Docker engine is running.

If using Ollama, verify the installed models:

```bash
ollama list
```

Check the Ollama API:

```bash
curl http://localhost:11434/api/tags
```

Make sure the configured model is installed and that the API or worker can reach the LLM provider.

---

## 3. Project Structure

The relevant files should resemble this structure:

```text
ppt_generation_service/
|
|-- app/
|   |-- main.py
|   |-- config.py
|   |-- worker.py
|   |-- telemetry.py
|   |-- services/
|   |   |-- llm.py
|   |   |-- pipeline.py
|   |   |-- render.py
|   |-- temporal/
|       |-- activities.py
|       |-- workflows.py
|
|-- frontend/
|
|-- observability/
|   |-- otel-collector.yaml
|   |-- prometheus.yml
|   |-- loki-config.yaml
|
|-- generated/
|-- tmp/
|-- docker-compose.yml
|-- requirements.txt
|-- .env
|-- .env.example
|-- .gitignore
|-- README.md
```

Your actual project may use slightly different filenames. Keep the existing application modules and add or update the telemetry files as required.

---

## 4. Environment Configuration

Create the local environment file if it does not exist:

```bash
cp .env.example .env
```

Edit `.env` in VS Code.

Typical settings for services communicating within Docker:

```dotenv
# Application
APP_ENV=development
LOG_LEVEL=INFO

# Redis
REDIS_URL=redis://redis:6379/0

# Temporal
TEMPORAL_ADDRESS=temporal:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=ppt_generation

# OpenTelemetry
OTEL_ENABLED=true
OTEL_SERVICE_NAME=ppt-generation-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
```

These are example values, not a guarantee that every variable is already supported by your code. Keep the names consistent with `app/config.py`, `app/telemetry.py`, and the actual Compose configuration.

For the worker, use its own service name:

```dotenv
OTEL_SERVICE_NAME=ppt-generation-worker
```

If the API and worker share `.env`, override the service name separately in each service's Compose `environment` section.

### Docker addresses versus local addresses

Inside Docker:

```text
Redis:       redis:6379
Temporal:    temporal:7233
Collector:   otel-collector:4317
```

From the Mac browser:

```text
Frontend:    http://localhost:5173
API:         http://localhost:8000
```

When Ollama runs on the Mac host, containers generally reach it through:

```text
http://host.docker.internal:11434
```

Do not put real API credentials in Git. Keep `.env` excluded by `.gitignore`.

---

## 5. Start the Application

Run all commands from the project root, where `docker-compose.yml` is located.

### Step 1: Validate the Compose configuration

```bash
docker compose config
```

Resolve any missing variables, YAML errors, or invalid service references before proceeding.

### Step 2: Create output folders

```bash
mkdir -p generated tmp
```

### Step 3: Build and start the services

```bash
docker compose up -d --build
```

### Step 4: Check container status

```bash
docker compose ps
```

### Step 5: Inspect startup logs

```bash
docker compose logs --tail=100 api worker temporal redis
```

Inspect observability services too:

```bash
docker compose logs --tail=100 otel-collector prometheus jaeger grafana loki
```

The service names in these commands must match your Compose file.

If a monitoring service is not defined, Docker Compose will report that it cannot find the service. Add the service and its configuration before expecting that monitoring feature to work.

---

## 6. Service URLs

These URLs assume the corresponding ports are published in Docker Compose.

| Component          | URL                                   | Purpose                                     |
| ------------------ | ------------------------------------- | ------------------------------------------- |
| Frontend           | http://localhost:5173                 | Presentation UI                             |
| FastAPI            | http://localhost:8000                 | Backend API                                 |
| Swagger            | http://localhost:8000/docs            | API testing                                 |
| ReDoc              | http://localhost:8000/redoc           | API documentation                           |
| API health         | http://localhost:8000/health          | Backend health                              |
| Temporal health    | http://localhost:8000/health/temporal | Temporal connectivity                       |
| Temporal UI        | http://localhost:8233                 | Workflow history                            |
| Jaeger             | http://localhost:16686                | Distributed tracing                         |
| Prometheus         | http://localhost:9090                 | Metrics queries                             |
| Prometheus targets | http://localhost:9090/targets         | Scrape health                               |
| Grafana            | http://localhost:3000                 | Monitoring dashboards                       |
| Collector metrics  | http://localhost:9464/metrics         | Collector metrics, if enabled and published |

Grafana credentials depend on the configured environment. Some demo configurations use `admin` / `admin`; check your `.env` and Compose settings.

Redis usually does not provide a browser dashboard by default. Its health can be checked using `redis-cli` or an appropriate health check.

---

## 7. Docker Logs

Docker logs are the first place to investigate application startup errors and exceptions.

### View backend logs

```bash
docker compose logs -f api
```

### View worker logs

```bash
docker compose logs -f worker
```

### View API and worker together

```bash
docker compose logs -f api worker
```

### View recent logs

```bash
docker compose logs --tail=200 api
```

### Filter errors

On macOS:

```bash
docker compose logs --tail=500 api 2>&1 \
  | grep -Ei 'error|exception|traceback|failed'
```

For worker errors:

```bash
docker compose logs --tail=500 worker 2>&1 \
  | grep -Ei 'error|exception|traceback|failed'
```

### View Collector logs

```bash
docker compose logs -f otel-collector
```

### View all services

```bash
docker compose logs -f
```

Press `Control + C` to stop following the logs. The containers continue running.

Docker captures the processes' standard output and standard error. If Python logs are not visible, check Python logging configuration, container startup, and whether the application writes logs to a file instead of stdout/stderr.

For readable logs, configure Python's logging system with timestamps, severity levels, logger names, and messages. Structured JSON logging can make filtering easier, but it must be configured separately.

---

## 8. OpenTelemetry Configuration

OpenTelemetry instrumentation should be initialized in the API and worker.

Typical integration points:

```text
app/telemetry.py
app/main.py
app/worker.py
app/services/llm.py
app/temporal/activities.py
```

### Recommended instrumentation

- FastAPI instrumentation for incoming HTTP requests
- HTTPX instrumentation for outgoing HTTP calls
- A logical LLM span around provider requests
- Activity spans around Temporal activities
- Application metrics for request counts, durations, and failures

The SDK must export telemetry to the Collector.

Typical Docker endpoint:

```text
http://otel-collector:4317
```

The Collector must expose an OTLP receiver and have correctly configured exporters and service pipelines.

### Check telemetry configuration

```bash
cat observability/otel-collector.yaml
```

Look for:

- OTLP receiver configuration
- Trace pipeline
- Metrics pipeline
- Log pipeline, if logs are required
- Exporters and their destination services

A receiver alone is insufficient. Data must also be connected to an exporter through the appropriate pipeline.

### Check Collector startup

```bash
docker compose logs --tail=200 otel-collector
```

Look for invalid YAML, unavailable exporters, connection errors, and rejected telemetry.

### Avoid sensitive telemetry attributes

Do not put the following in spans, metrics labels, or logs:

- API keys or authorization headers
- Complete prompts or source documents
- Passwords or secrets
- Uploaded confidential content
- Personal information that is not needed for diagnostics

Use a request ID or job ID when safe and useful, rather than recording the full user payload.

---

## 9. Prometheus Metrics

Open:

http://localhost:9090

Go to **Graph** or the query page.

### Step 1: Verify scrape targets

Open:

http://localhost:9090/targets

A target showing `UP` means Prometheus can scrape that target. It does not guarantee that every application metric is being exported.

### Step 2: Run basic queries

#### Target health

```promql
up
```

#### Total scraped targets that are up

```promql
sum(up)
```

#### CPU time metric, if exported

```promql
process_cpu_seconds_total
```

#### HTTP request count, if the metric exists

```promql
http_server_request_duration_seconds_count
```

#### Request rate, if the metric exists

```promql
sum(rate(http_server_request_duration_seconds_count[5m]))
```

These metric names are examples. The actual names depend on the instrumentation and exporter. Open Prometheus's metric browser or start typing a metric name to discover what is available.

### Useful monitoring metrics

| Metric category            | What it tells you                                                     |
| -------------------------- | --------------------------------------------------------------------- |
| Request count              | How many requests the application receives                            |
| Request duration           | How long requests take                                                |
| Error count                | How many requests or operations fail                                  |
| LLM duration               | How long provider calls take                                          |
| Workflow/activity duration | How long processing stages take                                       |
| Process memory             | Memory used by the instrumented process                               |
| Process CPU time           | Cumulative CPU time consumed                                          |
| Container CPU              | CPU usage of Docker containers                                        |
| Container memory           | Memory used by Docker containers                                      |
| Host CPU and memory        | Mac host resource utilization, when a suitable exporter is configured |

Application metrics, process metrics, container metrics, and host metrics are different. Exporting one does not automatically provide all the others.

---

## 10. Jaeger Distributed Tracing

Open:

http://localhost:16686

### Step 1: Generate application traffic

Use Swagger:

http://localhost:8000/docs

Submit a presentation request and allow the API and worker to process it.

### Step 2: Search for traces

1. Open Jaeger's Search page.
2. Select the API service, for example `ppt-generation-api`.
3. Choose a recent time range.
4. Click **Find Traces**.
5. Open a trace to inspect its spans.
6. Search for `ppt-generation-worker` separately.

### Step 3: Inspect the spans

Depending on the instrumentation, traces may include:

- Incoming HTTP request
- Outgoing HTTP client request
- `llm.chat`
- Temporal activity operations
- Other explicitly instrumented processing stages

Review span duration, error status, and relationships between spans to identify slow operations.

### If Jaeger is empty

Check:

```bash
docker compose logs --tail=200 otel-collector jaeger
```

Confirm:

1. Tracing is enabled.
2. The API and worker are configured to export traces.
3. The Collector accepts OTLP data.
4. The Collector's trace pipeline exports to Jaeger.
5. The exporter uses the correct hostname and port.
6. You generated traffic after starting the services.

A workflow can span multiple services and execute asynchronously. Continuous end-to-end trace relationships require context propagation across the workflow boundary; separate spans may appear if that is not implemented.

---

## 11. Grafana Dashboards

Open:

http://localhost:3000

### Step 1: Sign in

Use the Grafana credentials configured for your deployment.

### Step 2: Configure data sources

Navigate to **Connections → Data sources**.

Typical URLs inside a shared Docker network are:

| Data source | URL                        |
| ----------- | -------------------------- |
| Prometheus  | `http://prometheus:9090` |
| Loki        | `http://loki:3100`       |
| Jaeger      | `http://jaeger:16686`    |

The URLs depend on your Compose service names, network, and published ports. Use **Save & test** where available.

### Step 3: Explore metrics

1. Open **Explore**.
2. Select Prometheus.
3. Run:

```promql
up
```

4. Execute the query.
5. Switch between table and graph views.

### Step 4: Create a dashboard

Create panels for:

- API request rate
- Request duration
- Error rate
- LLM request duration
- Temporal activity duration
- Process memory
- Container CPU usage
- Container memory usage
- Service health

The queries must use metric names that actually exist in your environment.

### Step 5: Add alert rules

Once the metrics are available, create alerts for conditions such as:

- API error rate exceeding an agreed threshold
- Service targets becoming unavailable
- Container memory usage approaching its limit
- Sustained high CPU utilization
- LLM or workflow latency exceeding a threshold

Use thresholds appropriate to your workload. A threshold that is too sensitive will generate unnecessary alerts.

Grafana does not automatically create all dashboards or alerts just because the service is running.

---

## 12. Loki Application Logs

Loki stores log entries that are sent to it through a configured ingestion pipeline.

### Step 1: Check Loki

```bash
docker compose logs --tail=100 loki
```

### Step 2: Configure the Grafana data source

In Grafana, add or select Loki and configure the URL:

```text
http://loki:3100
```

### Step 3: Query logs

Open **Explore**, select Loki, and use the label browser to inspect the labels available in your actual log streams.

For example, if your stream has a `service_name` label:

```logql
{service_name="ppt-generation-api"}
```

If the label is `service` or `container`, use the label that actually exists.

### Step 4: Filter errors

If the label names and log format match your setup, a query such as the following can filter error text:

```logql
{service_name="ppt-generation-api"} |= "ERROR"
```

This is an example, not a guaranteed working query for every deployment.

### Important: logs must be shipped

The following command can show logs even when Grafana is empty:

```bash
docker compose logs -f api
```

That is because Docker's local logging output and Loki ingestion are separate paths.

To view Docker container logs in Grafana, configure a suitable log collection mechanism, such as a supported Docker log receiver or a correctly configured file receiver, and connect it to the Collector's logs pipeline or another log agent.

A Loki container by itself does not automatically ingest every Docker log.

---

## 13. CPU, RAM, and Memory Monitoring

CPU and memory should be monitored at three levels:

1. Mac host resources
2. Docker container resources
3. Application process resources

These measurements are related but not interchangeable.

### A. View container CPU and memory immediately

Run:

```bash
docker stats
```

This displays live resource usage for running containers, including CPU percentage and memory usage.

To inspect a single container:

```bash
docker stats <container_name>
```

Find the actual container name with:

```bash
docker compose ps
```

For a one-time snapshot:

```bash
docker stats --no-stream
```

This is the quickest way to see container resource consumption without adding any monitoring exporter.

### B. Monitor the Mac host

Open Activity Monitor on macOS.

Inspect:

- CPU tab for process CPU utilization
- Memory tab for application memory and memory pressure
- The Memory Pressure graph for overall memory conditions

Docker Desktop runs Linux containers inside a Linux VM on macOS. Container resource usage is not identical to the host's total resource usage.

### C. Export container metrics to Prometheus

For persistent dashboards, add a container metrics exporter such as cAdvisor, if compatible with your Docker Desktop environment.

The intended flow is:

```text
Docker containers
       |
       v
Container metrics exporter
       |
       v
Prometheus
       |
       v
Grafana dashboards
```

The exporter must be added to Docker Compose, and Prometheus must scrape the correct target. Do not expect container CPU or memory metrics in Prometheus until this is configured.

After enabling a compatible exporter, discover its actual metric names in Prometheus. Common cAdvisor metric families include:

```promql
container_cpu_usage_seconds_total
```

```promql
container_memory_usage_bytes
```

Example CPU usage rate for containers, where the metric is available:

```promql
sum by (name) (
  rate(container_cpu_usage_seconds_total[5m])
)
```

Example memory usage:

```promql
container_memory_usage_bytes
```

Metric labels vary by exporter version and runtime, so inspect the available labels before using them in dashboards.

### D. Monitor the Python process

Process instrumentation may export metrics such as:

```promql
process_cpu_seconds_total
```

```promql
process_resident_memory_bytes
```

The exact names depend on the instrumentation and exporter.

Process metrics describe the instrumented API or worker process, not the entire Docker container or Mac host.

### E. Monitor host CPU and memory

For host-wide metrics in Prometheus, use a compatible host metrics exporter and configure its scrape target.

On macOS, Linux-oriented host exporters running inside a Docker Desktop container may report metrics for the Linux VM rather than the Mac host itself. Use a suitable native host exporter if true macOS host metrics are required.

### F. Resource monitoring summary

| Resource                | Quick check                  | Persistent dashboard                          |
| ----------------------- | ---------------------------- | --------------------------------------------- |
| Container CPU           | `docker stats`             | Container exporter + Prometheus + Grafana     |
| Container RAM           | `docker stats`             | Container exporter + Prometheus + Grafana     |
| Python process RAM      | Process metrics, if exported | Prometheus + Grafana                          |
| Python process CPU time | Process metrics, if exported | Prometheus + Grafana                          |
| Mac CPU                 | Activity Monitor             | Compatible host monitoring agent              |
| Mac memory pressure     | Activity Monitor             | Suitable host-specific monitoring integration |
| LLM latency             | Application instrumentation  | Prometheus + Grafana                          |
| Workflow duration       | Activity instrumentation     | Prometheus + Grafana                          |
| Errors and stack traces | Docker logs                  | Loki ingestion + Grafana                      |

---

## 14. Application and Service Health

### API health

```bash
curl -i http://localhost:8000/health
```

### Temporal connectivity

```bash
curl -i http://localhost:8000/health/temporal
```

### Container status

```bash
docker compose ps
```

### Temporal workflows

Open:

http://localhost:8233

Inspect recent workflow executions, activity attempts, failures, and retry history.

### Redis connectivity

If `redis-cli` is available inside the Redis container:

```bash
docker compose exec redis redis-cli ping
```

Expected response:

```text
PONG
```

### Service logs

```bash
docker compose logs --tail=100 api worker temporal redis
```

A container being `Up` does not guarantee that the application is healthy. Check health endpoints, application logs, and dependencies as well.

---

## 15. End-to-End Verification

Follow these steps after the stack starts.

### Test 1: API

```bash
curl -i http://localhost:8000/health
```

Expected: a successful HTTP response if the application is healthy.

### Test 2: Swagger

Open:

http://localhost:8000/docs

Submit a small presentation request using the schema displayed by the running API.

### Test 3: Temporal

Open:

http://localhost:8233

Find the workflow execution associated with your submitted job.

### Test 4: Worker

```bash
docker compose logs -f worker
```

Check whether the worker starts the workflow activities and whether any activity fails.

### Test 5: Metrics

Open:

http://localhost:9090/targets

Check that configured Prometheus targets are up.

### Test 6: Traces

Open:

http://localhost:16686

Search for API and worker traces after generating traffic.

### Test 7: Logs

Open Grafana Explore and select Loki. Confirm that log streams exist before running queries.

### Test 8: Resource utilization

```bash
docker stats --no-stream
```

Confirm that the API, worker, Temporal, Redis, and monitoring containers have measurable resource usage.

### Test 9: Grafana

Open:

http://localhost:3000

Check data sources and run queries before building dashboards.

---

## 16. Troubleshooting

### Problem: Docker service is missing

Run:

```bash
docker compose config --services
```

If the requested service is not listed, it is not defined in the active Compose configuration.

### Problem: Port already in use

Check the container ports:

```bash
docker compose ps
```

Identify the process or container occupying the conflicting port. Change the relevant host port mapping if needed.

Avoid stopping unrelated containers unless you know they are safe to stop.

### Problem: No Prometheus metrics

Check:

```bash
docker compose logs --tail=200 prometheus
docker compose logs --tail=200 otel-collector
```

Verify scrape targets, metric exporters, the Collector's metrics pipeline, and network configuration.

### Problem: No Jaeger traces

Check:

```bash
docker compose logs --tail=200 otel-collector jaeger
```

Verify that the SDK exports traces, the Collector accepts OTLP, and its trace pipeline exports to Jaeger.

### Problem: Grafana has no logs

Check:

```bash
docker compose logs --tail=200 loki otel-collector
```

Verify that a log ingestion pipeline is configured and that logs reach Loki.

### Problem: CPU and RAM panels are empty

Run:

```bash
docker stats
```

If container usage is visible there but not in Grafana, the resource exporter, Prometheus scrape target, metric name, or dashboard query is probably missing or incorrect.

### Problem: Temporal workflow fails

Inspect:

```bash
docker compose logs --tail=200 api worker temporal
```

Then open the Temporal UI and inspect the failed activity and its error details.

### Problem: LLM request fails

Verify the configured provider, endpoint, model name, credentials if applicable, and network reachability from the worker container.

### Problem: Logs do not appear in Docker

Check whether the process writes to stdout/stderr, whether the container is restarting, and whether the service name in your command is correct.

---

## 17. Stop and Restart Services

### Stop the stack

```bash
docker compose down
```

### Restart the API

```bash
docker compose restart api
```

### Restart the worker

```bash
docker compose restart worker
```

### Rebuild after code changes

```bash
docker compose up -d --build api worker frontend
```

If you change the Collector configuration, recreate the Collector too:

```bash
docker compose up -d --force-recreate otel-collector
```

Use the actual service names from your Compose configuration.

### Remove containers and volumes

```bash
docker compose down -v
```

**Warning:** This can delete persistent Temporal, Redis, Grafana, or other monitoring data stored in named volumes. Do not use it for routine restarts.

---

## 18. Security Recommendations

- Never commit `.env` files containing real credentials.
- Keep API keys out of logs, trace attributes, and metrics labels.
- Avoid recording prompts and uploaded documents in telemetry.
- Restrict Grafana and other monitoring interfaces to trusted environments.
- Change default demo credentials.
- Avoid exposing Redis, Temporal, and the Collector publicly without appropriate security controls.
- Use reasonable log retention and volume limits.
- Avoid high-cardinality metric labels such as unique request IDs or full user prompts.
- Set resource limits only after measuring the application's actual workload.
- Review telemetry configuration before using the system with confidential or production data.

---

## Final Checklist

- [ ] Docker Desktop is running.
- [ ] `.env` is configured.
- [ ] API and worker are running.
- [ ] Redis and Temporal are reachable.
- [ ] Swagger accepts a test request.
- [ ] Temporal shows the workflow execution.
- [ ] Docker logs show application output.
- [ ] OpenTelemetry exports traces.
- [ ] Jaeger displays traces.
- [ ] Prometheus targets are up.
- [ ] Grafana data sources work.
- [ ] Loki receives logs, if log ingestion is configured.
- [ ] Container CPU and memory are visible in `docker stats`.
- [ ] CPU and memory metrics are exported before adding Grafana resource dashboards.

**Important:** Starting Grafana, Prometheus, Jaeger, Loki, and the Collector does not automatically enable every type of monitoring. Application metrics, container resource metrics, host resource metrics, logs, and traces each require the corresponding instrumentation, exporter, receiver, or scrape configuration.
