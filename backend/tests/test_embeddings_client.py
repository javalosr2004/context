from __future__ import annotations

import math

import pytest

from backend.embeddings_client import (
    NullEmbeddingsClient,
    cosine,
    step_fingerprint,
)
from backend.tutorial_schema import ActionTarget, TutorialAction, TutorialStep


def _step(instruction: str, *, label: str | None = None, description: str | None = None) -> TutorialStep:
    return TutorialStep(
        step_id="step_001",
        instruction=instruction,
        actions=[
            TutorialAction(
                type="click",
                target=ActionTarget(kind="element", label=label, description=description),
                requires_confirmation=False,
            )
        ],
        confidence=0.9,
    )


class TestCosine:
    def test_identical_vectors_yield_one(self) -> None:
        assert cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_yield_zero(self) -> None:
        assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_yield_negative_one(self) -> None:
        assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_partial_alignment_yields_intermediate(self) -> None:
        sim = cosine([1.0, 1.0], [1.0, 0.0])
        assert sim == pytest.approx(1.0 / math.sqrt(2.0))

    def test_empty_vectors_yield_zero(self) -> None:
        assert cosine([], []) == 0.0

    def test_mismatched_lengths_yield_zero(self) -> None:
        assert cosine([1.0, 0.0], [1.0]) == 0.0

    def test_zero_vector_yields_zero(self) -> None:
        assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestStepFingerprint:
    def test_uses_label_when_present(self) -> None:
        fingerprint = step_fingerprint(_step("Open the menu.", label="School"))
        assert "Open the menu." in fingerprint
        assert "click" in fingerprint
        assert "School" in fingerprint

    def test_falls_back_to_description_when_no_label(self) -> None:
        fingerprint = step_fingerprint(
            _step("Open the menu.", description="the School link in the sidebar")
        )
        assert "the School link in the sidebar" in fingerprint

    def test_skips_empty_fields(self) -> None:
        fingerprint = step_fingerprint(_step("Wait."))
        # No bare " | " separators leaking from missing label/description.
        assert " |  | " not in fingerprint

    def test_two_phrasings_of_same_step_share_a_fingerprint_prefix(self) -> None:
        # The fingerprint isn't a hash; identical action+target+instruction
        # text yields identical text. This guards against accidental noise
        # (action ordering, whitespace) creeping in.
        a = _step("Click School.", label="School")
        b = _step("Click School.", label="School")
        assert step_fingerprint(a) == step_fingerprint(b)


class TestNullEmbeddingsClient:
    def test_returns_empty_list(self) -> None:
        client = NullEmbeddingsClient()
        assert client.embed_batch(["a", "b"]) == []
