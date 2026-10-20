"""Consistency checks for manifest.json, hacs.json and constants."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from custom_components.streckenwacht.const import DOMAIN, USER_AGENT, VERSION

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / DOMAIN


def manifest() -> dict:
    return json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))


def test_version_matches_const() -> None:
    assert manifest()["version"] == VERSION
    assert VERSION in USER_AGENT


def test_version_matches_pyproject() -> None:
    # A release bumps all three: manifest.json, const.py and pyproject.toml.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == VERSION


def test_domain_matches_folder() -> None:
    assert manifest()["domain"] == DOMAIN == INTEGRATION.name


def test_manifest_key_order() -> None:
    # hassfest requires domain, name first, then the remaining keys sorted.
    keys = list(manifest())
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_brand_images_present() -> None:
    names = {"icon", "logo", "dark_icon", "dark_logo"}
    for name in names:
        for suffix in (".png", "@2x.png"):
            assert (INTEGRATION / "brand" / f"{name}{suffix}").is_file()


def test_hacs_json() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["name"] == manifest()["name"]
