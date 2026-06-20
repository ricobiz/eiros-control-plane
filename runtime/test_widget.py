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
 checks=["single placeholder","stable global name","instance binding","bridge methods","static diagnostic","legacy diagnostic compatibility","cache-busted URI","sandbox origin"]
 print(json.dumps({"ok":True,"checks":checks,"count":len(checks)},indent=2))

if __name__=="__main__": main()
