from __future__ import annotations

import os
from http import HTTPStatus

from flask import Flask, jsonify, request
from pydantic import ValidationError

from grounding import NormalizedPoint, gui_actor_response, holo_coordinate_to_normalized, point_to_bbox
from holo_client import HoloLocalizer
from image_io import read_image


DEFAULT_INSTRUCTION = "Locate the matching UI element."


def create_app(localizer: HoloLocalizer | None = None) -> Flask:
    app = Flask(__name__)
    app.config["HOLO_LOCALIZER"] = localizer

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "model": os.environ.get("HOLO_MODEL", "holo3-35b-a3b"),
                "provider": "hcompany",
            }
        )

    @app.post("/predict")
    def predict():
        upload = request.files.get("input_image")
        if upload is None:
            return error_response("Missing multipart file field: input_image", HTTPStatus.BAD_REQUEST)

        instruction = request.form.get("instruction") or DEFAULT_INSTRUCTION
        try:
            image_size, screenshot_data_uri = read_image(upload.read())
            localizer_instance = app.config["HOLO_LOCALIZER"] or HoloLocalizer()
            point_1000 = localizer_instance.locate(
                screenshot_data_uri=screenshot_data_uri,
                target=instruction,
            )
            point = NormalizedPoint(
                x=holo_coordinate_to_normalized(point_1000.x),
                y=holo_coordinate_to_normalized(point_1000.y),
            )
            bbox = point_to_bbox(
                point,
                width_ratio=float(os.environ.get("HOLO_BBOX_WIDTH_RATIO", "0.08")),
                height_ratio=float(os.environ.get("HOLO_BBOX_HEIGHT_RATIO", "0.06")),
            )
        except ValueError as exc:
            return error_response(str(exc), HTTPStatus.BAD_REQUEST)
        except ValidationError as exc:
            return error_response(f"Holo returned invalid localization JSON: {exc}", HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            return error_response(f"Holo localization failed: {exc}", HTTPStatus.BAD_GATEWAY)

        return jsonify(
            gui_actor_response(
                point=point,
                bbox=bbox,
                image_size=image_size,
                label=instruction,
            )
        )

    return app


def error_response(message: str, status: HTTPStatus):
    return jsonify({"error": message}), int(status)


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
