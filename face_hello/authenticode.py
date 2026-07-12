"""Windows Authenticode 信任校验。发布者 pin 在生产证书落地后启用。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuthenticodeResult:
    trusted: bool
    status: int


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_ = [
        ("cbStruct", wintypes.DWORD),
        ("pcwszFilePath", wintypes.LPCWSTR),
        ("hFile", wintypes.HANDLE),
        ("pgKnownSubject", ctypes.POINTER(_GUID)),
    ]


class _WINTRUST_DATA(ctypes.Structure):
    _fields_ = [
        ("cbStruct", wintypes.DWORD),
        ("pPolicyCallbackData", wintypes.LPVOID),
        ("pSIPClientData", wintypes.LPVOID),
        ("dwUIChoice", wintypes.DWORD),
        ("fdwRevocationChecks", wintypes.DWORD),
        ("dwUnionChoice", wintypes.DWORD),
        ("pFile", ctypes.POINTER(_WINTRUST_FILE_INFO)),
        ("dwStateAction", wintypes.DWORD),
        ("hWVTStateData", wintypes.HANDLE),
        ("pwszURLReference", wintypes.LPWSTR),
        ("dwProvFlags", wintypes.DWORD),
        ("dwUIContext", wintypes.DWORD),
        ("pSignatureSettings", wintypes.LPVOID),
    ]


_WINTRUST_ACTION_GENERIC_VERIFY_V2 = _GUID(
    0x00AAC56B,
    0xCD44,
    0x11D0,
    (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
)
_WTD_UI_NONE = 2
_WTD_REVOKE_WHOLECHAIN = 1
_WTD_CHOICE_FILE = 1
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT = 0x80


def verify_authenticode(path: Path) -> AuthenticodeResult:
    """用 WinVerifyTrust 校验签名、信任链、吊销状态和时间戳。"""
    if sys.platform != "win32":
        raise NotImplementedError("Authenticode verification requires Windows")
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    file_info = _WINTRUST_FILE_INFO(
        ctypes.sizeof(_WINTRUST_FILE_INFO), str(path), None, None
    )
    trust_data = _WINTRUST_DATA()
    trust_data.cbStruct = ctypes.sizeof(_WINTRUST_DATA)
    trust_data.dwUIChoice = _WTD_UI_NONE
    trust_data.fdwRevocationChecks = _WTD_REVOKE_WHOLECHAIN
    trust_data.dwUnionChoice = _WTD_CHOICE_FILE
    trust_data.pFile = ctypes.pointer(file_info)
    trust_data.dwStateAction = _WTD_STATEACTION_VERIFY
    trust_data.dwProvFlags = _WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT

    verify = ctypes.windll.wintrust.WinVerifyTrust
    verify.argtypes = [wintypes.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(_WINTRUST_DATA)]
    verify.restype = wintypes.LONG
    status = int(verify(None, ctypes.byref(_WINTRUST_ACTION_GENERIC_VERIFY_V2), ctypes.byref(trust_data)))
    trust_data.dwStateAction = _WTD_STATEACTION_CLOSE
    verify(None, ctypes.byref(_WINTRUST_ACTION_GENERIC_VERIFY_V2), ctypes.byref(trust_data))
    return AuthenticodeResult(status == 0, status)
