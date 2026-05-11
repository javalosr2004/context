"""Crop stills from screen recordings using events.jsonl bounding boxes."""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
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
    title: str | None = None
    description: str | None = None


class TutorialSource(BaseModel):
    events_path: str
    video_path: str | None = None
    frames_dir: str | None = None


class CropJob(BaseModel):
    """Job JSON: paths to video, events.jsonl, and output directory."""

    video_path: str
    events_path: str
    output_dir: str = "./output"


class TutorialMetadata(BaseModel):
    recording_name: str
    recorded_at_ms: int


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


def _bbox_from_selected_snapshot_node(ax: dict) -> BBox | None:
    selected = ax.get("selected")
    if selected == "user_override":
        override = ax.get("userOverride")
        if isinstance(override, dict):
            return _bbox_from_bounding_box_dict(override.get("boundingBox"))
        return None

    if selected == "current":
        current = ax.get("current")
        if isinstance(current, dict):
            return _bbox_from_bounding_box_dict(current.get("boundingBox"))
        return None

    if not isinstance(selected, str) or ":" not in selected:
        return None

    group, raw_index = selected.split(":", 1)
    if group not in ("parents", "children"):
        return None
    try:
        index = int(raw_index)
    except ValueError:
        return None

    nodes = ax.get(group)
    if not isinstance(nodes, list) or index < 0 or index >= len(nodes):
        return None
    node = nodes[index]
    if not isinstance(node, dict):
        return None
    return _bbox_from_bounding_box_dict(node.get("boundingBox"))


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
        selected = _bbox_from_selected_snapshot_node(ax)
        if selected is not None:
            return selected

        snap = _bbox_from_ax_snapshot(ax)
        if snap is not None:
            return snap

    if any(k in ax for k in ("bbox_x", "bbox_y", "bbox_width", "bbox_height")):
        return _bbox_from_legacy_flat_ax(ax)

    return None


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(text.split())


