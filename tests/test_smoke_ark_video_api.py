import os
import unittest

from sd2video import ArkClient, CreateTaskRequest


def _smoke_enabled() -> bool:
    return os.environ.get("ARK_RUN_SMOKE_TESTS") == "1"


@unittest.skipUnless(
    _smoke_enabled(),
    "set ARK_RUN_SMOKE_TESTS=1 to run live Ark smoke tests",
)
class ArkVideoApiSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        if not os.environ.get("ARK_API_KEY"):
            self.skipTest("ARK_API_KEY is required for live smoke tests")
        self.client = ArkClient.from_env()

    def test_list_tasks_live(self) -> None:
        result = self.client.list_tasks(page_num=1, page_size=1)

        self.assertGreaterEqual(result.total, 0)
        self.assertLessEqual(len(result.items), 1)

    def test_create_task_live_explicit_cost_opt_in(self) -> None:
        if os.environ.get("ARK_SMOKE_CREATE_TASK") != "1":
            self.skipTest("set ARK_SMOKE_CREATE_TASK=1 to create a real paid task")

        model = os.environ.get("ARK_SMOKE_MODEL_ID")
        if not model:
            self.skipTest("ARK_SMOKE_MODEL_ID is required to create a live task")

        prompt = os.environ.get(
            "ARK_SMOKE_PROMPT",
            "A single red ball rolling slowly across a plain white floor.",
        )
        duration = int(os.environ.get("ARK_SMOKE_DURATION", "4"))

        request = CreateTaskRequest.text_to_video(
            prompt,
            model=model,
            ratio=os.environ.get("ARK_SMOKE_RATIO", "16:9"),
            resolution=os.environ.get("ARK_SMOKE_RESOLUTION", "480p"),
            duration=duration,
        )
        task_id = self.client.create_task(request)

        self.assertTrue(task_id)
        detail = self.client.get_task(task_id)
        self.assertIn(
            detail.status,
            {"queued", "running", "succeeded", "failed", "cancelled"},
        )
