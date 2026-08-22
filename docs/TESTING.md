# Testing Guide

## Backend
- Run all tests (default SQLite unless `POSTGRES_URL` is set):
  ```bash
  cd backend
  pytest
  ```
- For Postgres: export `POSTGRES_URL=postgresql://user:pass@host:5432/dbname` before running.

## Frontend
```bash
cd frontend
npm run lint
npm run build
```

## With Docker Services Up
```bash
docker compose up -d
```
Then run the same test commands; they will use your env (Qdrant/ML/Postgres) if pointed there.

## Quick Manual Checks (Docker)
- Backend health: `curl http://localhost:8081/healthz`
- ML health: `curl http://localhost:18000/health`
- Sign in (get JWT):
  `curl -X POST http://localhost:8081/api/auth/signin -H "Content-Type: application/json" -d '{"email":"user@example.com","password":"SecurePass123!"}'`
- Ingest:
  `curl -X POST http://localhost:8081/api/ingest -H "Authorization: Bearer YOUR_ACCESS_TOKEN" -F "file=@/path/doc.pdf"`
- Query:
  `curl -X POST http://localhost:8081/api/query -H "Authorization: Bearer YOUR_ACCESS_TOKEN" -H "Content-Type: application/json" -d '{"q":"hello"}'`

## Troubleshooting
- Docker ports: backend 8081, ML 18000, Qdrant 6335, Postgres 5433, RabbitMQ 5672.
- Local dev ports: backend 8080, ML 8000, Qdrant 6333, Postgres 5432.
- Logs: `docker compose logs -f backend worker ml-service`.
