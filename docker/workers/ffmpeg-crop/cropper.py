"""Crop stills from screen recordings using events.jsonl bounding boxes."""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from pydantic import BaseModel


class BBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class CropSection(BaseModel):
    timestamp_ms: int
    bbox: BBox
    event_type: str | None = None


class TutorialSource(BaseModel):
    events_path: str
    video_path: str | None = None
    frames_dir: str | None = None


class CropJob(BaseModel):
    """Job JSON: paths to video, events.jsonl, and output directory."""

    video_path: str
    events_path: str
    output_dir: str = "./output"


def _int_from_ax(val: object) -> int | None:
    if val is None:
        return None
    try:
        if isinstance(val, bool):
            return None
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(round(val))
        s = str(val).strip()
        if "." in s:
            return int(float(s))
        return int(s)
    except (TypeError, ValueError):
        return None


def _bbox_from_bounding_box_dict(bb: object) -> BBox | None:
    """Parse ``boundingBox`` object (new schema)."""
    if not isinstance(bb, dict):
        return None
    x = _int_from_ax(bb.get("x"))
    y = _int_from_ax(bb.get("y"))
    w = _int_from_ax(bb.get("width"))
    h = _int_from_ax(bb.get("height"))
    if x is None or y is None or w is None or h is None:
        return None
    if w <= 0 or h <= 0:
        return None
    return BBox(x=x, y=y, width=w, height=h)


def _bbox_from_ax_snapshot(ax: dict) -> BBox | None:
    """
    Extract a crop rect from AxSnapshot: ``current``, then ``parents``, then ``children``.
    Parents are ordered immediate-parent-first (as emitted by the recorder).
    """
    current = ax.get("current")
    if isinstance(current, dict):
        bb = _bbox_from_bounding_box_dict(current.get("boundingBox"))
        if bb is not None:
            return bb

    parents = ax.get("parents")
    if isinstance(parents, list):
        for p in parents:
            if isinstance(p, dict):
                bb = _bbox_from_bounding_box_dict(p.get("boundingBox"))
                if bb is not None:
                    return bb

    children = ax.get("children")
    if isinstance(children, list):
        for c in children:
            if isinstance(c, dict):
                bb = _bbox_from_bounding_box_dict(c.get("boundingBox"))
                if bb is not None:
                    return bb

    return None


def _bbox_from_legacy_flat_ax(ax: dict) -> BBox | None:
    """Legacy flat map: ``bbox_x``, ``bbox_y``, ``bbox_width``, ``bbox_height``."""
    x = _int_from_ax(ax.get("bbox_x"))
    y = _int_from_ax(ax.get("bbox_y"))
    w = _int_from_ax(ax.get("bbox_width"))
    h = _int_from_ax(ax.get("bbox_height"))
    if x is None or y is None or w is None or h is None:
        return None
    if w <= 0 or h <= 0:
        return None
    return BBox(x=x, y=y, width=w, height=h)


def bbox_from_ax_attributes(ax: dict) -> BBox | None:
    """
    Primary bbox for cropping.

    - **AxSnapshot**: structured ``current`` / ``parents`` / ``children`` with
      ``boundingBox`` on each node (camelCase).
    - **Legacy**: flat ``bbox_*`` keys only.
    """
    if isinstance(ax.get("current"), dict):
        snap = _bbox_from_ax_snapshot(ax)
        if snap is not None:
            return snap

    if any(k in ax for k in ("bbox_x", "bbox_y", "bbox_width", "bbox_height")):
        return _bbox_from_legacy_flat_ax(ax)

    return None


def parse_events_jsonl(path: Path) -> tuple[int, list[CropSection]]:
    """
    Read events.jsonl: ``recording_start`` supplies ``timeUtcMs`` as the video baseline;
    other lines with ``timeUtcMs`` and a usable bbox in ``axAttributes`` become crop sections.
    """
    text = path.read_text(encoding="utf-8")
    base_ms: int | None = None
    sections: list[CropSection] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue

        et = obj.get("eventType")
        if et == "recording_start" and "timeUtcMs" in obj:
            base_ms = int(obj["timeUtcMs"])
            continue

        if "timeUtcMs" not in obj:
            continue
        ax = obj.get("axAttributes")
        if not isinstance(ax, dict):
            continue
        bb = bbox_from_ax_attributes(ax)
        if bb is None:
            continue
        sections.append(
            CropSection(
                timestamp_ms=int(obj["timeUtcMs"]),
                bbox=bb,
                event_type=str(et) if et is not None else None,
            )
        )

    if base_ms is None:
        raise ValueError(
            f"No recording_start with timeUtcMs in {path}"
        )
    return base_ms, sections


