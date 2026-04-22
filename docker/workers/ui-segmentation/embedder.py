"""Dense patch-token embedders.

The ``Embedder`` interface returns an L2-normalized feature map of shape
``[C, H, W]`` so the downstream localization code can stay model-agnostic.

Default implementation is DINOv2 (ViT-S/14) loaded via ``torch.hub``. Its
self-supervised patch tokens give spatially coherent features that localize
UI elements well without any text-grounding bias.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import torch
import torch.nn.functional as F
import torchvision.transforms as T
from PIL import Image

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def pick_device(override: str | None = None) -> str:
    """Choose the best available torch device (cuda > mps > cpu)."""
    if override:
        return override
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Embedder(Protocol):
    patch: int

    def embed(self, img: Image.Image) -> torch.Tensor:
        """Return an L2-normalized ``[C, H, W]`` feature map."""
        ...


class DinoV2Embedder:
    """DINOv2 patch-token feature extractor.

    ``forward_features`` returns a dict whose ``x_norm_patchtokens`` entry is
    already layer-normalized by the model; we additionally L2-normalize along
    the channel dimension so dot products are literal cosine similarities.
    """

    patch: int = 14

    def __init__(
        self,
        model_name: str = "dinov2_vits14",
        device: str | None = None,
    ) -> None:
        self.device = pick_device(device)
        # torch.hub caches to ~/.cache/torch/hub after first run.
        self.model = torch.hub.load("facebookresearch/dinov2", model_name)
        self.model.eval().to(self.device)
        self.transform = T.Compose(
            [
                T.ToTensor(),
                T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )

    def _pad_to_patch(self, img: Image.Image) -> Image.Image:
        """Right/bottom-pad by edge-replication so dims are multiples of ``patch``.

        Padding (not resizing) preserves the query's pixel-to-patch ratio, which
        is what lets the feature grid stay interpretable as pixel coordinates.
        Replicate (vs. solid black) avoids injecting a hard artificial edge into
        the last patch row/column, which would otherwise dominate the feature
        of any partial patch — a big deal for small queries where that partial
        patch is a large fraction of the whole feature map.
        """
        w, h = img.size
        nw = max(self.patch, ((w + self.patch - 1) // self.patch) * self.patch)
        nh = max(self.patch, ((h + self.patch - 1) // self.patch) * self.patch)
        if (nw, nh) == (w, h):
            return img
        arr = np.asarray(img)
        pad_h = nh - h
        pad_w = nw - w
        arr = np.pad(arr, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
        return Image.fromarray(arr)

    @torch.no_grad()
    def embed(self, img: Image.Image) -> torch.Tensor:
        img = img.convert("RGB")
        img = self._pad_to_patch(img)
        w, h = img.size
        x = self.transform(img).unsqueeze(0).to(self.device)
        out = self.model.forward_features(x)
        tokens = out["x_norm_patchtokens"]  # [1, N, C]
        gh, gw = h // self.patch, w // self.patch
        feats = tokens.reshape(1, gh, gw, -1).permute(0, 3, 1, 2).contiguous()
        feats = F.normalize(feats, dim=1)
        return feats.squeeze(0)  # [C, gh, gw]
