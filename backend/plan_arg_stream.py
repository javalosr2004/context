"""Incremental preview extraction for streamed ``tutorial_update_plan`` args.

The planner emits its plan inside the ``tutorial_update_plan`` tool call's
arguments JSON. OpenAI streams those arguments token-by-token via
``response.function_call_arguments.delta``. This module turns that growing
JSON string into per-step previews the overlay can render the instant each
step is generated, instead of waiting for the whole tool call to finish.

Hard rule: this is a COSMETIC preview. The authoritative plan is still the
one parsed from the completed tool call and merged in
``tutorial_session._execute_plan_update_call``. ``feed`` never raises — a
malformed or truncated buffer simply yields fewer previews.

The args object has exactly one array-valued top-level field (``plan``);
``plan_reasoning`` is a string and ``abandon_awaiting`` is a bool. So the
first structural ``[`` at object depth 1 is the plan array, regardless of
field order. We brace-count its element objects with full string/escape
awareness so braces or quotes inside an ``agent_description`` never throw
off the depth count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from backend.tutorial_tools import PlanItem


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanStepPreview:
    """One streamed step instruction, rendered ahead of the full plan."""

    index: int
    instruction: str
    confidence: float


class IncrementalPlanPreview:
    """Feed argument-JSON fragments; get back newly-completed step previews.

    Stateful and single-pass: each character is scanned exactly once, so
    repeated ``feed`` calls cost only the new bytes. Call ``reset`` when a
    fresh ``tutorial_update_plan`` call starts (a new tool-call id).
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._buffer = ""
        self._pos = 0
        self._stack: list[str] = []
        self._in_string = False
        self._escape = False
        self._plan_array_depth: int | None = None
        self._plan_done = False
        self._item_start: int | None = None
        self._next_index = 0

    def feed(self, delta: str) -> list[PlanStepPreview]:
        """Append ``delta`` and return previews completed by it (in order)."""
        if not delta or self._plan_done:
            self._buffer += delta
            return []
        self._buffer += delta
        previews: list[PlanStepPreview] = []
        buffer = self._buffer
        while self._pos < len(buffer):
            char = buffer[self._pos]
            self._pos += 1
            if self._in_string:
                if self._escape:
                    self._escape = False
                elif char == "\\":
                    self._escape = True
                elif char == '"':
                    self._in_string = False
                continue
            if char == '"':
                self._in_string = True
                continue
            if char in "{[":
                self._on_open(char)
            elif char in "}]":
                preview = self._on_close(char)
                if preview is not None:
                    previews.append(preview)
                if self._plan_done:
                    break
        return previews

    # --- internals ---

    def _on_open(self, char: str) -> None:
        # The first structural '[' at object depth 1 is the plan array.
        if (
            char == "["
            and self._plan_array_depth is None
            and self._stack == ["{"]
        ):
            self._stack.append(char)
            self._plan_array_depth = len(self._stack)
            return
        # A '{' opened directly inside the plan array starts a step item.
        if (
            char == "{"
            and self._plan_array_depth is not None
            and len(self._stack) == self._plan_array_depth
            and self._stack and self._stack[-1] == "["
        ):
            self._item_start = self._pos - 1
        self._stack.append(char)

    def _on_close(self, char: str) -> PlanStepPreview | None:
        if not self._stack:
            return None
        self._stack.pop()
        if self._plan_array_depth is None:
            return None
        # Back at the plan-array level after closing a step object.
        if (
            char == "}"
            and self._item_start is not None
            and len(self._stack) == self._plan_array_depth
        ):
            raw_item = self._buffer[self._item_start : self._pos]
            self._item_start = None
            return self._build_preview(raw_item)
        # The plan array itself closed — stop scanning for previews.
        if char == "]" and len(self._stack) < self._plan_array_depth:
            self._plan_done = True
        return None

    def _build_preview(self, raw_item: str) -> PlanStepPreview | None:
        try:
            item = PlanItem.model_validate_json(raw_item)
        except ValidationError:
            # Structurally complete but schema-invalid (rare). Still advance
            # the index so a later, valid item keeps a stable row position.
            logger.debug("[plan_stream] skipped invalid preview item")
            self._next_index += 1
            return None
        preview = PlanStepPreview(
            index=self._next_index,
            instruction=item.human_text,
            confidence=item.confidence,
        )
        self._next_index += 1
        return preview
