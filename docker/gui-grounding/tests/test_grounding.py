import pytest

from grounding import (
    ImageSize,
    NormalizedPoint,
    bbox_center,
    bbox_to_rect,
    gui_actor_response,
    holo_bbox_to_normalized_bbox,
    holo_coordinate_to_normalized,
    point_to_bbox,
)


def test_holo_coordinate_to_normalized_clamps_to_unit_interval():
    assert holo_coordinate_to_normalized(-1) == 0.0
    assert holo_coordinate_to_normalized(500) == 0.5
    assert holo_coordinate_to_normalized(1001) == 1.0


def test_holo_bbox_to_normalized_bbox_validates_and_scales_edges():
    bbox = holo_bbox_to_normalized_bbox(x1=100, y1=200, x2=500, y2=700)

    assert bbox.x1 == 0.1
    assert bbox.y1 == 0.2
    assert bbox.x2 == 0.5
    assert bbox.y2 == 0.7


def test_holo_bbox_to_normalized_bbox_rejects_empty_boxes():
    with pytest.raises(ValueError, match="x2 must be greater than x1"):
        holo_bbox_to_normalized_bbox(x1=500, y1=200, x2=500, y2=700)


def test_bbox_center_returns_midpoint():
    bbox = holo_bbox_to_normalized_bbox(x1=100, y1=200, x2=500, y2=700)
    center = bbox_center(bbox)

    assert center.x == pytest.approx(0.3)
    assert center.y == pytest.approx(0.45)


def test_bbox_to_rect_converts_edges_to_xywh():
    rect = bbox_to_rect(holo_bbox_to_normalized_bbox(x1=100, y1=200, x2=500, y2=700))

    assert rect.x == 0.1
    assert rect.y == 0.2
    assert rect.width == 0.4
    assert rect.height == pytest.approx(0.5)


def test_point_to_bbox_centers_box_around_point():
    bbox = point_to_bbox(
        NormalizedPoint(x=0.5, y=0.5),
        width_ratio=0.2,
        height_ratio=0.1,
    )

    assert bbox.x1 == 0.4
    assert bbox.y1 == 0.45
    assert bbox.x2 == 0.6
    assert bbox.y2 == 0.55


def test_point_to_bbox_clamps_edges():
    bbox = point_to_bbox(
        NormalizedPoint(x=0.02, y=0.98),
        width_ratio=0.2,
        height_ratio=0.2,
    )

    assert bbox.x1 == 0.0
    assert bbox.y1 == 0.88
    assert bbox.x2 == pytest.approx(0.12)
    assert bbox.y2 == 1.0


def test_gui_actor_response_matches_frontend_schema():
    response = gui_actor_response(
        point=NormalizedPoint(x=0.5, y=0.25),
        bbox=point_to_bbox(
            NormalizedPoint(x=0.5, y=0.25),
            width_ratio=0.2,
            height_ratio=0.1,
        ),
        image_size=ImageSize(width=1000, height=800),
        label="target button",
    )

    assert response["point"] == {"x": 0.5, "y": 0.25}
    assert response["point_pixel"] == {"x": 500.0, "y": 200.0}
    assert response["bbox_xywh"] == {
        "x": 0.4,
        "y": 0.2,
        "width": pytest.approx(0.2),
        "height": pytest.approx(0.1),
    }
    assert response["bbox_pixel"]["x1"] == pytest.approx(400.0)
    assert response["bbox_pixel"]["y1"] == pytest.approx(160.0)
    assert response["bbox_pixel"]["x2"] == pytest.approx(600.0)
    assert response["bbox_pixel"]["y2"] == pytest.approx(240.0)
    assert response["bbox_xywh_pixel"] == {
        "x": 400.0,
        "y": 160.0,
        "width": pytest.approx(200.0),
        "height": pytest.approx(80.0),
    }
    assert response["bbox_source"] == "holo3_bbox"
    assert response["image_size"] == {"width": 1000, "height": 800}
    assert response["num_detections"] == 1
