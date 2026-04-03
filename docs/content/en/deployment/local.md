---
title: "Local Setup"
weight: 0
---

Run IntentKit locally from the repository checkout. This path builds services from source and does not depend on published container images.

## Prerequisites

- Git
- Docker Desktop, or Colima plus the Docker CLI on macOS

## Clone the repository

```bash
git clone https://github.com/xian-technology/xian-intentkit.git
cd xian-intentkit
```

## Configure environment

```bash
cp .env.example .env
```

Edit `.env` and configure at least one LLM provider API key (e.g., `OPENAI_API_KEY`).

For local setup, you can usually start with:

- `OPENAI_API_KEY`
- `DB_*` values from the checked-in defaults
- the default local Redis and RustFS settings

## Start the stack

```bash
docker compose up --build
```

## Verify

Check that all containers are running:

```bash
docker compose ps
```

Check the logs for errors:

```bash
docker compose logs -f
```

Visit these local endpoints to confirm everything is working:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/redoc`
- Health endpoint: `http://localhost:8000/health`

## Direct process development

If you want to iterate on Python code without running the full compose stack, keep the backing services running and start the app directly:

```bash
docker compose up -d db redis rustfs
uv sync
uv run uvicorn app.api:app --reload
```

## Stop the stack

```bash
docker compose down
```

Note: Named volumes are preserved after stopping. To remove them as well:

```bash
docker compose down -v
```
