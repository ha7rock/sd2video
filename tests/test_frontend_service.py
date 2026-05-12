from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SOURCE = ROOT / "frontend_current" / "frontend" / "app-components.jsx"


def _service_source() -> str:
    source = FRONTEND_SOURCE.read_text(encoding="utf-8")
    start = source.index("const MODELS =")
    end = source.index("\nfunction Pill", start)
    return source[start:end]


class FrontendServiceCallTests(unittest.TestCase):
    maxDiff = None

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend service tests")
    def test_service_helpers_map_parameters_errors_and_task_state(self) -> None:
        script = textwrap.dedent(
            f"""
            const assert = require("assert");
            const calls = [];
            let responses = [];
            global.window = {{
              __SD2VIDEO_API_BASE__: "http://backend.test",
              localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }},
              crypto: {{ randomUUID() {{ return "uuid-frontend-1"; }} }}
            }};
            global.document = {{ querySelector() {{ return null; }} }};
            global.fetch = async (url, options = {{}}) => {{
              calls.push({{
                url: String(url),
                method: options.method || "GET",
                headers: options.headers || {{}},
                body: options.body || null
              }});
              if (!responses.length) throw new Error("No mocked response for " + url);
              const response = responses.shift();
              return {{
                ok: response.ok,
                status: response.status,
                text: async () => JSON.stringify(response.body)
              }};
            }};

            {_service_source()}

            (async () => {{
              const config = {{ mode: "dev", apiBase: "http://backend.test", createPath: "/api/v1/tasks" }};
              const payload = buildCreateTaskPayload({{
                mode: "reference",
                model: "doubao-seedance-2-0-fast-260128",
                prompt: "  Make a calm product shot  ",
                ratio: "9:16",
                resolution: "720p",
                duration: 4,
                seed: "42",
                camera_fixed: true,
                watermark: false,
                generate_audio: true,
                return_last_frame: true,
                webSearch: false,
                refImages: [{{ url: "https://cdn.test/ref.png" }}],
                refVideos: ["asset://video-1"],
                refAudios: [{{ url: "https://cdn.test/ref.mp3" }}]
              }});
              assert.strictEqual(payload.prompt, "Make a calm product shot");
              assert.strictEqual(payload.seed, 42);
              assert.strictEqual(payload.camera_fixed, true);
              assert.strictEqual(payload.generate_audio, true);
              assert.strictEqual(payload.return_last_frame, true);
              assert.deepStrictEqual(payload.assets.reference_images, ["https://cdn.test/ref.png"]);
              assert.deepStrictEqual(payload.assets.reference_videos, ["asset://video-1"]);
              assert.deepStrictEqual(payload.assets.reference_audios, ["https://cdn.test/ref.mp3"]);
              assert.ok(!("content" in payload));
              assert.ok(!("negative_prompt" in payload));
              assert.strictEqual(payload.client_request_id, "uuid-frontend-1");

              responses = [{{ ok: true, status: 201, body: {{ task_id: "cgt-created", status: "queued" }} }}];
              const created = await requestCreateVideoTask({{
                mode: "t2v",
                model: "doubao-seedance-2-0-fast-260128",
                prompt: "Create a test clip",
                ratio: "16:9",
                resolution: "480p",
                duration: 4
              }}, {{ config }});
              assert.strictEqual(created.taskId, "cgt-created");
              assert.strictEqual(created.status, "queued");
              assert.strictEqual(calls[0].url, "http://backend.test/api/v1/tasks");
              assert.strictEqual(calls[0].method, "POST");
              assert.strictEqual(calls[0].headers["Content-Type"], "application/json");
              assert.ok(JSON.parse(calls[0].body).client_request_id);

              responses = [{{ ok: false, status: 409, body: {{
                error: {{ code: "duplicate_request", message: "duplicate" }},
                existing: {{ task_id: "cgt-created", status: "running" }}
              }} }}];
              const duplicate = await createVideoTask(payload, config);
              assert.strictEqual(duplicate.duplicate, true);
              assert.strictEqual(duplicate.task_id, "cgt-created");
              assert.strictEqual(duplicate.status, "running");

              responses = [{{ ok: false, status: 400, body: {{
                error: {{ code: "parameter_invalid", field: "prompt", message: "prompt is required" }}
              }} }}];
              await assert.rejects(
                () => createVideoTask(payload, config),
                (err) => err.status === 400 && err.code === "parameter_invalid" &&
                  err.field === "prompt" && formatCreateError(err) === "prompt: prompt is required"
              );

              responses = [{{ ok: true, status: 200, body: {{
                task_id: "cgt-created",
                status: "succeeded",
                model: "doubao-seedance-2-0-fast-260128",
                video_url: "https://cdn.test/result.mp4"
              }} }}];
              const done = await requestTaskStatus("cgt-created", {{ config }});
              assert.strictEqual(done.videoUrl, "https://cdn.test/result.mp4");
              const donePatch = nodePatchFromTask(done);
              assert.strictEqual(typeof donePatch.completedAt, "number");
              delete donePatch.completedAt;
              assert.deepStrictEqual(donePatch, {{
                status: "done",
                taskStatus: "succeeded",
                task_status: "succeeded",
                statusText: "已完成",
                progress: 100,
                videoUrl: "https://cdn.test/result.mp4",
                video_url: "https://cdn.test/result.mp4",
                errorMessage: null,
                error_message: null
              }});

              responses = [{{ ok: true, status: 200, body: {{
                total: 1,
                items: [{{ task_id: "cgt-created", status: "succeeded", video_url: "https://cdn.test/result.mp4" }}]
              }} }}];
              const list = await requestListTasks({{ pageNum: 2, pageSize: 5, statusFilter: "succeeded", config }});
              assert.strictEqual(calls.at(-1).url, "http://backend.test/api/v1/tasks?page_num=2&page_size=5&status=succeeded");
              assert.strictEqual(list.items[0].taskId, "cgt-created");
              assert.strictEqual(list.hasMore, false);

              responses = [{{ ok: true, status: 200, body: {{ task_id: "cgt-created", status: "cancelled", deleted: true }} }}];
              const cancelled = await requestDeleteTask("cgt-created", {{ currentStatus: "running", config }});
              assert.strictEqual(calls.at(-1).method, "DELETE");
              assert.deepStrictEqual(JSON.parse(calls.at(-1).body), {{ current_status: "running" }});
              assert.strictEqual(cancelled.status, "cancelled");
            }})().catch((err) => {{
              console.error(err && err.stack || err);
              process.exit(1);
            }});
            """
        )

        subprocess.run(["node", "-e", script], cwd=ROOT, check=True)

    def test_create_panel_has_loading_error_and_duplicate_submit_guards(self) -> None:
        source = FRONTEND_SOURCE.read_text(encoding="utf-8")

        self.assertIn("if (submitting) return;", source)
        self.assertIn("setSubmitting(true);", source)
        self.assertIn("setSubmitError(formatCreateError(err));", source)
        self.assertIn("setSubmitting(false);", source)
        self.assertIn("disabled={!ok || !!firstError || submitting}", source)
        self.assertIn('{submitting ? "提交中…" : "生成视频"}', source)


if __name__ == "__main__":
    unittest.main()
