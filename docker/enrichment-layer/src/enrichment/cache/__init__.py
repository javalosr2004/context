"""Hot-path grounding caches for the enrichment-layer.

Five layered caches, from cheapest to most expensive:

    L1 — multimodal plan      (Phase 2)
    L2 — final snippets       (Phase 2)
    L3 — search hits          per-query, exact-string
    L4 — fetch + extract      per-URL, exact-string
    L5 — page summary         per (content_hash, goal, application)

Each layer reads on the way down, populates on the way up. A hit at any
layer short-circuits the layers below.
"""
from enrichment.cache.grounding_cache import (
    all_stats,
    l1_partition_for_image,
    l1_plan,
    l2_partition_for_context,
    l2_snippets,
    l2_text_for_queries,
    l3_search,
    l4_page,
    l5_summary,
)
from enrichment.cache.storage import InMemoryStorage, StorageProvider, StorageStats

__all__ = [
    "InMemoryStorage",
    "StorageProvider",
    "StorageStats",
    "all_stats",
    "l1_partition_for_image",
    "l1_plan",
    "l2_partition_for_context",
    "l2_snippets",
    "l2_text_for_queries",
    "l3_search",
    "l4_page",
    "l5_summary",
]
