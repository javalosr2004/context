from __future__ import annotations

import hashlib
import os
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from grounding import NormalizedPoint, gui_actor_response, holo_coordinate_to_normalized, point_to_bbox
from holo_client import HoloLocalizer
from image_io import read_image
from logging_config import configure_logging, log_event


load_dotenv()

DEFAULT_INSTRUCTION = "Locate the matching UI element."
logger = configure_logging()


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
        reference_image: UploadFile | None = File(None),
        instruction: str = Form(DEFAULT_INSTRUCTION),
    ):
        request_id = str(uuid.uuid4())
        total_started = time.perf_counter()
        instruction_text = instruction or DEFAULT_INSTRUCTION
        upload_bytes = 0
        reference_upload_bytes = 0

        try:
            decode_started = time.perf_counter()
            image_bytes = await input_image.read()
            upload_bytes = len(image_bytes)
            image_sha256 = sha256_hex(image_bytes)
            image_size, screenshot_data_uri = read_image(image_bytes)
            reference_image_data_uri = None
            reference_image_sha256 = None
            if reference_image is not None:
                reference_bytes = await reference_image.read()
                reference_upload_bytes = len(reference_bytes)
                reference_image_sha256 = sha256_hex(reference_bytes)
                _, reference_image_data_uri = read_image(reference_bytes)
            decode_ms = elapsed_ms(decode_started)

            localizer_instance = app.state.localizer or HoloLocalizer()
            holo_started = time.perf_counter()
            point_1000 = localizer_instance.locate(
                screenshot_data_uri=screenshot_data_uri,
                target=instruction_text,
                reference_image_data_uri=reference_image_data_uri,
            )
            holo_ms = elapsed_ms(holo_started)

            post_started = time.perf_counter()
            point = NormalizedPoint(
                x=holo_coordinate_to_normalized(point_1000.x),
                y=holo_coordinate_to_normalized(point_1000.y),
            )
            bbox = point_to_bbox(
                point,
                width_ratio=float(os.environ.get("HOLO_BBOX_WIDTH_RATIO", "0.08")),
                height_ratio=float(os.environ.get("HOLO_BBOX_HEIGHT_RATIO", "0.06")),
            )
            response = gui_actor_response(
                point=point,
                bbox=bbox,
                image_size=image_size,
                label=instruction_text,
                confidence=point_1000.confidence,
                found=point_1000.found,
            )
            post_ms = elapsed_ms(post_started)
        except ValueError as exc:
            log_predict_error(
                request_id=request_id,
                instruction=instruction_text,
                upload_bytes=upload_bytes,
                reference_upload_bytes=reference_upload_bytes,
                status_code=400,
                error=exc,
                total_started=total_started,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValidationError as exc:
            log_predict_error(
                request_id=request_id,
                instruction=instruction_text,
                upload_bytes=upload_bytes,
                reference_upload_bytes=reference_upload_bytes,
                status_code=502,
                error=exc,
                total_started=total_started,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Holo returned invalid localization JSON: {exc}",
            ) from exc
        except Exception as exc:
            log_predict_error(
                request_id=request_id,
                instruction=instruction_text,
                upload_bytes=upload_bytes,
                reference_upload_bytes=reference_upload_bytes,
                status_code=502,
                error=exc,
                total_started=total_started,
            )
            raise HTTPException(status_code=502, detail=f"Holo localization failed: {exc}") from exc

        log_event(
            logger,
            "predict_success",
            request_id=request_id,
            status_code=200,
            model=os.environ.get("HOLO_MODEL", "holo3-35b-a3b"),
            instruction=instruction_text,
            upload_bytes=upload_bytes,
            reference_upload_bytes=reference_upload_bytes,
            has_reference_image=reference_image_data_uri is not None,
            input_image_sha256=image_sha256,
            reference_image_sha256=reference_image_sha256,
            image_size={"width": image_size.width, "height": image_size.height},
            holo_point_1000={"x": point_1000.x, "y": point_1000.y},
            holo_confidence=point_1000.confidence,
            holo_found=point_1000.found,
            normalized_point=response["point"],
            bbox=response["bbox"],
            timings_ms={
                "decode": decode_ms,
                "holo": holo_ms,
                "post": post_ms,
                "total": elapsed_ms(total_started),
            },
        )
        return response

    return app


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log_predict_error(
    *,
    request_id: str,
    instruction: str,
    upload_bytes: int,
    reference_upload_bytes: int,
    status_code: int,
    error: Exception,
    total_started: float,
) -> None:
    log_event(
        logger,
        "predict_error",
        request_id=request_id,
        status_code=status_code,
        instruction=instruction,
        upload_bytes=upload_bytes,
        reference_upload_bytes=reference_upload_bytes,
        has_reference_image=reference_upload_bytes > 0,
        error_type=type(error).__name__,
        error=str(error),
        timings_ms={"total": elapsed_ms(total_started)},
    )


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
