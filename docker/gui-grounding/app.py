from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from grounding import NormalizedPoint, gui_actor_response, holo_coordinate_to_normalized, point_to_bbox
from holo_client import HoloLocalizer
from image_io import read_image


load_dotenv()

DEFAULT_INSTRUCTION = "Locate the matching UI element."


def create_app(localizer: HoloLocalizer | None = None) -> FastAPI:
    app = FastAPI(title="Holo GUI Grounding")
    app.state.localizer = localizer

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model": os.environ.get("HOLO_MODEL", "holo3-35b-a3b"),
            "provider": "hcompany",
        }

    @app.post("/predict")
    async def predict(
        input_image: UploadFile = File(...),
        instruction: str = Form(DEFAULT_INSTRUCTION),
    ):
        try:
            image_size, screenshot_data_uri = read_image(await input_image.read())
            localizer_instance = app.state.localizer or HoloLocalizer()
            point_1000 = localizer_instance.locate(
                screenshot_data_uri=screenshot_data_uri,
                target=instruction or DEFAULT_INSTRUCTION,
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
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Holo returned invalid localization JSON: {exc}",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Holo localization failed: {exc}") from exc

        return gui_actor_response(
            point=point,
            bbox=bbox,
            image_size=image_size,
            label=instruction or DEFAULT_INSTRUCTION,
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
