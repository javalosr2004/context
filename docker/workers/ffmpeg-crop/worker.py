"""FFmpeg crop worker — extracts and crops single frames from video."""

import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DATA_DIR = Path("/data")

app = FastAPI(title="ffmpeg-crop-worker")


class BBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class CropRequest(BaseModel):
    timestamp_ms: int
    bbox: BBox


class CropJob(BaseModel):
    video_path: str  # relative to DATA_DIR, e.g. "input/recording.mp4"
    crops: list[CropRequest]
    output_dir: str = "output"  # relative to DATA_DIR


class CropResult(BaseModel):
    timestamp_ms: int
    output_path: str


class CropJobResponse(BaseModel):
    results: list[CropResult]
    errors: list[str]


def extract_cropped_frame(
    video: Path, timestamp_ms: int, bbox: BBox, output: Path
) -> None:
    """Seek to timestamp, crop bbox region, save as PNG."""
    seconds = timestamp_ms / 1000.0
    crop_filter = f"crop={bbox.w}:{bbox.h}:{bbox.x}:{bbox.y}"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(seconds),
        "-i", str(video),
        "-frames:v", "1",
        "-vf", crop_filter,
        str(output),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()}")


@app.post("/crop", response_model=CropJobResponse)
def crop_frames(job: CropJob):
    video = DATA_DIR / job.video_path
    if not video.is_file():
        raise HTTPException(404, f"Video not found: {job.video_path}")

    out_dir = DATA_DIR / job.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[CropResult] = []
    errors: list[str] = []

    for crop in job.crops:
        filename = f"{crop.timestamp_ms}ms_{uuid4().hex[:8]}.png"
        output_path = out_dir / filename

        try:
            extract_cropped_frame(video, crop.timestamp_ms, crop.bbox, output_path)
            results.append(CropResult(
                timestamp_ms=crop.timestamp_ms,
                output_path=str(Path(job.output_dir) / filename),
            ))
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            errors.append(f"ts={crop.timestamp_ms}ms: {e}")

    return CropJobResponse(results=results, errors=errors)


@app.get("/health")
def health():
    return {"status": "ok"}
