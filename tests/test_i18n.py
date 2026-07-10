from __future__ import annotations

from string import Formatter

from face_hello.i18n import DEFAULT_LANG, _CATALOG


def _fields(text: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(text) if field}


def test_catalog_keys_and_placeholders_match() -> None:
    base = _CATALOG[DEFAULT_LANG]
    for catalog in _CATALOG.values():
        assert catalog.keys() == base.keys()
        for key, text in catalog.items():
            assert _fields(text) == _fields(base[key])
