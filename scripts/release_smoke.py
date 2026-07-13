from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))

    import numpy as np

    import app.main  # noqa: F401
    import face_hello.win_service  # noqa: F401
    from face_hello import config
    from face_hello.detector import FaceDetector
    from face_hello.liveness import FaceMeshTracker
    from face_hello.version import get_build_info, get_current_version

    if config.ROOT.resolve() != root:
        raise RuntimeError(f"portable root mismatch: {config.ROOT}")
    build_info = get_build_info()
    if not build_info.is_release or get_current_version() is None:
        raise RuntimeError("portable build has no valid release version")
    certificate = root / "FaceHello-Signer.cer"
    if bool(build_info.signer_sha256) != certificate.is_file():
        raise RuntimeError("portable signer pin and certificate must be present together")
    if certificate.is_file():
        certificate_sha256 = hashlib.sha256(certificate.read_bytes()).hexdigest()
        if certificate_sha256 not in build_info.signer_sha256:
            raise RuntimeError("portable signer certificate does not match build info")
    FaceDetector().load()
    tracker = FaceMeshTracker()
    try:
        tracker.process(np.zeros((480, 640, 3), dtype=np.uint8))
    finally:
        tracker.close()
    print("portable smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
