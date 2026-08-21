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
import tempfile

if os.environ.get("EIROS_TEST_ALLOW_LIVE_DATA_DIR", "").strip().lower() not in {"1", "true", "yes"}:
    os.environ["EIROS_DATA_DIR"] = tempfile.mkdtemp(prefix="eiros-pytest-data-")
