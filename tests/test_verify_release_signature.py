from __future__ import annotations

import base64
import hashlib

import pytest

from scripts import verify_release_signature


def test_verify_accepts_pinned_untrusted_self_signed_signature(tmp_path, monkeypatch):
    target = tmp_path / "signed.exe"
    target.write_bytes(b"signed payload")
    certificate = b"signer certificate"
    digest = hashlib.sha256(certificate).hexdigest()
    monkeypatch.setattr(
        verify_release_signature,
        "_signature_info",
        lambda path: {
            "status": "NotTrusted",
            "certificate": base64.b64encode(certificate).decode("ascii"),
            "timestamped": True,
        },
    )

    verify_release_signature.verify(target, digest)


def test_verify_rejects_hash_mismatch_status(tmp_path, monkeypatch):
    target = tmp_path / "damaged.exe"
    target.write_bytes(b"damaged payload")
    certificate = b"signer certificate"
    monkeypatch.setattr(
        verify_release_signature,
        "_signature_info",
        lambda path: {
            "status": "HashMismatch",
            "certificate": base64.b64encode(certificate).decode("ascii"),
            "timestamped": True,
        },
    )

    with pytest.raises(RuntimeError, match="HashMismatch"):
        verify_release_signature.verify(target, hashlib.sha256(certificate).hexdigest())


def test_verify_rejects_wrong_signer(tmp_path, monkeypatch):
    target = tmp_path / "wrong-signer.exe"
    target.write_bytes(b"signed payload")
    monkeypatch.setattr(
        verify_release_signature,
        "_signature_info",
        lambda path: {
            "status": "NotTrusted",
            "certificate": base64.b64encode(b"wrong certificate").decode("ascii"),
            "timestamped": True,
        },
    )

    with pytest.raises(RuntimeError, match="signer certificate mismatch"):
        verify_release_signature.verify(target, "0" * 64)


def test_verify_requires_timestamp(tmp_path, monkeypatch):
    target = tmp_path / "untimestamped.exe"
    target.write_bytes(b"signed payload")
    certificate = b"signer certificate"
    monkeypatch.setattr(
        verify_release_signature,
        "_signature_info",
        lambda path: {
            "status": "NotTrusted",
            "certificate": base64.b64encode(certificate).decode("ascii"),
            "timestamped": False,
        },
    )

    with pytest.raises(RuntimeError, match="not timestamped"):
        verify_release_signature.verify(target, hashlib.sha256(certificate).hexdigest())
