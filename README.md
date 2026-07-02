# Endpoint Central

A production-style, self-hosted Endpoint Management System built with FastAPI, SQLAlchemy, Redis, PostgreSQL, HTMX, and Bootstrap 5.

## Quick Start

```bash
# 1. Clone & configure
cp .env.example .env
# Edit .env: set SECRET_KEY, GATEWAY_API_KEY, DB passwords

# 2. Start all services
docker compose up -d

# 3. Open the dashboard
open http://localhost:8000

# Default credentials: admin / Admin@1234
```

## Architecture

| Service | Port | Purpose |
|---|---|---|
| `api-service` | 8000 | Web dashboard (FastAPI + Jinja2 + HTMX) |
| `agent-gateway` | 8001 | Agent communication endpoint |
| `command-worker` | — | Script/policy dispatch via Redis queue |
| `alert-worker` | — | Threshold monitoring, offline detection |
| `report-worker` | — | AI report generation via Ollama |
| `postgres` | 5432 | Primary database |
| `redis` | 6379 | Queue + pub/sub |

## Agent Deployment

### Linux
```bash
sudo bash agent-linux/install.sh \
  --gateway http://YOUR_SERVER:8001 \
  --key YOUR_GATEWAY_KEY
```

### Windows (run as Administrator)
```
# Edit agent-windows\agent_config.env first
agent-windows\install.bat
```

## Database Migrations

```bash
# Inside the api-service container
docker compose exec api-service alembic revision --autogenerate -m "init"
docker compose exec api-service alembic upgrade head
```

## AI Reports (Ollama)

1. Install Ollama: https://ollama.ai
2. Pull the model: `ollama pull llama3.1:8b`
3. Set `OLLAMA_BASE_URL` in `.env`
4. Generate reports from the Reports page

## Project Structure

```
endpoint-central/
├── docker-compose.yml
├── .env.example
├── server/
│   ├── app/
│   │   ├── main.py              # Dashboard FastAPI app
│   │   ├── gateway.py           # Agent gateway FastAPI app
│   │   ├── core/
│   │   │   ├── config.py        # pydantic-settings
│   │   │   └── security.py      # bcrypt + session signing
│   │   ├── db/
│   │   │   ├── session.py       # SQLAlchemy async engine
│   │   │   └── redis_client.py  # Redis pool
│   │   ├── models/models.py     # All 18 ORM models
│   │   ├── schemas/schemas.py   # Pydantic request/response schemas
│   │   ├── repositories/        # Repository pattern (BaseRepository + specifics)
│   │   ├── services/            # Business logic layer
│   │   ├── api/v1/endpoints/    # FastAPI routers
│   │   ├── workers/             # alert, command, report background workers
│   │   └── templates/           # Jinja2 HTML templates
│   └── alembic/                 # Database migrations
├── agent-windows/               # Windows agent (pywin32 service)
└── agent-linux/                 # Linux agent (systemd service)
```

## Features

- **Device Inventory** — register Windows/Linux agents, track status, IP, user, OS
- **Live Monitoring** — CPU/RAM/Disk metrics with auto-refreshing charts (HTMX)
- **Domains & Groups** — hierarchical tree + group assignment
- **Policy Engine** — disable USB, CMD, Task Manager, wallpaper, registry, sysctl
- **Script Repository** — PowerShell, CMD, Bash, Python scripts with one-click deploy
- **Software Inventory** — full installed software list per device, cross-device search
- **Software Deployment** — upload MSI/EXE/SH packages, deploy to device or group
- **Alerts** — threshold rules on CPU/RAM/Disk/Offline, auto-resolve, severity levels
- **Audit Logs** — all admin actions tracked with user, action, IP, timestamp
- **AI Reports** — daily/weekly/monthly executive reports via Ollama llama3.1:8b, PDF export
