from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path


class RootFiles:
    def stat(self, path: str) -> dict[str, object]:
        p = Path(path).expanduser()
        s = p.lstat()
        return {
            "path": str(p),
            "size": s.st_size,
            "mode": format(stat.S_IMODE(s.st_mode), "04o"),
            "uid": s.st_uid,
            "gid": s.st_gid,
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "is_symlink": p.is_symlink(),
        }

    def list(self, path: str) -> list[dict[str, object]]:
        p = Path(path).expanduser()
        return [self.stat(str(x)) for x in sorted(p.iterdir(), key=lambda x: x.name)]

    def read(self, path: str, max_bytes: int = 200000) -> dict[str, object]:
        p = Path(path).expanduser()
        data = p.read_bytes()
        limit = max(1, min(int(max_bytes), 2_000_000))
        return {
            "path": str(p),
            "content": data[:limit].decode("utf-8", "replace"),
            "size": len(data),
            "truncated": len(data) > limit,
        }

    def write_atomic(self, path: str, content: str, mode: int = 0o600) -> dict[str, object]:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=str(p.parent))
        try:
            os.fchmod(fd, int(mode))
            os.write(fd, content.encode())
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(tmp, p)
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)
        return self.stat(str(p))

    def replace(self, path: str, old: str, new: str, count: int = 1) -> dict[str, object]:
        p = Path(path).expanduser()
        text = p.read_text()
        updated = text.replace(old, new, count if count > 0 else -1)
        if updated == text:
            raise ValueError("old text not found")
        return self.write_atomic(str(p), updated, stat.S_IMODE(p.stat().st_mode))

    def copy(self, src: str, dst: str) -> dict[str, object]:
        shutil.copy2(src, dst)
        return self.stat(dst)

    def move(self, src: str, dst: str) -> dict[str, object]:
        shutil.move(src, dst)
        return self.stat(dst)

    def mkdir(self, path: str, mode: int = 0o755) -> dict[str, object]:
        Path(path).mkdir(parents=True, exist_ok=True, mode=mode)
        return self.stat(path)

    def delete(self, path: str, recursive: bool = False) -> dict[str, object]:
        p = Path(path)
        existed = p.exists() or p.is_symlink()
        if p.is_dir() and not p.is_symlink():
            if recursive:
                shutil.rmtree(p)
            else:
                p.rmdir()
        elif existed:
            p.unlink()
        return {"ok": True, "path": str(p), "existed": existed}

    def chmod(self, path: str, mode: int) -> dict[str, object]:
        os.chmod(path, mode)
        return self.stat(path)

    def chown(self, path: str, uid: int, gid: int) -> dict[str, object]:
        os.chown(path, uid, gid)
        return self.stat(path)
