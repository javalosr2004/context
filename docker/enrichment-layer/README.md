# enrichment-layer

Tiny MVP: `POST /query {request}` →
LLM-generated search queries → fan-out to Brave → fetch pages → extract main text + structural features → persist (SQLite index + filesystem blobs).

## Run

```bash
cd docker/enrichment-layer
uv venv && source .venv/bin/activate
uv pip install -e .
cp .env.example .env  # add OPENAI_API_KEY (+ BRAVE_API_KEY when ready)
uvicorn enrichment.app:app --reload
```

Then:

```bash
curl -X POST localhost:8000/query -H 'content-type: application/json' \
  -d '{"request":"how do I export a PNG from a Figma frame?"}'
```

## Layout

```
data/
  index.db                  SQLite index (runs, searches, pages, parsed)
  runs/{run_id}/meta.json   per-run metadata + plan
  pages/{hash}.html         raw HTML
  parsed/{hash}.json        extracted text + features
```

## Tests

```bash
uv pip install --group dev
pytest
```

Pipeline tests stub out OpenAI / Brave / HTTP — no network.

## Not built yet

JS classifier, Playwright rendering, ApplicationResolver, domain cache, Alembic. Add when needed.
