from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageSize:
    width: int
    height: int


@dataclass(frozen=True)
class NormalizedPoint:
    x: float
    y: float


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def holo_coordinate_to_normalized(value: int) -> float:
    return clamp(value / 1000.0, 0.0, 1.0)


def holo_bbox_to_normalized_bbox(
    *,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> BoundingBox:
    bbox = BoundingBox(
        x1=holo_coordinate_to_normalized(x1),
        y1=holo_coordinate_to_normalized(y1),
        x2=holo_coordinate_to_normalized(x2),
        y2=holo_coordinate_to_normalized(y2),
    )
    if bbox.x2 <= bbox.x1:
        raise ValueError("Bounding box x2 must be greater than x1.")
    if bbox.y2 <= bbox.y1:
        raise ValueError("Bounding box y2 must be greater than y1.")
    return bbox


def bbox_center(bbox: BoundingBox) -> NormalizedPoint:
    return NormalizedPoint(
        x=(bbox.x1 + bbox.x2) / 2.0,
        y=(bbox.y1 + bbox.y2) / 2.0,
    )


def bbox_to_rect(bbox: BoundingBox) -> Rect:
    return Rect(
        x=bbox.x1,
        y=bbox.y1,
        width=bbox.x2 - bbox.x1,
        height=bbox.y2 - bbox.y1,
    )


def point_to_bbox(
    point: NormalizedPoint,
    *,
    width_ratio: float,
    height_ratio: float,
) -> BoundingBox:
    if width_ratio <= 0 or height_ratio <= 0:
        raise ValueError("Bounding box ratios must be positive.")
    if width_ratio > 1 or height_ratio > 1:
        raise ValueError("Bounding box ratios must be <= 1.")

    half_width = width_ratio / 2.0
    half_height = height_ratio / 2.0
    x1 = clamp(point.x - half_width, 0.0, 1.0)
    y1 = clamp(point.y - half_height, 0.0, 1.0)
    x2 = clamp(point.x + half_width, 0.0, 1.0)
    y2 = clamp(point.y + half_height, 0.0, 1.0)

    if x2 <= x1:
        x2 = min(1.0, x1 + width_ratio)
        x1 = max(0.0, x2 - width_ratio)
    if y2 <= y1:
        y2 = min(1.0, y1 + height_ratio)
        y1 = max(0.0, y2 - height_ratio)

    return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)


def pixel_bbox(bbox: BoundingBox, image_size: ImageSize) -> BoundingBox:
    return BoundingBox(
        x1=bbox.x1 * image_size.width,
        y1=bbox.y1 * image_size.height,
        x2=bbox.x2 * image_size.width,
        y2=bbox.y2 * image_size.height,
    )


def pixel_rect(rect: Rect, image_size: ImageSize) -> Rect:
    return Rect(
        x=rect.x * image_size.width,
        y=rect.y * image_size.height,
        width=rect.width * image_size.width,
        height=rect.height * image_size.height,
    )


def gui_actor_response(
    *,
    point: NormalizedPoint,
    bbox: BoundingBox,
    image_size: ImageSize,
    label: str | None,
    bbox_source: str = "holo3_bbox",
) -> dict:
    bbox_px = pixel_bbox(bbox, image_size)
    rect = bbox_to_rect(bbox)
    rect_px = pixel_rect(rect, image_size)
    return {
        "point": {"x": point.x, "y": point.y},
        "point_pixel": {
            "x": point.x * image_size.width,
            "y": point.y * image_size.height,
        },
        "bbox": {
            "x1": bbox.x1,
            "y1": bbox.y1,
            "x2": bbox.x2,
            "y2": bbox.y2,
        },
        "bbox_xywh": {
            "x": rect.x,
            "y": rect.y,
            "width": rect.width,
            "height": rect.height,
        },
        "bbox_pixel": {
            "x1": bbox_px.x1,
            "y1": bbox_px.y1,
            "x2": bbox_px.x2,
            "y2": bbox_px.y2,
        },
        "bbox_xywh_pixel": {
            "x": rect_px.x,
            "y": rect_px.y,
            "width": rect_px.width,
            "height": rect_px.height,
        },
        "bbox_score": None,
        "bbox_label": label,
        "bbox_source": bbox_source,
        "image_size": {"width": image_size.width, "height": image_size.height},
        "num_detections": 1,
    }
