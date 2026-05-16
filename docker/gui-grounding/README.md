# Holo GUI Grounding

FastAPI service that adapts H Company Holo3 element localization to the `context-app` grounding response schema.

## Run

Create a local env file:

```bash
cp .env.example .env
```

Then set `HAI_API_KEY` in `.env`.

```bash
cd docker/gui-grounding
./run.sh
```

Point `context-app` at:

```bash
CONTEXT_GROUNDING_ENDPOINT=http://localhost:8080
```

The frontend appends `/predict` when needed.

For Docker, pass the same file at runtime:

```bash
docker build -t gui-grounding .
docker run --env-file .env -p 8080:8080 gui-grounding
```

## API

`POST /predict` accepts multipart form data:

- `input_image`: screenshot image file
- `instruction`: text description of the target element

Holo returns a point in `[0, 1000]`. This service returns the frontend-compatible schema and creates a deterministic bounding box centered on that point:

```json
{
  "point": {"x": 0.5, "y": 0.5},
  "point_pixel": {"x": 640, "y": 360},
  "bbox": {"x1": 0.46, "y1": 0.47, "x2": 0.54, "y2": 0.53},
  "bbox_pixel": {"x1": 588.8, "y1": 338.4, "x2": 691.2, "y2": 381.6},
  "bbox_score": null,
  "bbox_label": "the Sign in button",
  "bbox_source": "holo3_point_box",
  "image_size": {"width": 1280, "height": 720},
  "num_detections": 1
}
```

## Configuration

- `HAI_API_KEY`: required H Company API key
- `HAI_BASE_URL`: optional, defaults to `https://api.hcompany.ai/v1/`
- `HOLO_MODEL`: optional, defaults to `holo3-35b-a3b`
- `HOLO_BBOX_WIDTH_RATIO`: optional, defaults to `0.08`
- `HOLO_BBOX_HEIGHT_RATIO`: optional, defaults to `0.06`
