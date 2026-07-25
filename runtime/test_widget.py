from __future__ import annotations
import json,re
from pathlib import Path
from runtime import server_v2
ROOT=Path(__file__).resolve().parents[1]

def main():
 widget=(ROOT/"runtime"/"pulse_widget.html").read_text()
 assert widget.count("__EIROS_BOOTSTRAP_JSON__")==1
 assert "window.__EIROS_BOOTSTRAP__=__EIROS_BOOTSTRAP_JSON__;" in widget
 bootstrap={"instanceId":"instance-test","channel":"channel-test","displayName":"EIROS Test","polling":{"active_ms":750},"serverVersion":"test"}
 rendered=widget.replace("__EIROS_BOOTSTRAP_JSON__",json.dumps(bootstrap))
 assert "__EIROS_BOOTSTRAP_JSON__" not in rendered
 assert "window.__EIROS_BOOTSTRAP__={" in rendered
 assert "window.{" not in rendered
 assert "instance-test" in rendered and "channel-test" in rendered
 assert "ui/message" in rendered and "tools/call" in rendered
 scripts=re.findall(r"<script>(.*?)</script>",rendered,flags=re.DOTALL)
 assert len(scripts)==1 and scripts[0].count("(function(){")==1
 diagnostic=server_v2.widget_test_resource()
 assert diagnostic==server_v2.widget_test_resource_legacy()
 assert "EIROS Kill Switch" in diagnostic
 assert "eiros-ui-kill" in diagnostic and "<script" in diagnostic.lower()
 assert server_v2.WIDGET_TEST_URI.endswith("widget-test-v2.html")
 assert "domain" not in server_v2.WIDGET_TEST_META["ui"]
 assert "openai/widgetDomain" not in server_v2.WIDGET_TEST_META
 room_template=(ROOT/"runtime"/"collab_room.html").read_text()
 room_ids=set(re.findall(r'id="([^"]+)"',room_template))
 room_refs=set(re.findall(r"\$\('([^']+)'\)",room_template))
 assert not (room_refs-room_ids), f"missing room DOM ids: {sorted(room_refs-room_ids)}"
 room_rendered=server_v2.room_resource()
 assert "__EIROS_ROOM_BOOTSTRAP_JSON__" not in room_rendered
 assert "initialSystem" in room_rendered
 assert len(room_rendered.encode("utf-8")) < 50000
 assert server_v2.ROOM_URI == "ui://eiros/collab-room-v9-19-clean-start.html"
 assert "EIROS Control" in room_rendered
 assert "operator_send" in room_rendered and "request_immediate_wake" in room_rendered
 assert "room_cleanup_stale" in room_rendered and "dockFresh" in room_rendered and "EIROS_SCHEDULED_WAKE" in room_rendered
 assert "FROM_ROLE: user" in room_rendered and "FROM_AGENT: rico" in room_rendered and "rico_authorized_durable_scheduler_continuation" in room_rendered
 assert "pending messages preserved" in room_rendered and "waiting for Room Pulse leadership" in room_rendered
 assert server_v2.room_resource_legacy_v914() == room_rendered and server_v2.room_resource_legacy_v916() == room_rendered
 assert "noticeUntil" in room_rendered and "Refreshed ·" in room_rendered
 assert "lampShort" in room_rendered and "lastSig=null" in room_rendered and "room_telemetry_update" in room_rendered and "Both agents" in room_rendered
 launcher_rendered=server_v2.room_launcher_resource()
 assert "__EIROS_LAUNCHER_BOOTSTRAP_JSON__" not in launcher_rendered
 assert "launcher static proof" in launcher_rendered and "room_snapshot" in launcher_rendered and "REFRESHING" in launcher_rendered
 assert server_v2.ROOM_LAUNCHER_URI.endswith("room-launcher-v1d-static-proof.html")
 original_status=server_v2.collab_engine.hub_status
 try:
  server_v2.collab_engine.hub_status=lambda:{"agents":[{"agent_id":"chatgpt","presence":"online","activity":"idle"},{"agent_id":"claude","presence":"offline","activity":"offline"}]}
  receipts=server_v2._delivery_receipts([{"message_id":"m1","to_agent":"chatgpt"},{"message_id":"m2","to_agent":"claude"}],[{"message_id":"m1","event_id":"e1"}])
 finally:
  server_v2.collab_engine.hub_status=original_status
 assert receipts[0]["mode"]=="wake queued"
 assert receipts[1]["mode"]=="offline mail"
 checks=["single placeholder","stable global name","instance binding","bridge methods","static diagnostic","legacy diagnostic compatibility","cache-busted URI","sandbox origin","room DOM bindings","lean room bootstrap","room cache-busted URI","dark control room","operator wake path","scheduled user-origin wake","pending message preservation","legacy v9.14/v9.16/v9.18 aliases","compact launcher","launcher pulse","delivery receipts","singleton stale guard","service lamp dashboard","english-only control UI","compact mobile layout","empty room render fix","micro service lamps","widget telemetry"]
 print(json.dumps({"ok":True,"checks":checks,"count":len(checks)},indent=2))

if __name__=="__main__": main()
