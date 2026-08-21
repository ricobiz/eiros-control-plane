"""Keep the test suite out of the production data directory.

The control plane is deployed straight from its checkout and every long-running
service sets EIROS_DATA_DIR=/opt/eiros-control-plane, so a shell inherited from
one of them - or a plain `pytest` in the checkout, where runtime/config.py falls
back to the code root - pointed the suite at live state. Measured on this host
before this file existed, one `pytest` run:

  runtime/widget-mount-attempts.json   revision 96 -> 106, 5 new attempts
  runtime/queue.json                   rewritten

The widget attempts are the damaging one. runtime/test_sum_server_tools.py
exercises the open_* tools, and each call appends a MOUNT_REQUESTED row that no
browser will ever answer. widget_boot_status then finds an unserved mount and
reports HOST_DID_NOT_REQUEST_RESOURCE - a ChatGPT-side fault that never
happened, produced by running the tests.

The data root is therefore always redirected to a throwaway directory. Set
EIROS_TEST_ALLOW_LIVE_DATA_DIR=1 to opt out, which should only ever be needed
for a deliberate against-live diagnostic. Tests that set EIROS_DATA_DIR for
their own subprocesses are unaffected; they overwrite it themselves.
"""

import os
import shutil
import tempfile
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parent


def _seed_data_dir(target: Path) -> None:
    """Give the throwaway data dir the config every server reads at import time.

    Redirecting EIROS_DATA_DIR at an empty directory keeps the suite off live
    state but also makes `import runtime.claude_server` raise "missing remote
    config" during collection, which takes the whole module's tests with it.
    The committed *.example.json files are copied in under their real names, so
    imports resolve against example config and never against the deployment's.
    """
    config_dir = target / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (target / "runtime").mkdir(parents=True, exist_ok=True)
    for example in (_CODE_ROOT / "config").glob("*.example.json"):
        destination = config_dir / example.name.replace(".example.json", ".json")
        if not destination.exists():
            shutil.copyfile(example, destination)


if os.environ.get("EIROS_TEST_ALLOW_LIVE_DATA_DIR", "").strip().lower() not in {"1", "true", "yes"}:
    _data_dir = Path(tempfile.mkdtemp(prefix="eiros-pytest-data-"))
    _seed_data_dir(_data_dir)
    os.environ["EIROS_DATA_DIR"] = str(_data_dir)
