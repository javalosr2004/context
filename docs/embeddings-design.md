# Embeddings in the tutorial loop

Design notes for introducing text embeddings into the tutorial session. Captured from a session debugging a Canvas-flow replan loop where the planner emitted four near-identical `click "School"` variants across four replans before progress.

## Motivating problem

Every replan in `tutorial_session.py` mints fresh step IDs via `step_counter`. As a result:

- `attempts_without_progress` (keyed by `step_id`) never increments across replans, because the next replan's "same logical step" arrives with a new ID.
- The planner has the *data* to detect the loop (completed prefix + rejection notes accumulate in `render_history`), but it doesn't reason about pattern-level recurrence and keeps proposing variants of the same failing action.

Inferring loops by **action kind** alone (e.g. "you clicked twice, stop") is too coarse — `click` is the dominant action and most consecutive clicks are legitimate. We need a **semantic** notion of "this step is the same logical step as one we already tried."

## Latency budget

`text-embedding-3-small` (OpenAI) returns in ~50–150 ms for a single small request. Multiple strings can be batched in one HTTP call. Relative to the rest of the loop:

| Step | Latency |
|---|---|
| Verifier gate (post-shipped optimizations) | 1.5–2.2 s |
| Planner stream end-to-end | 5–10 s |
| Embedding call (batched tail) | ~100 ms |

Embeddings are effectively free on this scale.

## Use cases, ranked by value-to-this-system

### 1. Stable `logical_id` across replans (loop detection)

Add a `logical_id` field alongside `step_id` on `TutorialStep`. When the planner emits a new tail, embed each candidate's `(instruction, action.kind, target_label)` and cosine-compare against all previously-seen steps. If similarity exceeds a threshold (~0.85), reuse the prior `logical_id`; otherwise mint a new one.

- `attempts_without_progress[logical_id]` now naturally counts repeated attempts at the same logical step across replans.
- Loop detection becomes deterministic Python state, not a planner-judgment.
- History can surface `"You have attempted logical step X three times: [variant 1] → blocked, [variant 2] → blocked, [variant 3] → blocked"` and force a `user_choice` escape hatch.

**Build first.** Smallest change, highest direct impact on the Canvas-loop failure mode.

### 2. Step → screen-summary alignment (cheap verifier shortcut)

The verifier already emits `screen_summary` ("Signed-in GitHub dashboard with repositories and feed visible") as a side effect of its vision call. That phrase is expensive — full image + vision tokens.

If the planner emits an `expected_screen_summary` per step ("you should see GitHub repository Settings page with Danger Zone visible"), then post-action you can:

1. Get the verifier's `screen_summary` (text)
2. Cosine-compare `expected` vs `actual`
3. High similarity → skip the full vision verdict, advance
4. Low similarity → fall through to the full verifier

For obvious cases, this skips the LLM call entirely. The verifier becomes a hot path only when embeddings are uncertain.

**Caveat:** requires planner-side schema extension (`expected_screen_summary` field) and a small prompt change. The accuracy of the shortcut depends on the planner writing useful expectations.

### 3. In-plan deduplication

When a single replan emits two adjacent steps with high cosine similarity (e.g. `"Open Courses"` and `"Open All Courses"`), flag at merge time. Either collapse them or send back to the planner with a "distinguish or remove" prompt.

Small, low-risk, cleans up a common minor planner failure.

### 4. Cross-session retrieval (longer-term, high ceiling)

Embed every `(goal, completed_plan)` pair from shipped sessions. On a new goal:

1. Retrieve the closest N prior trajectories
2. Prepend them as exemplars in the planner prompt
3. Planner uses them as hints, not scripts

This turns the recording side of the product into priors for the live tutorial: every successful session improves the next one. No model training — just embed-and-retrieve.

**Requires:** a persistence layer (vector store or just a JSONL + numpy index) and an ingestion step. Different scope from (1)–(3).

### 5. Goal → completed-trajectory similarity (early completion)

Embed the goal and the concatenation of completed step instructions. When cosine crosses a threshold, proactively trigger the completion check instead of waiting for the planner to propose it.

In the Canvas log, this would have proposed completion 1–2 steps earlier than the planner did. In the GitHub-private-repo log, it would have caught completion much earlier (the user was already done).

### 6. Failure memory per app

Embed `agent_description`s of actions that ended with `verdict=blocked` or `diverged`, scoped by visible application. Build a prior of "things that don't reliably work on Canvas/GitHub/etc."

Next session on the same app, the planner gets:
> *"On Canvas, clicks labeled 'School' have failed 3 of 4 times — prefer URL navigation or asking the user."*

Requires the same persistence layer as (4).

### 7. History compaction

The history list grows linearly with replans. When it gets long, drop or merge near-duplicate entries by embedding similarity to keep the planner prompt from bloating.

Cosmetic relative to (1)–(3) but worth keeping in mind once sessions get longer.

### 8. Smarter web-grounding fallback

The `enrichment_client` 403s on every observed session and returns no snippets. If you maintained a small embedded corpus of help docs (Canvas, GitHub, common apps), goal-text embedding → closest 2–3 snippets → into the planner prompt would replace the broken path.

Lower priority than fixing the upstream service, but the embedding infrastructure built for (1)–(3) makes it trivial.

## Architecture sketch

One new module: `backend/embeddings_client.py`.

```python
class EmbeddingsClient:
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

Plus helpers:

```python
def cosine(a: list[float], b: list[float]) -> float: ...
def step_fingerprint(step: TutorialStep) -> str:
    """Canonical text fed to the embedder."""
    parts = [step.instruction]
    for action in step.actions:
        parts.append(action.type)
        if action.target and action.target.label:
            parts.append(action.target.label)
    return " | ".join(parts)
```

`TutorialStep` gains `logical_id: str`. Default = `step_id` (back-compat). `plan_merge.merge_plan_tail` consults the embeddings client during merge and sets `logical_id` accordingly.

`TutorialSession` keeps a `step_embeddings: dict[str, list[float]]` cache so we never re-embed a logical step we've already seen.

## Recommended build order

1. **`embeddings_client.py` + `logical_id` on `TutorialStep`** — unlocks (1).
2. **Loop detection + forced `user_choice` escape** — consumes (1).
3. **In-plan dedup at merge time** — reuses (1)'s infrastructure for (3).
4. **`expected_screen_summary` schema + pre-verifier shortcut** — implements (2). Bigger schema change; keep separate.
5. **Persistence layer + retrieval (4, 6)** — long-horizon project.

Items 1–3 share infrastructure and can ship together. Item 4 is independent. Items 5+ depend on persistence design choices not made yet.
