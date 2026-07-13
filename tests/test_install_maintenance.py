from __future__ import annotations

import hashlib

from scripts import install_maintenance


def test_import_signer_requires_pinned_certificate(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    root.mkdir()
    certificate = root / "FaceHello-Signer.cer"
    certificate.write_bytes(b"public certificate")
    digest = hashlib.sha256(certificate.read_bytes()).hexdigest()
    monkeypatch.setattr(install_maintenance.config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(install_maintenance, "_store_contains", lambda store, value: False)
    calls = []
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: calls.append(args))

    markers = install_maintenance._import_signer(root, (digest,))

    assert [call[3] for call in calls] == ["Root", "TrustedPublisher"]
    assert len(markers) == 2
    assert len(list((tmp_path / "data").glob("signer-*.installed"))) == 2


def test_import_signer_rejects_unpinned_certificate(tmp_path):
    root = tmp_path / "FaceHello"
    root.mkdir()
    (root / "FaceHello-Signer.cer").write_bytes(b"wrong certificate")

    try:
        install_maintenance._import_signer(root, ("0" * 64,))
    except RuntimeError:
        pass
    else:
        raise AssertionError("certificate pin mismatch should fail")


def test_owned_cp_accepts_only_versioned_dll_below_root(tmp_path):
    root = tmp_path / "FaceHello"
    root.mkdir()
    assert install_maintenance._owned_cp(root / "FaceHelloCP-1.2.3.dll", root)
    assert install_maintenance._owned_cp(root / "FaceHelloCP.dll", root)
    assert not install_maintenance._owned_cp(tmp_path / "other" / "FaceHelloCP-1.2.3.dll", root)


def test_configure_restarts_service_when_early_step_fails(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    root.mkdir()
    new_cp = root / "FaceHelloCP-1.1.0.dll"
    new_cp.write_bytes(b"new")
    monkeypatch.setattr(install_maintenance.config, "INSTALL_ROOT", root)
    monkeypatch.setattr(install_maintenance.config, "AVATAR_DIR", tmp_path / "data")
    monkeypatch.setattr(install_maintenance, "display_version", lambda: "1.1.0")
    monkeypatch.setattr(install_maintenance, "_registered_cp", lambda: None)
    calls = []

    def run(*args):
        calls.append(args)
        if args[0] == "icacls.exe":
            raise RuntimeError("acl failed")

    monkeypatch.setattr(install_maintenance, "_run", run)

    try:
        install_maintenance.configure("update", True)
    except RuntimeError:
        pass
    else:
        raise AssertionError("configure should fail")

    assert calls[-1][-1] == "start"


def test_configure_restores_old_cp_when_start_fails(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    root.mkdir()
    old_cp = root / "FaceHelloCP-1.0.0.dll"
    new_cp = root / "FaceHelloCP-1.1.0.dll"
    old_cp.write_bytes(b"old")
    new_cp.write_bytes(b"new")
    (root / "winservice_main.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(install_maintenance.config, "INSTALL_ROOT", root)
    monkeypatch.setattr(install_maintenance.config, "AVATAR_DIR", tmp_path / "data")
    monkeypatch.setattr(install_maintenance, "display_version", lambda: "1.1.0")
    monkeypatch.setattr(install_maintenance, "_registered_cp", lambda: old_cp)
    calls = []
    monkeypatch.setattr(install_maintenance, "_register", lambda path: calls.append(("reg", path)))
    monkeypatch.setattr(install_maintenance, "_unregister", lambda path: calls.append(("unreg", path)))
    run_calls = []
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: run_calls.append(args))
    monkeypatch.setattr(
        install_maintenance,
        "_wait_ready",
        lambda version: (_ for _ in ()).throw(RuntimeError("not ready")),
    )

    try:
        install_maintenance.configure("update", True)
    except RuntimeError:
        pass
    else:
        raise AssertionError("configure should fail")

    assert calls == [("reg", new_cp), ("unreg", new_cp), ("reg", old_cp)]
    assert run_calls[-1][-1] == "start"
