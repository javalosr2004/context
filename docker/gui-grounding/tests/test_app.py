import io

from PIL import Image

from app import create_app
from holo_client import VisualLocalizerOutput


class FakeLocalizer:
    def locate(self, *, screenshot_data_uri: str, target: str) -> VisualLocalizerOutput:
        assert screenshot_data_uri.startswith("data:image/png;base64,")
        assert target == "Submit button"
        return VisualLocalizerOutput(x=250, y=750)


def png_bytes() -> bytes:
    image = Image.new("RGB", (200, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_predict_returns_context_app_schema():
    client = create_app(FakeLocalizer()).test_client()

    response = client.post(
        "/predict",
        data={
            "input_image": (io.BytesIO(png_bytes()), "screen.png"),
            "instruction": "Submit button",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["point"] == {"x": 0.25, "y": 0.75}
    assert body["point_pixel"] == {"x": 50.0, "y": 75.0}
    assert body["bbox_source"] == "holo3_point_box"
    assert body["image_size"] == {"width": 200, "height": 100}
    assert body["num_detections"] == 1


def test_predict_requires_input_image():
    client = create_app(FakeLocalizer()).test_client()

    response = client.post("/predict", data={}, content_type="multipart/form-data")

    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing multipart file field: input_image"
