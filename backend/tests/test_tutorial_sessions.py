from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.main import create_app, get_tutorial_session_manager
from backend.tutorial_guide import TutorialSessionPlanRequest
from backend.tutorial_schema import PlannerReply, parse_tutorial_planner_reply
from backend.tutorial_sessions import TutorialSessionManager


VALID_PLAN_JSON = """
{
  "schema_version": "tutorial_plan.v1",
  "goal": "Create a new GitHub repository",
  "summary": "Open the repository creation flow and fill out the form.",
  "steps": [
    {
      "step_id": "step_001",
      "instruction": "Click the New repository button.",
      "action": {
        "type": "click",
        "target": {
          "kind": "element",
          "label": "New repository",
          "role": "button"
        }
      },
      "confidence": 0.86,
      "requires_confirmation": false
    }
  ]
}
""".strip()

UPDATED_PLAN_JSON = """
{
  "schema_version": "tutorial_plan.v1",
  "goal": "Create a new GitHub repository",
  "summary": "Use the visible Create button instead.",
  "steps": [
    {
      "step_id": "step_001",
      "instruction": "Click the visible Create button.",
      "action": {
        "type": "click",
        "target": {
          "kind": "element",
          "label": "Create",
          "role": "button"
        }
      },
      "confidence": 0.86,
      "requires_confirmation": false
    }
  ]
}
""".strip()

NEEDS_CONTEXT_REPLY_JSON = """
{
  "type": "needs_context",
  "question": "Which repository should I use?"
}
""".strip()


class StubTutorialGuide:
    def __init__(self, replies: list[PlannerReply]) -> None:
        self.replies = replies
        self.requests: list[TutorialSessionPlanRequest] = []

    def create_session_planner_reply(
        self,
        request: TutorialSessionPlanRequest,
    ) -> PlannerReply:
        self.requests.append(request)
        return self.replies.pop(0)