def _looks_like_pointer_description(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("(") and stripped.endswith(")") and "," in stripped


def _text_from_annotation(obj: dict, ax: dict, key: str, event_type: str | None) -> str | None:
    for source in (obj, ax):
        text = _clean_text(source.get(key))
        if text and text != event_type and not _looks_like_pointer_description(text):
            return text

    annotation = obj.get("annotation")
    if isinstance(annotation, dict):
        text = _clean_text(annotation.get(key))
        if text and text != event_type and not _looks_like_pointer_description(text):
            return text

    return None


def _selected_ax_node(ax: dict) -> dict | None:
    selected = ax.get("selected", "current")
    if selected == "current":
        current = ax.get("current")
        return current if isinstance(current, dict) else None
    if not isinstance(selected, str) or ":" not in selected:
        return None
    group, raw_index = selected.split(":", 1)
    try:
        index = int(raw_index)
    except ValueError:
        return None
    nodes = ax.get(group)
    if not isinstance(nodes, list) or index < 0 or index >= len(nodes):
        return None
    node = nodes[index]
    return node if isinstance(node, dict) else None


def _target_text_from_snapshot(ax: dict) -> str | None:
    node = _selected_ax_node(ax)
    if node is None:
        node = ax.get("current") if isinstance(ax.get("current"), dict) else None
    if node is None:
        return None

    for key in (
        "axTitle",
        "axValue",
        "axDescription",
        "axLabel",
        "axPlaceholderValue",
        "axRoleDescription",
    ):
        text = _clean_text(node.get(key))
        if text:
            return text
    return None


def _target_text_from_legacy_ax(ax: dict) -> str | None:
    for key in ("AXTitleOrValue", "AXTitle", "AXValue", "AXDescription", "AXRole"):
        text = _clean_text(ax.get(key))
        if text:
            return text
    return None


def step_text_from_event(obj: dict, ax: dict, event_type: str | None) -> tuple[str | None, str | None]:
    title = _text_from_annotation(obj, ax, "title", event_type)
    description = _text_from_annotation(obj, ax, "description", event_type)
    if title is not None:
        return title, description

    target_text = (
        _target_text_from_snapshot(ax)
        if isinstance(ax.get("current"), dict)
        else _target_text_from_legacy_ax(ax)
    )
    if target_text:
        action = "Click" if event_type == "mousedown_left" else _event_label(event_type)
        return f"{action} {target_text}", description

    return _event_label(event_type), description


def _event_label(event_type: str | None) -> str:
    labels = {
        "mousedown_left": "Click",
        "mousedown_right": "Right click",
        "mouseup_left": "Release click",
        "scroll": "Scroll",
        "keypress": "Type",
    }
    if event_type in labels:
        return labels[event_type]
    return (event_type or "Interaction").replace("_", " ").title()


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
        title, description = step_text_from_event(obj, ax, str(et) if et is not None else None)
        sections.append(
            CropSection(
                timestamp_ms=int(obj["timeUtcMs"]),
                bbox=bb,
                event_type=str(et) if et is not None else None,
                title=title,
                description=description,
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


def zoom_region_for_bbox(bbox: BBox, image_width: int, image_height: int) -> BBox | None:
    clamped = clamp_bbox_to_image(bbox, image_width, image_height)
    if clamped is None:
        return None

    target_width = max(clamped.width * 4, image_width // 3)
    target_height = max(clamped.height * 4, image_height // 3)
    target_width = min(image_width, target_width)
    target_height = min(image_height, target_height)

    center_x = clamped.x + (clamped.width / 2)
    center_y = clamped.y + (clamped.height / 2)
    left = int(round(center_x - (target_width / 2)))
    top = int(round(center_y - (target_height / 2)))
    left = max(0, min(left, image_width - target_width))
    top = max(0, min(top, image_height - target_height))

    return BBox(x=left, y=top, width=target_width, height=target_height)


def _draw_callout_marker(draw, number: int, x: int, y: int, radius: int) -> None:
    try:
        from PIL import ImageFont

        font = ImageFont.truetype("Arial Bold.ttf", max(12, radius))
    except Exception:
        font = None

    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=(20, 184, 166, 255),
        outline=(255, 255, 255, 255),
        width=max(2, radius // 5),
    )
    label = str(number)
    text_box = draw.textbbox((0, 0), label, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    draw.text(
        (x - (text_width / 2), y - (text_height / 2) - 1),
        label,
        fill=(255, 255, 255, 255),
        font=font,
    )


def annotate_frame(image_path: Path, bbox: BBox, output_path: Path, step_number: int = 1) -> None:
    try:
        from PIL import Image, ImageDraw
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

        zoom = zoom_region_for_bbox(clamped, image.width, image.height)
        if zoom is None:
            raise ValueError(
                f"bbox {bbox.model_dump()} does not overlap image {image.width}x{image.height}"
            )

        composed = image.copy()
        dim = Image.new("RGBA", image.size, (17, 24, 39, 92))
        composed.alpha_composite(dim)

        draw = ImageDraw.Draw(composed)
        context_width = max(2, min(image.width, image.height) // 270)
        draw.rounded_rectangle(
            [
                clamped.x,
                clamped.y,
                clamped.x + clamped.width,
                clamped.y + clamped.height,
            ],
            radius=max(6, min(clamped.width, clamped.height) // 8),
            outline=(239, 68, 68, 230),
            width=context_width,
        )

        crop = image.crop((zoom.x, zoom.y, zoom.x + zoom.width, zoom.y + zoom.height))
        max_zoom_width = int(image.width * 0.72)
        max_zoom_height = int(image.height * 0.68)
        zoom_scale = min(max_zoom_width / crop.width, max_zoom_height / crop.height)
        zoomed_width = int(crop.width * zoom_scale)
        zoomed_height = int(crop.height * zoom_scale)
        crop = crop.resize((zoomed_width, zoomed_height), Image.Resampling.LANCZOS)

        image_center_x = clamped.x + (clamped.width / 2)
        panel_x = int(round(image_center_x - (zoomed_width / 2)))
        panel_x = max(24, min(panel_x, image.width - zoomed_width - 24))
        panel_y = max(24, min(clamped.y - zoomed_height - 40, image.height - zoomed_height - 24))
        if panel_y < 24 or panel_y + zoomed_height > image.height - 24:
            panel_y = max(24, min(clamped.y + clamped.height + 40, image.height - zoomed_height - 24))

        shadow = Image.new("RGBA", (zoomed_width + 24, zoomed_height + 24), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle(
            [8, 8, zoomed_width + 16, zoomed_height + 16],
            radius=18,
            fill=(17, 24, 39, 70),
        )
        composed.alpha_composite(shadow, (panel_x - 12, panel_y - 12))
        composed.paste(crop, (panel_x, panel_y))

        draw = ImageDraw.Draw(composed)
        panel_radius = max(12, min(zoomed_width, zoomed_height) // 36)
        draw.rounded_rectangle(
            [panel_x, panel_y, panel_x + zoomed_width, panel_y + zoomed_height],
            radius=panel_radius,
            outline=(255, 255, 255, 255),
            width=max(3, context_width),
        )

        target_in_panel = [
            panel_x + int(round((clamped.x - zoom.x) * zoom_scale)),
            panel_y + int(round((clamped.y - zoom.y) * zoom_scale)),
            panel_x + int(round((clamped.x + clamped.width - zoom.x) * zoom_scale)),
            panel_y + int(round((clamped.y + clamped.height - zoom.y) * zoom_scale)),
        ]
        target_width = max(3, min(image.width, image.height) // 190)
        draw.rounded_rectangle(
            target_in_panel,
            radius=max(8, min(target_in_panel[2] - target_in_panel[0], target_in_panel[3] - target_in_panel[1]) // 8),
            outline=(255, 255, 255, 255),
            width=target_width + 2,
        )
        draw.rounded_rectangle(
            target_in_panel,
            radius=max(8, min(target_in_panel[2] - target_in_panel[0], target_in_panel[3] - target_in_panel[1]) // 8),
            outline=(239, 68, 68, 255),
            width=target_width,
        )

        marker_radius = max(16, min(image.width, image.height) // 48)
        marker_x = max(panel_x + marker_radius + 4, target_in_panel[0] - marker_radius)
        marker_y = max(panel_y + marker_radius + 4, target_in_panel[1] - marker_radius)
        marker_x = min(marker_x, panel_x + zoomed_width - marker_radius - 4)
        marker_y = min(marker_y, panel_y + zoomed_height - marker_radius - 4)
        _draw_callout_marker(draw, step_number, marker_x, marker_y, marker_radius)

        composed.convert("RGB").save(output_path)


def write_tutorial_pdf(
    annotated_steps: list[tuple[CropSection, Path]],
    output_pdf: Path,
    metadata: TutorialMetadata,
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
    margin = 42
    title_height = 86
    footer_height = 32
    image_max_width = page_width - (margin * 2)
    image_max_height = page_height - title_height - footer_height - (margin * 2)

    pdf = canvas.Canvas(str(output_pdf), pagesize=(page_width, page_height))
    _draw_cover_page(pdf, page_width, page_height, metadata, len(annotated_steps))

    for index, (section, image_path) in enumerate(annotated_steps, start=1):
        pdf.setFillColor(colors.HexColor("#f8fafc"))
        pdf.rect(0, 0, page_width, page_height, stroke=0, fill=1)

        image = ImageReader(str(image_path))
        image_width, image_height = image.getSize()
        scale = min(image_max_width / image_width, image_max_height / image_height)
        drawn_width = image_width * scale
        drawn_height = image_height * scale
        image_x = margin + ((image_max_width - drawn_width) / 2)
        image_y = margin + footer_height

        _draw_context_logo(pdf, margin, page_height - margin + 3)

        pdf.setFillColor(colors.HexColor("#111827"))
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(margin, page_height - margin - 27, f"Step {index}")

        pdf.setFillColor(colors.HexColor("#4b5563"))
        pdf.setFont("Helvetica-Bold", 14)
        label = section.title or _event_label(section.event_type)
        _draw_wrapped_text(pdf, label, margin + 92, page_height - margin - 27, image_max_width - 92, 16)

        if section.description:
            pdf.setFillColor(colors.HexColor("#6b7280"))
            pdf.setFont("Helvetica", 10)
            _draw_wrapped_text(
                pdf,
                section.description,
                margin + 92,
                page_height - margin - 47,
                image_max_width - 92,
                12,
                max_lines=2,
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
            margin - 6,
            f"{_event_label(section.event_type)} | {section.timestamp_ms} ms | "
            f"Target bbox: x={bbox.x}, y={bbox.y}, w={bbox.width}, h={bbox.height}",
        )
        pdf.showPage()

    pdf.save()


def _formatted_recording_date(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%B %d, %Y")


def _draw_context_logo(pdf, x: float, y: float) -> None:
    from reportlab.lib import colors

    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(x + 23, y - 8, "Context")
    pdf.setFillColor(colors.HexColor("#ef4444"))
    pdf.circle(x + 7, y - 4, 5, stroke=0, fill=1)
    pdf.setFillColor(colors.HexColor("#14b8a6"))
    pdf.circle(x + 15, y - 12, 5, stroke=0, fill=1)


def _draw_wrapped_text(
    pdf,
    text: str,
    x: float,
    y: float,
    max_width: float,
    line_height: float,
    max_lines: int = 1,
) -> None:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdf.stringWidth(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)

    for index, line in enumerate(lines[:max_lines]):
        if index == max_lines - 1 and len(lines) == max_lines and words:
            while pdf.stringWidth(line + "...") > max_width and line:
                line = line[:-1].rstrip()
            if line != text and max_lines == 1:
                line = line + "..."
        pdf.drawString(x, y - (index * line_height), line)


def _draw_cover_page(
    pdf,
    page_width: float,
    page_height: float,
    metadata: TutorialMetadata,
    step_count: int,
) -> None:
    from reportlab.lib import colors

    pdf.setFillColor(colors.HexColor("#f8fafc"))
    pdf.rect(0, 0, page_width, page_height, stroke=0, fill=1)

    margin = 64
    _draw_context_logo(pdf, margin, page_height - margin)

    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 34)
    pdf.drawString(margin, page_height - 170, "Tutorial Guide")

    pdf.setFillColor(colors.HexColor("#374151"))
    pdf.setFont("Helvetica-Bold", 20)
    _draw_wrapped_text(pdf, metadata.recording_name, margin, page_height - 210, page_width - (margin * 2), 24)

    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.setFont("Helvetica", 13)
    pdf.drawString(margin, page_height - 256, f"{step_count} steps")
    pdf.drawString(margin, page_height - 278, _formatted_recording_date(metadata.recorded_at_ms))

    pdf.setFillColor(colors.HexColor("#ef4444"))
    pdf.roundRect(margin, 88, 120, 8, 4, stroke=0, fill=1)
    pdf.setFillColor(colors.HexColor("#14b8a6"))
    pdf.roundRect(margin + 134, 88, 120, 8, 4, stroke=0, fill=1)
    pdf.showPage()


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
                annotate_frame(frame_path, section.bbox, annotated_path, index)
                annotated_steps.append((section, annotated_path))

            metadata = TutorialMetadata(
                recording_name=input_path.stem if input_path.is_file() else input_path.name,
                recorded_at_ms=base_ms,
            )
            write_tutorial_pdf(
                annotated_steps,
                output_pdf.expanduser().resolve(),
                metadata,
            )


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
