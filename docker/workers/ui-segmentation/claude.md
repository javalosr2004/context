# ui-segmentation

Find a **sub-image (query) inside a larger target image** using dense
patch-token cosine similarity. This is the "feature-map localization" path:
instead of sliding a detector across hundreds of target windows, we encode the
query once, encode the target once, and compare in feature space.

Sits alongside the other docker-worker siblings (`ffmpeg-crop`, `omniparser`)
and will eventually expose the same FastAPI contract. Today it is a standalone
CLI — Docker/HTTP gets added once the algorithm is dialed in.

## Why

The Electron app (`../../../electron`) captures screen recordings and needs to
locate specific UI elements (buttons, list rows, icons) across frames and
across apps. Pixel-level template matching is fragile to anti-aliasing,
rendering differences, and small scale changes. Running a full detector per
target is wasteful when the goal is "where does *this* thing appear in *that*
screenshot." Patch-token cosine gets us robust, scale-tolerant localization at
roughly the cost of two forward passes.

## How it works

```
query image  ─▶ encoder ─▶ q_map   [C, Hq, Wq]  ─┐
                                                  ├─▶ similarity map ─▶ top-K bboxes
target image ─▶ encoder ─▶ t_map   [C, H,  W ]  ─┘
```

Per scale:

1. **Encode** with a dense patch-token backbone (default DINOv2 ViT-S/14).
   Images are right/bottom-padded to a multiple of the patch size so the
   pixel→patch mapping stays interpretable. Feature maps are L2-normalized
   along the channel dimension so dot products are cosine similarities.
2. **Combine two similarity signals**:
   - *mean-pooled cosine*: average query vector ⋅ each target cell. Smooth,
     global semantic match.
   - *2D normalized cross-correlation*: `conv2d(t_map, q_map, padding='same')`
     divided by query cell count. Captures spatial pattern (icon-then-text,
     etc.).
   Blended 50/50 by default (tunable).
3. **Upsample** the similarity map bilinearly to target pixel resolution.

Across scales we keep the elementwise max for scale robustness. Greedy NMS
with the query's pixel size as suppression window extracts the top-K peaks.

## Layout

- `embedder.py`      — `DinoV2Embedder` returning `[C, H, W]` L2-normalized patch-token feature maps. Pluggable via an `Embedder` Protocol.
- `localize.py`      — core algorithm + CLI entrypoint.
- `requirements.txt` — torch, torchvision, Pillow, numpy, matplotlib.
- `.gitignore`       — ignores `.venv/`, `output/`, caches.
- `output/`          — CLI results (heatmap + matches).

## CLI

```bash
python localize.py <query.png> <target.png> -o ./output \
    [--top-k 5] [--scales 0.85 1.0 1.15] [--no-ncc] \
    [--backbone dinov2_vits14] [--device mps|cuda|cpu] [--no-display]
```

Outputs:

- `output/heatmap.jpeg` — target with jet heatmap overlay + green top-K bboxes and score labels.
- `output/matches.json` — `{query, target, scales, boxes:[{rank, x, y, w, h, score}]}`.

First run downloads DINOv2 weights (~80 MB for ViT-S/14) to
`~/.cache/torch/hub/`. Device auto-picks `cuda > mps > cpu`, with
`PYTORCH_ENABLE_MPS_FALLBACK=1` set before torch import (same pattern as
`../omniparser/parser.py`).

## Current status

- CLI works end-to-end on Apple Silicon via MPS.
- Smoke-tested on `query_1.png` (a 190×24 file-tree row) against
  `target_1.png` (a full IDE screenshot). DINOv2 features localize, but for
  very thin queries (≤2 patches tall) the mean-pooled term dominates and
  pulls peaks toward generic dark UI rows. NCC carries most of the signal in
  that regime.

### Known next-up improvements

1. `--ncc-weight` flag so the mean/NCC blend is tunable; consider defaulting
   to NCC-heavy (~0.8) for thin queries.
2. Mean-center features before similarity (subtract the target's spatial-mean
   feature vector) to wash out generic-UI background direction.
3. Widen NMS window beyond query size (e.g. `max(qw, 2·qh)`) so thin rows
   don't re-win adjacent pixels.
4. Try `dinov2_vitb14` to see if backbone capacity alone fixes the thin-query
   failure mode.

## Roadmap

1. Tune the algorithm on a small eval set (deterministic crops from
   `../ffmpeg-crop/samples/`), tracking IoU@1 and recall@5 across scales.
2. FastAPI wrapper in `worker.py` (`POST /localize`, `GET /health`) mirroring
   `../ffmpeg-crop/worker.py`. Port 8200 in `../../docker-compose.yml`.
3. `Dockerfile` (python:3.12-slim + torch CPU wheels) and `setup_weights.py`
   to pre-bake DINOv2 weights into the image, matching how
   `../omniparser/setup_weights.py` handles YOLO/Florence.
4. Target-embedding cache keyed by `sha256(target_bytes) + backbone + scale`
   so batch queries against the same screenshot pay encoding cost once.
5. Wire into the Electron `Annotator` view as a "find similar region" action,
   reusing the shared `/data` volume contract used by `ffmpeg-crop`.
