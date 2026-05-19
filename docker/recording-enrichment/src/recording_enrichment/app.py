from fastapi import FastAPI

app = FastAPI(title="recording-enrichment", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