class TutorialSessionTests(unittest.TestCase):
    def test_create_session_returns_stable_id(self) -> None:
        manager = TutorialSessionManager(
            StubTutorialGuide([ready_reply(VALID_PLAN_JSON)]),
            session_id_factory=lambda: "session-1",
        )

        response = manager.create_session()

        self.assertEqual(response.session_id, "session-1")
        self.assertEqual(response.status, "created")
        self.assertEqual(manager.get_session("session-1").session_id, "session-1")

    def test_websocket_emits_session_ready(self) -> None:
        client = client_with_manager(
            TutorialSessionManager(
                StubTutorialGuide([ready_reply(VALID_PLAN_JSON)]),
                session_id_factory=lambda: "session-1",
            )
        )
        session_id = client.post("/tutorial-sessions").json()["session_id"]

        with client.websocket_connect(f"/tutorial-sessions/{session_id}/socket") as websocket:
            self.assertEqual(
                websocket.receive_json(),
                {"type": "session_ready", "session_id": "session-1"},
            )

    def test_user_message_emits_plan_ready_or_question(self) -> None:
        client = client_with_manager(
            TutorialSessionManager(
                StubTutorialGuide([needs_context_reply()]),
                session_id_factory=lambda: "session-1",
            )
        )
        session_id = client.post("/tutorial-sessions").json()["session_id"]

        with client.websocket_connect(f"/tutorial-sessions/{session_id}/socket") as websocket:
            websocket.receive_json()
            websocket.send_json(
                {"type": "user_message", "text": "Show me how to create a repo."}
            )

            events = [websocket.receive_json() for _ in range(4)]

        self.assertEqual(events[0]["type"], "request_received")
        self.assertEqual(events[1]["type"], "status_changed")
        self.assertEqual(events[1]["status"], "planning")
        self.assertEqual(events[2]["status"], "needs_context")
        self.assertEqual(events[3]["type"], "assistant_question")
        self.assertEqual(events[3]["question_id"], "question_002")

    def test_user_message_accepts_binary_json_websocket_frame(self) -> None:
        client = client_with_manager(
            TutorialSessionManager(
                StubTutorialGuide([ready_reply(VALID_PLAN_JSON)]),
                session_id_factory=lambda: "session-1",
            )
        )
        session_id = client.post("/tutorial-sessions").json()["session_id"]

        with client.websocket_connect(f"/tutorial-sessions/{session_id}/socket") as websocket:
            websocket.receive_json()
            websocket.send_json(
                {"type": "user_message", "text": "Show me how to create a repo."},
                mode="binary",
            )
            events = [websocket.receive_json() for _ in range(5)]

        self.assertEqual(events[0]["type"], "request_received")
        self.assertEqual(events[1]["status"], "planning")
        self.assertEqual(events[2]["type"], "plan_ready")
        self.assertEqual(events[3], {"type": "step_ready", "step_id": "step_001"})
        self.assertEqual(
            events[4],
            {"type": "awaiting_confirmation", "step_id": "step_001"},
        )

    def test_user_answer_resumes_context_interrupt(self) -> None:
        client = client_with_manager(
            TutorialSessionManager(
                StubTutorialGuide([needs_context_reply(), ready_reply(VALID_PLAN_JSON)]),
                session_id_factory=lambda: "session-1",
            )
        )
        session_id = client.post("/tutorial-sessions").json()["session_id"]

        with client.websocket_connect(f"/tutorial-sessions/{session_id}/socket") as websocket:
            websocket.receive_json()
            websocket.send_json(
                {"type": "user_message", "text": "Show me how to create a repo."}
            )
            for _ in range(4):
                websocket.receive_json()

            websocket.send_json(
                {
                    "type": "user_answer",
                    "question_id": "question_002",
                    "text": "Use the context repo.",
                }
            )
            events = [websocket.receive_json() for _ in range(4)]

        self.assertEqual(events[0]["status"], "planning")
        self.assertEqual(events[1]["type"], "plan_ready")
        self.assertEqual(events[2], {"type": "step_ready", "step_id": "step_001"})
        self.assertEqual(
            events[3],
            {"type": "awaiting_confirmation", "step_id": "step_001"},
        )

    def test_user_confirmation_true_completes_single_step_plan(self) -> None:
        client = client_with_manager(
            TutorialSessionManager(
                StubTutorialGuide([ready_reply(VALID_PLAN_JSON)]),
                session_id_factory=lambda: "session-1",
            )
        )
        session_id = client.post("/tutorial-sessions").json()["session_id"]

        with client.websocket_connect(f"/tutorial-sessions/{session_id}/socket") as websocket:
            websocket.receive_json()
            websocket.send_json(
                {"type": "user_message", "text": "Show me how to create a repo."}
            )
            for _ in range(5):
                websocket.receive_json()

            websocket.send_json(
                {
                    "type": "user_confirmation",
                    "step_id": "step_001",
                    "confirmed": True,
                    "note": None,
                    "screen": None,
                }
            )
            event = websocket.receive_json()

        self.assertEqual(event, {"type": "session_completed"})

    def test_user_confirmation_false_replans_from_current_screen(self) -> None:
        client = client_with_manager(
            TutorialSessionManager(
                StubTutorialGuide(
                    [ready_reply(VALID_PLAN_JSON), ready_reply(UPDATED_PLAN_JSON)]
                ),
                session_id_factory=lambda: "session-1",
            )
        )
        session_id = client.post("/tutorial-sessions").json()["session_id"]

        with client.websocket_connect(f"/tutorial-sessions/{session_id}/socket") as websocket:
            websocket.receive_json()
            websocket.send_json(
                {"type": "user_message", "text": "Show me how to create a repo."}
            )
            for _ in range(5):
                websocket.receive_json()

            websocket.send_json(
                {
                    "type": "user_confirmation",
                    "step_id": "step_001",
                    "confirmed": False,
                    "note": "The New repository button is not visible.",
                    "screen": None,
                }
            )
            events = [websocket.receive_json() for _ in range(4)]

        self.assertEqual(events[0]["status"], "planning")
        self.assertEqual(events[1]["type"], "plan_updated")
        self.assertEqual(events[1]["plan"]["summary"], "Use the visible Create button instead.")
        self.assertEqual(events[2], {"type": "step_ready", "step_id": "step_001"})
        self.assertEqual(
            events[3],
            {"type": "awaiting_confirmation", "step_id": "step_001"},
        )


def client_with_manager(manager: TutorialSessionManager) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_tutorial_session_manager] = lambda: manager
    return TestClient(app)


def ready_reply(plan_json: str) -> PlannerReply:
    return parse_tutorial_planner_reply(
        f"""
{{
  "type": "ready",
  "plan": {plan_json}
}}
""".strip()
    )


def needs_context_reply() -> PlannerReply:
    return parse_tutorial_planner_reply(NEEDS_CONTEXT_REPLY_JSON)


if __name__ == "__main__":
    unittest.main()
