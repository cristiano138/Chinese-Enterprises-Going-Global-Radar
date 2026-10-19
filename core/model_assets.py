"""Recover the bundled public Whisper weight when a builder leaves an LFS pointer."""
import hashlib
import os
from pathlib import Path
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = Path("models/faster-whisper-base/model.bin")
SIZE = 145217532
SHA256 = "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"
URL = ("https://www.modelscope.cn/api/v1/studio/zhanxy2551/ComplianceRadar-v2/repo"
       "?Revision=38a245dd1d34ead2281a8bb4bb9e04752bb208bb&FilePath=models/faster-whisper-base/model.bin")


def ensure_bundled_whisper(root=ROOT):
    """Replace only our known pointer, atomically; never download for an absent bundle."""
    path = Path(root) / MODEL_PATH
    if not path.is_file():
        return False
    with path.open("rb") as stream:
        header = stream.read(256).replace(b"\r\n", b"\n")
    if not header.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        return False
    if f"oid sha256:{SHA256}\nsize {SIZE}\n".encode() not in header:
        raise ValueError("Unrecognized bundled model pointer")
    deadline = time.monotonic() + 90
    digest = hashlib.sha256()
    count = 0
    temporary = None
    try:
        with urlopen(URL, timeout=30) as response, tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".whisper-weight-", delete=False) as target:
            temporary = Path(target.name)
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("Bundled model download timed out")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > SIZE:
                    raise ValueError("Bundled model exceeds expected size")
                digest.update(chunk)
                target.write(chunk)
        if count != SIZE or digest.hexdigest() != SHA256:
            raise ValueError("Bundled model integrity check failed")
        os.replace(temporary, path)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
