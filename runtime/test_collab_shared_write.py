from __future__ import annotations

import grp
import os
import pwd
import stat

import pytest

from runtime.collab import _atomic_write


def _eiros_ids() -> tuple[int, int]:
    try:
        return pwd.getpwnam("eiros").pw_uid, grp.getgrnam("eiros").gr_gid
    except KeyError:
        pytest.skip("production shared user/group 'eiros' is not available")


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership regression requires a root-side writer")
def test_root_atomic_write_preserves_eiros_shared_store_ownership(tmp_path):
    """A root-side dialog write must not lock the eiros services out of collab.json."""
    eiros_uid, eiros_gid = _eiros_ids()
    store = tmp_path / "collab.json"
    store.write_text('{"schema_version": 1}\n', encoding="utf-8")
    os.chown(store, eiros_uid, eiros_gid)
    os.chmod(store, 0o660)

    _atomic_write(store, {"schema_version": 1, "revision": 1})

    meta = store.stat()
    assert meta.st_uid == eiros_uid
    assert meta.st_gid == eiros_gid
    assert stat.S_IMODE(meta.st_mode) == 0o660
    assert os.access(store, os.R_OK | os.W_OK, effective_ids=False)
