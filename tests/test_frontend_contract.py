from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend_current" / "frontend"


class FrontendSafetyContractTests(unittest.TestCase):
    def _read(self, name: str) -> str:
        return (FRONTEND / name).read_text(encoding="utf-8")

    def _keyboard_delete_block(self, source: str) -> str:
        match = re.search(
            r'if\(\(e\.key==="Delete"\|\|e\.key==="Backspace"\)&&selId\)\{(?P<body>.*?)\n      \}',
            source,
            flags=re.S,
        )
        self.assertIsNotNone(match, "keyboard delete handler not found")
        return match.group("body")

    def test_keyboard_delete_uses_confirmed_delete_flow(self) -> None:
        for name in ("canvas.html", "canvas.standalone.html"):
            with self.subTest(name=name):
                block = self._keyboard_delete_block(self._read(name))
                self.assertIn("deleteNode(selId)", block)
                self.assertNotIn("setNodes(ns=>ns.filter", block)

    def test_cancel_failure_preserves_generating_task_state(self) -> None:
        for name in ("canvas.html", "canvas.standalone.html"):
            with self.subTest(name=name):
                source = self._read(name)
                self.assertIn('const message=err?.message||"取消任务失败，任务仍在继续轮询。";', source)
                self.assertNotIn('status:"error",errorMessage:err?.message||"取消任务失败"', source)

    def test_generating_delete_is_blocked_until_cancel_succeeds(self) -> None:
        for name in ("canvas.html", "canvas.standalone.html"):
            with self.subTest(name=name):
                source = self._read(name)
                self.assertIn('if(n.status==="generating"){', source)
                self.assertIn("请先取消任务，取消成功后再删除记录。", source)


if __name__ == "__main__":
    unittest.main()
