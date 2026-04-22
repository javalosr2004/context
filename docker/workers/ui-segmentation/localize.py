"""Feature-map localization of a sub-image within a target image.

Pipeline (per scale):
    1. Encode query and target once with a dense patch-token backbone (DINOv2).
    2. Compute a cosine similarity map two ways and sum them:
         - mean-pooled query vector vs. target feature map
         - 2D normalized cross-correlation of the full query feature map
    3. Bilinearly upsample the similarity map to target pixel resolution.

Across scales we keep the elementwise max, giving a scale-robust heatmap. Top-K
peaks are extracted with a simple greedy NMS using the query's pixel size as
the suppression window.

Usage:
    python localize.py <query> <target> [-o OUTPUT_DIR] [--top-k 5]
                       [--scales 0.85 1.0 1.15] [--no-display]

Writes to ``OUTPUT_DIR``:
    heatmap.jpeg   -- target image with heatmap overlay + top-K bboxes
    matches.json   -- list of {x, y, w, h, score, rank}
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Must be set before torch picks up the env var.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from PIL import Image  # noqa: E402

from embedder import DinoV2Embedder, Embedder  # noqa: E402


def _cosine_mean_map(q_map: torch.Tensor, t_map: torch.Tensor) -> torch.Tensor:
    """Cosine similarity between the mean-pooled query vector and each target cell."""
    q_vec = q_map.mean(dim=(1, 2))
    q_vec = q_vec / (q_vec.norm() + 1e-8)
    return torch.einsum("c,chw->hw", q_vec, t_map)


def _ncc_map(q_map: torch.Tensor, t_map: torch.Tensor) -> torch.Tensor:
    """Patch-wise mean cosine via 2D cross-correlation.

    Both feature maps are already unit-normalized along C, so ``conv2d`` sums
    per-cell cosines; dividing by the query cell count yields a mean cosine in
    ``[-1, 1]``. ``padding='same'`` keeps the output aligned with ``t_map``.
    """
    C, Hq, Wq = q_map.shape
    _, H, W = t_map.shape
    if Hq > H or Wq > W:
        return torch.zeros(H, W, device=t_map.device, dtype=t_map.dtype)
    t = t_map.unsqueeze(0)
    q = q_map.unsqueeze(0)
    out = F.conv2d(t, q, padding="same") / (Hq * Wq)
    return out.squeeze(0).squeeze(0)


def _query_upscale(query: Image.Image, patch: int, min_patches: int) -> float:
    """Factor that brings the query's short side up to ``min_patches`` patches.

    DINOv2 has a 14-px stride. A 24-px-tall query yields only ~2 patch rows —
    too few for mean-pooled cosine or a 2×N NCC kernel to be discriminative.
    Upscaling the query alone grows its feature map without paying the O(N²)
    attention cost on the much larger target.
    """
    if min_patches <= 0:
        return 1.0
    qw, qh = query.size
    short = min(qw, qh)
    if short <= 0:
        return 1.0
    return max(1.0, (min_patches * patch) / float(short))


def _target_upscale(
    target: Image.Image,
    patch: int,
    desired: float,
    max_tokens: int,
) -> float:
    """Cap the target upscale so total patch tokens stay under ``max_tokens``.

    Matching query and target pixel-per-patch ratio is ideal, but target-side
    self-attention is O(N²) in patch count, so we cap the target factor by a
    token budget. The resulting scale mismatch is partly absorbed by the
    multi-scale search in ``--scales``.
    """
    if desired <= 1.0 or max_tokens <= 0:
        return max(1.0, desired)
    tw, th = target.size
    base_tokens = (tw / patch) * (th / patch)
    if base_tokens <= 0:
        return 1.0
    max_factor = (max_tokens / base_tokens) ** 0.5
    return max(1.0, min(desired, max_factor))


def _similarity_heatmap(
    embedder: Embedder,
    query: Image.Image,
    target: Image.Image,
    scales: list[float],
    use_ncc: bool,
    min_query_patches: int,
    max_target_tokens: int,
) -> np.ndarray:
    """Multi-scale similarity heatmap at the original target's pixel resolution."""
    target_w, target_h = target.size

    q_up = _query_upscale(query, embedder.patch, min_query_patches)
    if q_up > 1.0:
        qw, qh = query.size
        query = query.resize(
            (max(1, int(round(qw * q_up))), max(1, int(round(qh * q_up)))),
            Image.BICUBIC,
        )
    q_map = embedder.embed(query)

    t_up = _target_upscale(target, embedder.patch, q_up, max_target_tokens)
    print(
        f"upscale: query={q_up:.2f}  target={t_up:.2f}  "
        f"(query {query.size[0]}x{query.size[1]}, "
        f"target base {target_w}x{target_h})"
    )

    best: torch.Tensor | None = None
    for scale in scales:
        eff = scale * t_up
        sw = max(embedder.patch, int(round(target_w * eff)))
        sh = max(embedder.patch, int(round(target_h * eff)))
        t_scaled = target.resize((sw, sh), Image.BICUBIC)
        t_map = embedder.embed(t_scaled)

        sim = _cosine_mean_map(q_map, t_map)
        if use_ncc:
            sim = 0.5 * (sim + _ncc_map(q_map, t_map))

        sim_up = F.interpolate(
            sim[None, None],
            size=(target_h, target_w),
            mode="bilinear",
            align_corners=False,
        )[0, 0]
        best = sim_up if best is None else torch.maximum(best, sim_up)

    assert best is not None
    return best.detach().float().cpu().numpy()


