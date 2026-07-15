from __future__ import annotations

from face_hello.authenticode import AuthenticodeResult
from face_hello.updater import DownloadResult, UpdateError, UpdateErrorCode
from face_hello.version import BuildInfo


def _build_info(signers: tuple[str, ...]) -> BuildInfo:
    return BuildInfo("1.0.3", "v1.0.3", "a" * 40, "2026-07-13T00:00:00Z", signers)


def test_update_check_preserves_specific_error_code(monkeypatch):
    from app import workers

    monkeypatch.setattr(workers, "get_current_version", lambda: None)
    monkeypatch.setattr(
        workers,
        "check_latest",
        lambda version: (_ for _ in ()).throw(
            UpdateError(UpdateErrorCode.NETWORK, "timed out")
        ),
    )
    failures = []
    worker = workers.UpdateCheckWorker()
    worker.failed.connect(lambda code, detail: failures.append((code, detail)))

    worker.run()

    assert failures == [(UpdateErrorCode.NETWORK.value, "timed out")]


def test_installed_download_requires_signer_pin(monkeypatch, tmp_path):
    from app import workers

    installer = tmp_path / "FaceHello-Setup-1.0.3.exe"
    installer.write_bytes(b"installer")
    monkeypatch.setattr(workers.config, "IS_INSTALLED", True)
    monkeypatch.setattr(
        workers,
        "download_installer",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not download without a signer pin")
        ),
    )
    monkeypatch.setattr(workers, "get_build_info", lambda: _build_info(()))
    verified = []
    monkeypatch.setattr(workers, "verify_authenticode", lambda *args: verified.append(args))
    failures = []
    downloaded = []
    worker = workers.UpdateDownloadWorker(object())
    worker.failed.connect(lambda code, detail: failures.append((code, detail)))
    worker.downloaded.connect(downloaded.append)

    worker.run()

    assert failures == [(UpdateErrorCode.VERIFY.value, "release build has no signer pin")]
    assert downloaded == []
    assert verified == []
    assert installer.exists()


def test_installed_download_verifies_pinned_signer(monkeypatch, tmp_path):
    from app import workers

    installer = tmp_path / "FaceHello-Setup-1.0.3.exe"
    installer.write_bytes(b"installer")
    signers = ("a" * 64,)
    monkeypatch.setattr(workers.config, "IS_INSTALLED", True)
    monkeypatch.setattr(
        workers, "download_installer", lambda *args, **kwargs: DownloadResult(installer, False)
    )
    monkeypatch.setattr(workers, "get_build_info", lambda: _build_info(signers))
    seen = []
    monkeypatch.setattr(
        workers,
        "verify_authenticode",
        lambda path, expected: seen.append((path, expected))
        or AuthenticodeResult(True, 0, expected[0]),
    )
    downloaded = []
    worker = workers.UpdateDownloadWorker(object())
    worker.downloaded.connect(downloaded.append)

    worker.run()

    assert seen == [(installer, signers)]
    assert downloaded == [str(installer)]


def test_development_download_does_not_require_release_pin(monkeypatch, tmp_path):
    from app import workers

    installer = tmp_path / "FaceHello-Setup-1.0.3.exe"
    installer.write_bytes(b"installer")
    monkeypatch.setattr(workers.config, "IS_INSTALLED", False)
    monkeypatch.setattr(
        workers, "download_installer", lambda *args, **kwargs: DownloadResult(installer, False)
    )
    monkeypatch.setattr(workers, "get_build_info", lambda: _build_info(()))
    monkeypatch.setattr(
        workers,
        "verify_authenticode",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not verify development download")),
    )
    downloaded = []
    worker = workers.UpdateDownloadWorker(object())
    worker.downloaded.connect(downloaded.append)

    worker.run()

    assert downloaded == [str(installer)]
