import io
import json
import logging

from PIL import Image
from fastapi.testclient import TestClient

from app import create_app
from holo_client import VisualLocalizerOutput
from logging_config import LOGGER_NAME


class FakeLocalizer:
    def __init__(self) -> None:
        self.reference_image_data_uri = None

    def locate(
        self,
        *,
        screenshot_data_uri: str,
        target: str,
        reference_image_data_uri: str | None = None,
    ) -> VisualLocalizerOutput:
        assert screenshot_data_uri.startswith("data:image/png;base64,")
        assert target == "Submit button"
        self.reference_image_data_uri = reference_image_data_uri
        return VisualLocalizerOutput(x=250, y=750)


class FailingLocalizer:
    def locate(
        self,
        *,
        screenshot_data_uri: str,
        target: str,
        reference_image_data_uri: str | None = None,
    ) -> VisualLocalizerOutput:
        raise RuntimeError("provider unavailable")


def png_bytes() -> bytes:
    image = Image.new("RGB", (200, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_predict_returns_context_app_schema():
    client = TestClient(create_app(FakeLocalizer()))

    response = client.post(
        "/predict",
        files={"input_image": ("screen.png", png_bytes(), "image/png")},
        data={"instruction": "Submit button"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["point"] == {"x": 0.25, "y": 0.75}
    assert body["point_pixel"] == {"x": 50.0, "y": 75.0}
    assert body["bbox_source"] == "holo3_point_box"
    assert body["image_size"] == {"width": 200, "height": 100}
    assert body["num_detections"] == 1


def test_predict_accepts_reference_image():
    localizer = FakeLocalizer()
    client = TestClient(create_app(localizer))

    response = client.post(
        "/predict",
        files={
            "input_image": ("screen.png", png_bytes(), "image/png"),
            "reference_image": ("reference.png", png_bytes(), "image/png"),
        },
        data={"instruction": "Submit button"},
    )

    assert response.status_code == 200
    assert localizer.reference_image_data_uri is not None
    assert localizer.reference_image_data_uri.startswith("data:image/png;base64,")


def test_predict_logs_success_without_image_payload(caplog):
    client = TestClient(create_app(FakeLocalizer()))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.post(
            "/predict",
            files={"input_image": ("screen.png", png_bytes(), "image/png")},
            data={"instruction": "Submit button"},
        )

    assert response.status_code == 200
    records = [json.loads(record.message) for record in caplog.records]
    event = next(record for record in records if record["event"] == "predict_success")
    assert event["status_code"] == 200
    assert event["instruction"] == "Submit button"
    assert event["has_reference_image"] is False
    assert event["image_size"] == {"width": 200, "height": 100}
    assert event["holo_point_1000"] == {"x": 250, "y": 750}
    assert event["normalized_point"] == {"x": 0.25, "y": 0.75}
    assert "total" in event["timings_ms"]
    assert "screenshot_data_uri" not in event
    assert "reference_image_data_uri" not in event


def test_predict_logs_errors(caplog):
    client = TestClient(create_app(FailingLocalizer()))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.post(
            "/predict",
            files={"input_image": ("screen.png", png_bytes(), "image/png")},
            data={"instruction": "Submit button"},
        )

    assert response.status_code == 502
    records = [json.loads(record.message) for record in caplog.records]
    event = next(record for record in records if record["event"] == "predict_error")
    assert event["status_code"] == 502
    assert event["error_type"] == "RuntimeError"
    assert event["error"] == "provider unavailable"
    assert "total" in event["timings_ms"]


def test_predict_requires_input_image():
    client = TestClient(create_app(FakeLocalizer()))

    response = client.post("/predict", data={})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "input_image"]