def _top_k_peaks(
    heatmap: np.ndarray,
    query_size: tuple[int, int],
    k: int,
    min_score: float,
) -> list[dict]:
    """Greedy NMS: take argmax, zero a query-sized neighborhood, repeat."""
    qw, qh = query_size
    H, W = heatmap.shape
    scratch = heatmap.copy()
    peaks: list[dict] = []
    for rank in range(k):
        flat = int(np.argmax(scratch))
        y, x = divmod(flat, W)
        score = float(scratch[y, x])
        if score < min_score or not np.isfinite(score):
            break
        x0 = int(np.clip(x - qw // 2, 0, max(0, W - qw)))
        y0 = int(np.clip(y - qh // 2, 0, max(0, H - qh)))
        peaks.append(
            {
                "rank": rank + 1,
                "x": x0,
                "y": y0,
                "w": int(qw),
                "h": int(qh),
                "score": score,
            }
        )
        zy0 = max(0, y - qh // 2)
        zy1 = min(H, y + qh // 2)
        zx0 = max(0, x - qw // 2)
        zx1 = min(W, x + qw // 2)
        scratch[zy0:zy1, zx0:zx1] = -np.inf
    return peaks


def localize(
    query_path: Path,
    target_path: Path,
    embedder: Embedder,
    scales: list[float],
    top_k: int,
    min_score: float,
    use_ncc: bool,
    min_query_patches: int,
    max_target_tokens: int,
) -> tuple[np.ndarray, list[dict], Image.Image]:
    query = Image.open(query_path).convert("RGB")
    target = Image.open(target_path).convert("RGB")
    heatmap = _similarity_heatmap(
        embedder,
        query,
        target,
        scales,
        use_ncc,
        min_query_patches,
        max_target_tokens,
    )
    boxes = _top_k_peaks(heatmap, query.size, top_k, min_score)
    return heatmap, boxes, target


def render(
    target: Image.Image,
    heatmap: np.ndarray,
    boxes: list[dict],
    out_path: Path,
    display: bool,
) -> None:
    """Draw target + heatmap overlay + top-K bboxes, save JPEG, optionally show."""
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.imshow(target)
    # Normalize heatmap to [0, 1] for consistent alpha blending.
    lo, hi = float(heatmap.min()), float(heatmap.max())
    norm = (heatmap - lo) / (hi - lo + 1e-8)
    ax.imshow(
        norm,
        cmap="jet",
        alpha=0.45,
        extent=(0, target.width, target.height, 0),
    )
    for box in boxes:
        rect = mpatches.Rectangle(
            (box["x"], box["y"]),
            box["w"],
            box["h"],
            linewidth=2,
            edgecolor="lime",
            facecolor="none",
        )
        ax.add_patch(rect)
        ax.text(
            box["x"],
            max(0, box["y"] - 6),
            f"#{box['rank']} {box['score']:.3f}",
            color="white",
            fontsize=10,
            bbox=dict(facecolor="black", alpha=0.6, pad=2, edgecolor="none"),
        )
    ax.set_axis_off()
    ax.set_title(f"top-{len(boxes)} matches")
    fig.tight_layout()
    fig.savefig(out_path, format="jpeg", dpi=150, bbox_inches="tight")
    if display:
        plt.show()
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Localize a sub-image within a target image via DINOv2 features."
    )
    ap.add_argument("query", type=Path, help="path to the sub-image (query) to find")
    ap.add_argument("target", type=Path, help="path to the target image to search in")
    ap.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="directory for heatmap.jpeg + matches.json",
    )
    ap.add_argument("--top-k", type=int, default=5, help="number of peaks to report")
    ap.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="drop peaks with heatmap score below this threshold",
    )
    ap.add_argument(
        "--scales",
        type=float,
        nargs="+",
        default=[1.0],
        help="target scale factors for multi-scale search (e.g. 0.85 1.0 1.15)",
    )
    ap.add_argument(
        "--no-ncc",
        action="store_true",
        help="disable 2D cross-correlation refinement (mean-pooled cosine only)",
    )
    ap.add_argument(
        "--min-query-patches",
        type=int,
        default=6,
        help=(
            "upscale query so its short side has at least this many patches; "
            "crucial for thin queries where DINOv2's 14-px stride leaves only "
            "1-2 patch rows"
        ),
    )
    ap.add_argument(
        "--max-target-tokens",
        type=int,
        default=20000,
        help=(
            "token budget for target patch map (attention is O(N^2)). Target "
            "is upscaled toward the query factor but capped so total patches "
            "stay under this; 20k ~= 5GB of attention on MPS"
        ),
    )
    ap.add_argument(
        "--backbone",
        default="dinov2_vits14",
        help="torch.hub DINOv2 model name (vits14 | vitb14 | vitl14 | vitg14)",
    )
    ap.add_argument(
        "--device",
        choices=("cuda", "mps", "cpu"),
        default=None,
        help="override torch device",
    )
    ap.add_argument(
        "--no-display",
        action="store_true",
        help="skip matplotlib window (still writes heatmap.jpeg)",
    )
    args = ap.parse_args()

    query_path = args.query.expanduser().resolve()
    target_path = args.target.expanduser().resolve()
    if not query_path.is_file():
        raise SystemExit(f"query not found: {query_path}")
    if not target_path.is_file():
        raise SystemExit(f"target not found: {target_path}")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    embedder = DinoV2Embedder(model_name=args.backbone, device=args.device)
    print(f"backbone: {args.backbone}  device: {embedder.device}")

    heatmap, boxes, target = localize(
        query_path=query_path,
        target_path=target_path,
        embedder=embedder,
        scales=list(args.scales),
        top_k=args.top_k,
        min_score=args.min_score,
        use_ncc=not args.no_ncc,
        min_query_patches=args.min_query_patches,
        max_target_tokens=args.max_target_tokens,
    )

    matches_path = output_dir / "matches.json"
    matches_path.write_text(
        json.dumps(
            {
                "query": str(query_path),
                "target": str(target_path),
                "scales": list(args.scales),
                "boxes": boxes,
            },
            indent=2,
        )
    )
    print(f"wrote {matches_path}")
    for b in boxes:
        print(f"  #{b['rank']} score={b['score']:.3f} bbox=({b['x']},{b['y']},{b['w']},{b['h']})")

    heatmap_path = output_dir / "heatmap.jpeg"
    render(target, heatmap, boxes, heatmap_path, display=not args.no_display)
    print(f"wrote {heatmap_path}")


if __name__ == "__main__":
    main()
