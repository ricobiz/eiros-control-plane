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
 assert "EIROS Widget Render: OK" in diagnostic
 assert "<script" not in diagnostic.lower()
 assert server_v2.WIDGET_TEST_URI.endswith("widget-test-v2.html")
 assert "domain" not in server_v2.WIDGET_TEST_META["ui"]
 assert "openai/widgetDomain" not in server_v2.WIDGET_TEST_META
 room_template=(ROOT/"runtime"/"collab_room.html").read_text()
 room_ids=set(re.findall(r'id="([^"]+)"',room_template))
 room_refs=set(re.findall(r"\$\('([^']+)'\)",room_template))
 assert not (room_refs-room_ids), f"missing room DOM ids: {sorted(room_refs-room_ids)}"
 room_rendered=server_v2.room_resource()
 assert "__EIROS_ROOM_BOOTSTRAP_JSON__" not in room_rendered
 assert "initialSnapshot" not in room_rendered
 assert len(room_rendered.encode("utf-8")) < 40000
 assert server_v2.ROOM_URI.endswith("collab-room-v9.html")
 assert "EIROS Control" in room_rendered
 assert "operator_send" in room_rendered and "request_immediate_wake" in room_rendered
 assert "Tunnel" in room_rendered and "Worker" in room_rendered and "Broker" in room_rendered and "Old card" in room_rendered
 launcher_rendered=server_v2.room_launcher_resource()
 assert "__EIROS_LAUNCHER_BOOTSTRAP_JSON__" not in launcher_rendered
 assert "pulse_poll" in launcher_rendered and "EIROS_OPEN_ROOM" in launcher_rendered and "Old card" in launcher_rendered
 assert server_v2.ROOM_LAUNCHER_URI.endswith("room-launcher-v1.html")
 original_status=server_v2.collab_engine.hub_status
 try:
  server_v2.collab_engine.hub_status=lambda:{"agents":[{"agent_id":"chatgpt","presence":"online","activity":"idle"},{"agent_id":"claude","presence":"offline","activity":"offline"}]}
  receipts=server_v2._delivery_receipts([{"message_id":"m1","to_agent":"chatgpt"},{"message_id":"m2","to_agent":"claude"}],[{"message_id":"m1","event_id":"e1"}])
 finally:
  server_v2.collab_engine.hub_status=original_status
 assert receipts[0]["mode"]=="wake queued"
 assert receipts[1]["mode"]=="offline mail"
 checks=["single placeholder","stable global name","instance binding","bridge methods","static diagnostic","legacy diagnostic compatibility","cache-busted URI","sandbox origin","room DOM bindings","lean room bootstrap","room cache-busted URI","dark control room","operator wake path","compact launcher","launcher pulse","delivery receipts","singleton stale guard","service lamp dashboard","english-only control UI"]
 print(json.dumps({"ok":True,"checks":checks,"count":len(checks)},indent=2))

if __name__=="__main__": main()
