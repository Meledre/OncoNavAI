# OncoNavAI (Public Snapshot)

This is a shortened public repository intended for architecture and product demos.

## Included
- `backend/` — server-side logic and API
- `frontend/` — UI and client logic
- `infra/` — docker compose and runtime config

## Quick start (local)
```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build -d
```

## Public snapshot scope
- selected internal/service components are removed;
- test suites and vendor artifacts are not published;
- repository is intended for review and presentation.

## License
See `LICENSE` and `COPYRIGHT`.
