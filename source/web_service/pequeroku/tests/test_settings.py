from runpy import run_path

import pytest

import pequeroku.settings as project_settings


@pytest.mark.parametrize(
    ("value", "enabled"),
    [
        (None, False),
        ("0", False),
        ("false", False),
        ("typo", False),
        (" 1 ", True),
        ("TRUE", True),
    ],
)
def test_debug_requires_explicit_true_value(monkeypatch, value, enabled):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    if value is None:
        monkeypatch.delenv("DEBUG", raising=False)
    else:
        monkeypatch.setenv("DEBUG", value)

    assert run_path(project_settings.__file__)["DEBUG"] is enabled
