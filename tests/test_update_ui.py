from __future__ import annotations

from app.main import _update_error_key
from face_hello.updater import UpdateErrorCode


def test_update_errors_have_specific_ui_messages() -> None:
    expected = {
        UpdateErrorCode.NETWORK: "update_error_network",
        UpdateErrorCode.REMOTE_SERVICE: "update_error_remote_service",
        UpdateErrorCode.RATE_LIMIT: "update_error_rate_limit",
        UpdateErrorCode.INVALID_RELEASE: "update_error_invalid_release",
        UpdateErrorCode.UNSUPPORTED_MANIFEST: "update_error_unsupported_manifest",
        UpdateErrorCode.DISK_SPACE: "update_error_disk_space",
        UpdateErrorCode.DOWNLOAD: "update_error_download",
        UpdateErrorCode.VERIFY: "update_error_verify",
        UpdateErrorCode.CANCELLED: "update_cancelled",
    }

    for code, key in expected.items():
        assert _update_error_key(code.value) == key


def test_unknown_update_error_uses_generic_fallback() -> None:
    assert _update_error_key("unexpected") == "update_failed"
