"""One-shot: download OmniParser v2 weights from HuggingFace.

Pulls:
    icon_detect/model.pt
    icon_caption_florence/ (full Florence-2 model dir)

Skips files that already exist.
"""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

REPO_ID = "microsoft/OmniParser-v2.0"
HERE = Path(__file__).parent.resolve()
WEIGHTS_DIR = HERE / "weights"


def download_yolo() -> None:
    target_dir = WEIGHTS_DIR / "icon_detect"
    target_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("model.pt", "model.yaml", "train_args.yaml"):
        try:
            hf_hub_download(
                repo_id=REPO_ID,
                filename=f"icon_detect/{fname}",
                local_dir=str(WEIGHTS_DIR),
            )
        except Exception as e:  # noqa: BLE001
            # Only model.pt is strictly required.
            if fname == "model.pt":
                raise
            print(f"skip optional {fname}: {e}")
    print(f"yolo weights ready at {target_dir}")


def download_caption_model() -> None:
    target_dir = WEIGHTS_DIR / "icon_caption_florence"
    target_dir.mkdir(parents=True, exist_ok=True)
    # The Florence-2 caption model lives under icon_caption/ in the HF repo;
    # we mirror it locally as icon_caption_florence/ to match parser.py.
    snapshot_download(
        repo_id=REPO_ID,
        allow_patterns=["icon_caption/*"],
        local_dir=str(WEIGHTS_DIR),
    )
    src = WEIGHTS_DIR / "icon_caption"
    if src.is_dir() and not any(target_dir.iterdir()):
        for child in src.iterdir():
            child.rename(target_dir / child.name)
        src.rmdir()
    print(f"caption weights ready at {target_dir}")


def main() -> None:
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    download_yolo()
    download_caption_model()


if __name__ == "__main__":
    main()