def load_crop_job(path: Path) -> CropJob:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Job JSON root must be an object")
    return CropJob.model_validate(data)


def _resolve_relative(raw: str, base: Path) -> Path:
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (base / p).resolve()


def resolve_job_paths(job: CropJob, job_file: Path) -> tuple[Path, Path, Path]:
    base = job_file.parent
    return (
        _resolve_relative(job.video_path, base),
        _resolve_relative(job.events_path, base),
        _resolve_relative(job.output_dir, base),
    )


def media_duration_seconds(video_path: str | Path) -> float | None:
    """Return container duration in seconds, or None if ffprobe is unavailable."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(r.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return None


def get_cropped_region(video: str, crop: CropSection, t_sec: float, out_path: str) -> None:
    bbox = crop.bbox
    vf = f"crop={bbox.width}:{bbox.height}:{bbox.x}:{bbox.y}"
    # -ss after -i: frame-accurate seek for still extraction (avoids empty output when mis-seeking).
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video,
        "-ss",
        str(t_sec),
        "-vf",
        vf,
        "-frames:v",
        "1",
        out_path,
    ]
    subprocess.run(cmd, check=True)


def get_full_frame(video: str, t_sec: float, out_path: str) -> None:
    # -ss after -i keeps this aligned with get_cropped_region's frame-accurate seek.
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video,
        "-ss",
        str(t_sec),
        "-frames:v",
        "1",
        out_path,
    ]
    subprocess.run(cmd, check=True)


def clamp_bbox_to_image(bbox: BBox, image_width: int, image_height: int) -> BBox | None:
    left = max(0, min(bbox.x, image_width))
    top = max(0, min(bbox.y, image_height))
    right = max(0, min(bbox.x + bbox.width, image_width))
    bottom = max(0, min(bbox.y + bbox.height, image_height))

    if right <= left or bottom <= top:
        return None
    return BBox(x=left, y=top, width=right - left, height=bottom - top)


def zoom_inset_bounds(bbox: BBox, image_width: int, image_height: int) -> BBox:
    margin = max(24, min(image_width, image_height) // 40)
    available_width = max(bbox.width, image_width - (margin * 2))
    available_height = max(bbox.height, image_height - (margin * 2))
    max_width = min(max(160, int(image_width * 0.34)), available_width)
    max_height = min(max(120, int(image_height * 0.34)), available_height)
    scale = min(max_width / bbox.width, max_height / bbox.height, 5.0)
    scale = max(scale, 2.0)
    width = min(max_width, int(round(bbox.width * scale)))
    height = min(max_height, int(round(bbox.height * scale)))

    bbox_center_x = bbox.x + (bbox.width / 2)
    if bbox_center_x < image_width / 2:
        x = image_width - width - margin
    else:
        x = margin

    target_center_y = bbox.y + (bbox.height / 2)
    y = int(round(target_center_y - (height / 2)))
    y = max(margin, min(y, image_height - height - margin))

    return BBox(x=x, y=y, width=width, height=height)


def annotate_frame(image_path: Path, bbox: BBox, output_path: Path) -> None:
    try:
        from PIL import Image, ImageDraw, ImageEnhance
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for tutorial PDF generation. Install requirements.txt."
        ) from exc

    with Image.open(image_path).convert("RGBA") as image:
        clamped = clamp_bbox_to_image(bbox, image.width, image.height)
        if clamped is None:
            raise ValueError(
                f"bbox {bbox.model_dump()} does not overlap image {image.width}x{image.height}"
            )

        focused = ImageEnhance.Brightness(image).enhance(0.42)
        rect = [
            clamped.x,
            clamped.y,
            clamped.x + clamped.width,
            clamped.y + clamped.height,
        ]
        target = image.crop(tuple(rect))
        focused.paste(target, (clamped.x, clamped.y))

        draw = ImageDraw.Draw(focused)
        stroke_width = max(4, min(image.width, image.height) // 180)
        draw.rectangle(rect, outline=(255, 255, 255, 255), width=stroke_width + 4)
        draw.rectangle(rect, outline=(255, 45, 45, 255), width=stroke_width)

        inset = zoom_inset_bounds(clamped, image.width, image.height)
        resized_target = target.resize((inset.width, inset.height))
        shadow = Image.new("RGBA", (inset.width + 16, inset.height + 16), (0, 0, 0, 75))
        focused.alpha_composite(shadow, (inset.x + 8, inset.y + 8))
        focused.paste(resized_target, (inset.x, inset.y))

        inset_rect = [
            inset.x,
            inset.y,
            inset.x + inset.width,
            inset.y + inset.height,
        ]
        draw.rectangle(inset_rect, outline=(255, 255, 255, 255), width=stroke_width + 6)
        draw.rectangle(inset_rect, outline=(16, 185, 129, 255), width=stroke_width)

        source_center = (
            clamped.x + (clamped.width / 2),
            clamped.y + (clamped.height / 2),
        )
        inset_anchor_x = inset.x if inset.x > source_center[0] else inset.x + inset.width
        inset_anchor = (inset_anchor_x, inset.y + (inset.height / 2))
        draw.line([source_center, inset_anchor], fill=(255, 255, 255, 230), width=stroke_width + 3)
        draw.line([source_center, inset_anchor], fill=(16, 185, 129, 255), width=stroke_width)
        focused.convert("RGB").save(output_path)


def write_tutorial_pdf(
    annotated_steps: list[tuple[CropSection, Path]],
    output_pdf: Path,
) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError(
            "reportlab is required for tutorial PDF generation. Install requirements.txt."
        ) from exc

    if not annotated_steps:
        raise ValueError("No annotated tutorial steps to write.")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = landscape(letter)
    margin = 36
    title_height = 58
    footer_height = 26
    image_max_width = page_width - (margin * 2)
    image_max_height = page_height - title_height - footer_height - (margin * 2)

    pdf = canvas.Canvas(str(output_pdf), pagesize=(page_width, page_height))
    for index, (section, image_path) in enumerate(annotated_steps, start=1):
        image = ImageReader(str(image_path))
        image_width, image_height = image.getSize()
        scale = min(image_max_width / image_width, image_max_height / image_height)
        drawn_width = image_width * scale
        drawn_height = image_height * scale
        image_x = margin + ((image_max_width - drawn_width) / 2)
        image_y = margin + footer_height

        pdf.setFillColor(colors.HexColor("#111827"))
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(margin, page_height - margin - 10, f"Step {index}")

        pdf.setFillColor(colors.HexColor("#4b5563"))
        pdf.setFont("Helvetica", 10)
        label = section.event_type or "interaction"
        pdf.drawString(
            margin,
            page_height - margin - 28,
            f"{label} at {section.timestamp_ms} ms",
        )

        pdf.drawImage(
            image,
            image_x,
            image_y,
            width=drawn_width,
            height=drawn_height,
            preserveAspectRatio=True,
            mask="auto",
        )

        pdf.setFillColor(colors.HexColor("#6b7280"))
        pdf.setFont("Helvetica", 9)
        bbox = section.bbox
        pdf.drawString(
            margin,
            margin - 4,
            f"Target bbox: x={bbox.x}, y={bbox.y}, width={bbox.width}, height={bbox.height}",
        )
        pdf.showPage()

    pdf.save()


def _first_existing_file(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _first_file_with_suffix(root: Path, suffixes: tuple[str, ...]) -> Path | None:
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in suffixes:
            return path
    return None


def resolve_tutorial_source(path: Path) -> TutorialSource:
    if path.is_dir():
        events = _first_existing_file(path, ("events.jsonl",))
        if events is None:
            raise ValueError(f"events.jsonl not found in {path}")
        video = _first_file_with_suffix(path, (".webm", ".mp4", ".mov", ".mkv"))
        frames = path / "frames"
        return TutorialSource(
            events_path=str(events),
            video_path=str(video) if video is not None else None,
            frames_dir=str(frames) if frames.is_dir() else None,
        )

    if path.name == "events.jsonl":
        return TutorialSource(events_path=str(path))

    if path.suffix.lower() == ".json":
        job = load_crop_job(path)
        video, events, _ = resolve_job_paths(job, path)
        return TutorialSource(events_path=str(events), video_path=str(video))

    raise ValueError(
        f"Unsupported tutorial source: {path}. Use a .ctx file, recording directory, events.jsonl, or job JSON."
    )


@contextlib.contextmanager
def extracted_context(path: Path):
    if path.suffix.lower() != ".ctx":
        yield path
        return

    with tempfile.TemporaryDirectory(prefix="context-pdf-") as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(temp_path)
        yield temp_path


def source_image_for_step(
    section: CropSection,
    base_ms: int,
    source: TutorialSource,
    temp_dir: Path,
) -> Path:
    if source.video_path:
        t_sec = (section.timestamp_ms - base_ms) / 1000.0
        if t_sec < 0:
            raise ValueError(
                f"timestamp_ms={section.timestamp_ms} is before recording_start={base_ms}"
            )
        frame_path = temp_dir / f"frame_{section.timestamp_ms}.png"
        get_full_frame(source.video_path, t_sec, str(frame_path))
        return frame_path

    if source.frames_dir:
        frames_dir = Path(source.frames_dir)
        candidates = (
            frames_dir / f"{section.timestamp_ms}.png",
            frames_dir / f"{section.timestamp_ms}.jpg",
            frames_dir / f"{section.timestamp_ms}.jpeg",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate

    raise ValueError(
        "No video or matching frame image found for tutorial PDF generation."
    )


def run_tutorial_pdf(input_path: Path, output_pdf: Path) -> None:
    with extracted_context(input_path) as source_root:
        source = resolve_tutorial_source(source_root)
        events_file = Path(source.events_path)
        base_ms, sections = parse_events_jsonl(events_file)
        if not sections:
            raise ValueError(
                "No tutorial steps: need events with timeUtcMs and a usable bbox in axAttributes."
            )

        with tempfile.TemporaryDirectory(prefix="context-pdf-frames-") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            annotated_steps: list[tuple[CropSection, Path]] = []
            for index, section in enumerate(sections, start=1):
                frame_path = source_image_for_step(section, base_ms, source, temp_dir)
                annotated_path = temp_dir / f"annotated_{index:04d}.png"
                annotate_frame(frame_path, section.bbox, annotated_path)
                annotated_steps.append((section, annotated_path))

            write_tutorial_pdf(annotated_steps, output_pdf.expanduser().resolve())


def run_crop(
    events_file: Path,
    video_path: Path,
    output_dir: Path,
) -> None:
    base_ms, crop_sections = parse_events_jsonl(events_file)
    if not crop_sections:
        raise ValueError(
            "No crop rows: need timeUtcMs and a bbox (AxSnapshot: current/parents/children "
            "boundingBox, or legacy bbox_x/y/width/height) in axAttributes"
        )

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem

    duration = media_duration_seconds(video_path)

    for crop in crop_sections:
        t_sec = (crop.timestamp_ms - base_ms) / 1000.0
        if t_sec < 0:
            print(
                f"skip timestamp_ms={crop.timestamp_ms}: negative media time {t_sec:.3f}s "
                f"(check recording_start timeUtcMs)",
                file=sys.stderr,
            )
            continue
        if duration is not None and t_sec >= duration:
            print(
                f"skip timestamp_ms={crop.timestamp_ms}: seek {t_sec:.3f}s >= "
                f"video duration {duration:.3f}s",
                file=sys.stderr,
            )
            continue

        get_cropped_region(
            str(video_path),
            crop,
            t_sec,
            str(output_dir / f"{stem}_{crop.timestamp_ms}.png"),
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crop still frames or build a tutorial PDF from a context recording."
    )
    parser.add_argument(
        "input_path",
        type=Path,
        help="Crop job JSON, .ctx file, recording directory, or events.jsonl",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        help="Write one tutorial PDF with full-frame screenshots and bbox overlays",
    )
    args = parser.parse_args()

    input_path = args.input_path.expanduser().resolve()
    if args.pdf is not None:
        if not input_path.exists():
            raise SystemExit(f"input not found: {input_path}")
        run_tutorial_pdf(input_path, args.pdf)
        return

    job_file = input_path
    if not job_file.is_file():
        raise SystemExit(f"job file not found: {job_file}")

    job = load_crop_job(job_file)
    video_path, events_file, out_dir = resolve_job_paths(job, job_file)

    if not events_file.is_file():
        raise SystemExit(f"events file not found: {events_file}")
    if not video_path.is_file():
        raise SystemExit(f"video not found: {video_path}")

    run_crop(events_file, video_path, out_dir)


if __name__ == "__main__":
    main()
