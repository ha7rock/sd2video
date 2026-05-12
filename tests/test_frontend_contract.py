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

    def test_prompt_resource_tokens_are_validated_before_submit(self) -> None:
        for name in ("app-components.jsx", "canvas.standalone.html"):
            with self.subTest(name=name):
                source = self._read(name)
                self.assertIn("MEDIA_REFERENCE_RE", source)
                self.assertIn("mediaReferenceToken", source)
                self.assertIn("onInsertReference={insertReferenceToken}", source)
                self.assertIn("onRemoveReference={removeReferenceToken}", source)
                self.assertIn("promptReferences", source)
                self.assertIn("已失效，请删除或重新插入", source)

    def test_camera_controls_are_prompt_augmentation_only(self) -> None:
        for name in ("app-components.jsx", "canvas.standalone.html"):
            with self.subTest(name=name):
                source = self._read(name)
                self.assertGreaterEqual(source.count('id: "'), 12)
                self.assertIn("CAMERA_PRESETS", source)
                self.assertIn("toggleCameraPreset", source)
                self.assertIn("appendPromptFragment", source)
                self.assertIn("camera_fixed: fixedCam", source)

    def test_panel_and_prompt_size_controls_are_persisted(self) -> None:
        for name in ("app-components.jsx", "canvas.standalone.html"):
            with self.subTest(name=name):
                source = self._read(name)
                self.assertIn('PANEL_WIDTH_KEY = "sd2video:create-panel-width"', source)
                self.assertIn('PROMPT_HEIGHT_KEY = "sd2video:prompt-height"', source)
                self.assertIn("startPanelResize", source)
                self.assertIn("resetPanelLayout", source)

        for name in ("canvas.html", "canvas.standalone.html"):
            with self.subTest(name=name):
                source = self._read(name)
                self.assertIn(".panel-resize", source)
                self.assertIn("resize:vertical", source)
                self.assertIn(".camera-grid", source)


if __name__ == "__main__":
    unittest.main()
