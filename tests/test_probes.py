from __future__ import annotations

from face_hello import probes


def test_service_health_accepts_matching_ready_response() -> None:
    health = probes.service_health(
        {"ok": True, "ready": True, "version": "1.0.4", "protocol": 1},
        "1.0.4",
    )

    assert health.healthy
    assert health.code == probes.ServiceHealthCode.HEALTHY
    assert health.version == "1.0.4"
    assert health.protocol == 1


def test_service_health_distinguishes_failure_states() -> None:
    cases = [
        (
            {"ok": True, "ready": False, "version": "1.0.4", "protocol": 1},
            probes.ServiceHealthCode.NOT_READY,
        ),
        (
            {"ok": True, "ready": True, "version": "1.0.3", "protocol": 1},
            probes.ServiceHealthCode.VERSION_MISMATCH,
        ),
        (
            {"ok": True, "ready": True, "version": "1.0.4", "protocol": 2},
            probes.ServiceHealthCode.PROTOCOL_MISMATCH,
        ),
    ]

    for response, expected in cases:
        assert probes.service_health(response, "1.0.4").code == expected


def test_service_health_rejects_malformed_responses() -> None:
    responses = [
        None,
        [],
        {},
        {"ok": False},
        {"ok": True, "ready": True, "version": "1.0.4"},
        {"ok": True, "ready": True, "version": 104, "protocol": 1},
        {"ok": True, "ready": True, "version": "1.0.4", "protocol": "1"},
        {"ok": True, "ready": True, "version": "1.0.4", "protocol": True},
        {"ok": True, "ready": "yes", "version": "1.0.4", "protocol": 1},
    ]

    for response in responses:
        health = probes.service_health(response, "1.0.4")
        assert health.code == probes.ServiceHealthCode.BAD_RESPONSE
        assert not health.healthy
