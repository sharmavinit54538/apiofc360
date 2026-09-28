"""Test configuration import and ensure no duplicate fields exist in Settings."""

import ast
from pathlib import Path

from app.core.config import Settings, settings


def test_config_import_success():
    """Verify that Settings can be imported and instantiated without errors."""
    assert settings is not None
    assert hasattr(settings, "OLLAMA_HOST")
    assert hasattr(settings, "OLLAMA_BASE_URL")
    assert hasattr(settings, "OLLAMA_MODEL")
    assert settings.OLLAMA_MODEL == "qwen3:30b"


def test_no_duplicate_settings_fields():
    """Ensure no duplicate field annotations exist in the Settings class."""
    config_path = Path(__file__).resolve().parent.parent / "app" / "core" / "config.py"
    with open(config_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    settings_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            settings_class = node
            break

    assert settings_class is not None, "Settings class not found in config.py"

    field_counts = {}
    for item in settings_class.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            name = item.target.id
            field_counts[name] = field_counts.get(name, 0) + 1

    duplicates = {name: count for name, count in field_counts.items() if count > 1}
    assert not duplicates, f"Found duplicate fields in Settings class: {duplicates}"


def test_ollama_host_sync_with_base_url():
    """Verify that OLLAMA_HOST defaults or syncs with OLLAMA_BASE_URL when not explicitly provided."""
    # When OLLAMA_HOST is not explicitly in env, it should match OLLAMA_BASE_URL
    custom_settings = Settings(
        OLLAMA_BASE_URL="http://host.docker.internal:11434",
    )
    assert custom_settings.OLLAMA_HOST == "http://host.docker.internal:11434"

    # When OLLAMA_HOST is explicitly provided, it should keep its explicit value
    explicit_settings = Settings(
        OLLAMA_BASE_URL="http://host.docker.internal:11434",
        OLLAMA_HOST="http://custom-ollama:11434",
    )
    assert explicit_settings.OLLAMA_HOST == "http://custom-ollama:11434"
