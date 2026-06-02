# recording-enrichment

Backend service that enriches macOS UI recording bundles uploaded from the Swift app.

Phase 0: skeleton only — exposes `/health` and ships a `/data` volume.

## Run locally

```bash
docker compose up recording-enrichment
curl http://localhost:7100/health
```

Subsequent phases add bundle upload, Holo description worker, SSE progress, and optional gui-grounding verification.
