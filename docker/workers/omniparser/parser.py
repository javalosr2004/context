"""Parse a screenshot with OmniParser v2.

Usage:
    python parser.py <image> [-o OUTPUT_DIR] [--box-threshold 0.05]

Writes two files to the output directory:
    <stem>_annotated.png  -- input image with boxes + numeric labels
    <stem>_parsed.json    -- list of parsed elements (text + icon captions)

Expects ``OmniParser/`` and ``weights/`` to live next to this script.
Run ``setup_weights.py`` once to populate them.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import types
from pathlib import Path

# Let unsupported MPS ops fall back to CPU instead of crashing. Must be set
# before torch picks up the env var.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import torch  # noqa: E402
from PIL import Image  # noqa: E402

_HERE = Path(__file__).parent.resolve()
_OMNIPARSER_DIR = _HERE / "OmniParser"
if not _OMNIPARSER_DIR.is_dir():
    raise SystemExit(
        f"OmniParser repo not found at {_OMNIPARSER_DIR}. "
        "Run `python setup_weights.py` first."
    )
sys.path.insert(0, str(_OMNIPARSER_DIR))

# OmniParser's util/utils.py imports paddleocr at module-import time but we
# don't use it (easyocr path only). Stub it out to avoid the heavy dep.
if "paddleocr" not in sys.modules:
    _paddle_stub = types.ModuleType("paddleocr")

    class _PaddleOCRStub:  # pragma: no cover - never instantiated on our path
        def __init__(self, *args, **kwargs):
            pass

    _paddle_stub.PaddleOCR = _PaddleOCRStub
    sys.modules["paddleocr"] = _paddle_stub

from util.utils import (  # noqa: E402
    check_ocr_box,
    get_caption_model_processor,
    get_som_labeled_img,
    get_yolo_model,
)

WEIGHTS_DIR = _HERE / "weights"
YOLO_WEIGHTS = WEIGHTS_DIR / "icon_detect" / "model.pt"
CAPTION_WEIGHTS_DIR = WEIGHTS_DIR / "icon_caption_florence"


def pick_device(override: str | None = None) -> str:
    """Choose the best available torch device (mps > cuda > cpu)."""
    if override:
        return override
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_caption_mps() -> dict:
    """Load Florence-2 on Apple MPS in fp32.

    OmniParser's stock loader uses fp16 for any non-CPU device, but:
      - MPS fp16 coverage is spotty for some Florence-2 ops.
      - Downstream, ``get_parsed_content_icon`` only casts inputs to fp16 on
        CUDA; on MPS it leaves them fp32, which then mismatches an fp16 model.
    Loading fp32 on MPS sidesteps both.
    """
    from transformers import AutoModelForCausalLM, AutoProcessor

    processor = AutoProcessor.from_pretrained(
        "microsoft/Florence-2-base", trust_remote_code=True
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(CAPTION_WEIGHTS_DIR),
        torch_dtype=torch.float32,
        trust_remote_code=True,
    ).to("mps")
    return {"model": model, "processor": processor}


def load_models(device: str) -> tuple[object, dict]:
    if not YOLO_WEIGHTS.is_file():
        raise SystemExit(f"missing YOLO weights at {YOLO_WEIGHTS}")
    if not CAPTION_WEIGHTS_DIR.is_dir():
        raise SystemExit(f"missing caption weights at {CAPTION_WEIGHTS_DIR}")

    yolo = get_yolo_model(model_path=str(YOLO_WEIGHTS))
    if device == "mps":
        caption = _load_caption_mps()
    else:
        caption = get_caption_model_processor(
            model_name="florence2",
            model_name_or_path=str(CAPTION_WEIGHTS_DIR),
            device=device,
        )
    return yolo, caption


def parse_image(
    image_path: Path,
    output_dir: Path,
    yolo_model,
    caption_model_processor,
    box_threshold: float,
) -> tuple[Path, Path]:
    image = Image.open(image_path)
    box_overlay_ratio = max(image.size) / 3200
    draw_bbox_config = {
        "text_scale": 0.8 * box_overlay_ratio,
        "text_thickness": max(int(2 * box_overlay_ratio), 1),
        "text_padding": max(int(3 * box_overlay_ratio), 1),
        "thickness": max(int(3 * box_overlay_ratio), 1),
    }

    (text, ocr_bbox), _ = check_ocr_box(
        str(image_path),
        display_img=False,
        output_bb_format="xyxy",
        goal_filtering=None,
        easyocr_args={"paragraph": False, "text_threshold": 0.9},
        use_paddleocr=False,
    )

    labeled_img_b64, _label_coords, parsed_content = get_som_labeled_img(
        str(image_path),
        yolo_model,
        BOX_TRESHOLD=box_threshold,
        output_coord_in_ratio=False,
        ocr_bbox=ocr_bbox,
        draw_bbox_config=draw_bbox_config,
        caption_model_processor=caption_model_processor,
        ocr_text=text,
        use_local_semantics=True,
        iou_threshold=0.7,
        imgsz=640,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    annotated_path = output_dir / f"{stem}_annotated.png"
    annotated_path.write_bytes(base64.b64decode(labeled_img_b64))

    json_path = output_dir / f"{stem}_parsed.json"
    json_path.write_text(json.dumps(parsed_content, indent=2))

    return annotated_path, json_path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse a screenshot with OmniParser v2."
    )
    ap.add_argument("image", type=Path, help="input image path")
    ap.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="directory for annotated image + parsed JSON",
    )
    ap.add_argument(
        "--box-threshold",
        type=float,
        default=0.05,
        help="YOLO confidence threshold for icon detection",
    )
    ap.add_argument(
        "--device",
        choices=("mps", "cuda", "cpu"),
        default=None,
        help="override torch device (defaults to mps on Apple Silicon)",
    )
    args = ap.parse_args()

    image_path = args.image.expanduser().resolve()
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")

    output_dir = args.output_dir.expanduser().resolve()

    device = pick_device(args.device)
    print(f"device: {device}")
    yolo, caption = load_models(device)
    annotated_path, json_path = parse_image(
        image_path, output_dir, yolo, caption, args.box_threshold
    )
    print(f"wrote {annotated_path}")
    print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
