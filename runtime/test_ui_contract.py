from pathlib import Path
import json
import os
import re
import subprocess
import sys
import unittest


class StableUiMountContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        runtime = Path(__file__).parent
        cls.source = (runtime / "server_v2.py").read_text(encoding="utf-8")
        cls.anchor = (runtime / "pulse_anchor.html").read_text(encoding="utf-8")

    def test_room_mount_uri_remains_stable(self) -> None:
        from runtime import server_v2

        self.assertEqual(server_v2.ROOM_MOUNT_URI, server_v2.ROOM_URI)

    def test_pulse_tool_uses_current_cache_busted_resource(self) -> None:
        from runtime import server_v2

        legacy_uris = {
            server_v2.PULSE_ANCHOR_LEGACY_URI,
            server_v2.PULSE_ANCHOR_LEGACY_V44_URI,
            server_v2.PULSE_ANCHOR_LEGACY_V45_URI,
            server_v2.PULSE_ANCHOR_LEGACY_V46_URI,
            server_v2.PULSE_ANCHOR_LEGACY_V47_URI,
            server_v2.PULSE_ANCHOR_LEGACY_V48_URI,
            "ui://eiros/pulse-anchor-v4-9-singleton.html",
            "ui://eiros/pulse-anchor-v5-3-cache-busted-host-pip.html",
        }
        tool = server_v2.mcp._tool_manager._tools["open_pulse"]
        registered = {str(uri) for uri in server_v2.mcp._resource_manager._resources}

        self.assertEqual(server_v2.PULSE_ANCHOR_MOUNT_URI, server_v2.PULSE_ANCHOR_URI)
        self.assertNotIn(server_v2.PULSE_ANCHOR_MOUNT_URI, legacy_uris)
        self.assertEqual(tool.meta["ui"]["resourceUri"], server_v2.PULSE_ANCHOR_URI)
        self.assertEqual(tool.meta["openai/outputTemplate"], server_v2.PULSE_ANCHOR_URI)
        self.assertIn(server_v2.PULSE_ANCHOR_URI, registered)
        self.assertIn("ui://eiros/pulse-anchor-v5-3-cache-busted-host-pip.html", registered)

    def test_tool_results_report_mount_and_implementation_separately(self) -> None:
        self.assertIn('"resource_uri": ROOM_MOUNT_URI', self.source)
        self.assertIn('"implementation_uri": ROOM_URI', self.source)
        self.assertIn('"resource_uri": PULSE_ANCHOR_MOUNT_URI', self.source)
        self.assertIn('"implementation_uri": PULSE_ANCHOR_URI', self.source)

    def test_listener_bootstrap_contains_companion_hls(self) -> None:
        self.assertIn('COMPANION_ORIGIN = "https://178-105-43-79.sslip.io"', self.source)
        self.assertIn('COMPANION_HLS_URL', self.source)
        self.assertIn('"companionHlsUrl": COMPANION_HLS_URL', self.source)

    def test_companion_origin_is_allowlisted_for_video(self) -> None:
        self.assertIn("PULSE_EXTERNAL_DOMAINS", self.source)
        self.assertIn('"connectDomains": PULSE_EXTERNAL_DOMAINS', self.source)
        self.assertIn('"resourceDomains": PULSE_EXTERNAL_DOMAINS', self.source)
        self.assertIn('"connect_domains": PULSE_EXTERNAL_DOMAINS', self.source)
        self.assertIn('"resource_domains": PULSE_EXTERNAL_DOMAINS', self.source)

    def test_listener_uses_native_video_pip(self) -> None:
        self.assertIn('id="companionVideo"', self.anchor)
        self.assertIn("function requestSystemPiP", self.anchor)
        self.assertIn("webkitSetPresentationMode('picture-in-picture')", self.anchor)
        self.assertIn("requestPictureInPicture()", self.anchor)
        self.assertIn("video-pip:", self.anchor)

    def test_listener_exposes_visible_companion_stream(self) -> None:
        video_tag = re.search(r'<video id="companionVideo"[^>]*>', self.anchor)
        self.assertIsNotNone(video_tag)
        self.assertIn('class="companionVideo"', video_tag.group(0))
        self.assertIn("autoplay", video_tag.group(0))
        self.assertIn("controls", video_tag.group(0))
        self.assertIn('id="companionPanel"', self.anchor)
        self.assertIn('id="launchPip"', self.anchor)
        self.assertNotIn(".pipMedia{position:absolute", self.anchor)

    def test_ios_pip_arms_video_before_click(self) -> None:
        self.assertIn("function armCompanionVideo", self.anchor)
        self.assertIn("['pointerdown','touchstart']", self.anchor)
        self.assertIn("launchPip.addEventListener(kind,armCompanionVideo,{passive:true})", self.anchor)

    def test_companion_stream_uses_stable_csp_origin(self) -> None:
        from urllib.parse import urlparse
        from runtime import server_v2

        self.assertEqual(
            urlparse(server_v2.COMPANION_HLS_URL).netloc,
            urlparse(server_v2.COMPANION_ORIGIN).netloc,
        )
        self.assertIn(
            server_v2.COMPANION_ORIGIN,
            server_v2.PULSE_RESOURCE_META["ui"]["csp"]["resourceDomains"],
        )

    def test_rendered_listener_embeds_host_pip_controller(self) -> None:
        from runtime import server_v2

        html = server_v2.pulse_anchor_resource()
        self.assertIn("EirosPip.activateKeepalivePip", html)
        self.assertNotIn("__EIROS_PIP_CONTROLLER_JS__", html)

    def test_wake_uses_correlated_ui_message_request(self) -> None:
        self.assertIn("function bridgeRequest", self.anchor)
        self.assertIn("bridgeRequest('ui/message',payload)", self.anchor)
        self.assertIn("return 'bridge-confirmed'", self.anchor)
        self.assertNotIn("window.parent.postMessage({jsonrpc:'2.0',method:'ui/message'", self.anchor)

    def test_scheduled_sam_waits_for_active_video_pip(self) -> None:
        self.assertIn("payload.sam_kind==='scheduled_task'", self.anchor)
        self.assertIn("videoPipState!=='active'", self.anchor)
        self.assertIn("tap Открыть PiP to arm Video PiP", self.anchor)

    def _pulse_domain_meta_for_flag(self, flag: str | None) -> dict[str, object]:
        env = os.environ.copy()
        if flag is None:
            env.pop("EIROS_ENABLE_CUSTOM_WIDGET_DOMAIN", None)
        else:
            env["EIROS_ENABLE_CUSTOM_WIDGET_DOMAIN"] = flag
        script = """
import json
from runtime import server_v2
resource = server_v2.mcp._resource_manager._resources[server_v2.PULSE_ANCHOR_URI]
meta = resource.meta or {}
ui = meta.get('ui') or {}
print(json.dumps({'ui_domain': ui.get('domain'), 'legacy_domain': meta.get('openai/widgetDomain')}))
"""
        process = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).parent.parent,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(process.stdout)

    def test_custom_widget_domain_is_explicit_opt_in(self) -> None:
        managed = self._pulse_domain_meta_for_flag(None)
        custom = self._pulse_domain_meta_for_flag("true")

        self.assertEqual(managed, {"ui_domain": None, "legacy_domain": None})
        self.assertRegex(str(custom["ui_domain"]), r"^https://[^/]+$")
        self.assertEqual(custom["legacy_domain"], custom["ui_domain"])

    def test_doctor_reports_effective_managed_sandbox_mode(self) -> None:
        from runtime.doctor import run_doctor

        previous = os.environ.pop("EIROS_ENABLE_CUSTOM_WIDGET_DOMAIN", None)
        try:
            report = run_doctor(offline=True)
        finally:
            if previous is not None:
                os.environ["EIROS_ENABLE_CUSTOM_WIDGET_DOMAIN"] = previous
        check = next(item for item in report["checks"] if item["name"] == "widget_domain")

        self.assertEqual(check["details"]["mode"], "chatgpt_managed_sandbox")
        self.assertTrue(check["details"]["configured"])
        self.assertFalse(check["details"]["enabled"])

    def test_all_ui_resources_use_managed_sandbox_by_default(self) -> None:
        from runtime import server_v2

        self.assertEqual(server_v2.WIDGET_DOMAIN, "")
        resources = [
            (str(uri), resource)
            for uri, resource in server_v2.mcp._resource_manager._resources.items()
            if str(uri).startswith("ui://")
        ]
        self.assertGreater(len(resources), 0)
        for uri, resource in resources:
            with self.subTest(uri=uri):
                meta = resource.meta or {}
                ui = meta.get("ui") or {}
                self.assertNotIn("domain", ui)
                self.assertNotIn("openai/widgetDomain", meta)
                self.assertIn("csp", ui)
                self.assertIn("openai/widgetCSP", meta)


if __name__ == "__main__":
    unittest.main()
