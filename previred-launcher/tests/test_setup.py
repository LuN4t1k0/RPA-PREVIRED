from pathlib import Path

import setup


def test_is_python_ready_false(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "PYTHON_DIR", tmp_path / "python")
    assert setup.is_python_ready() is False


def test_is_python_ready_true(tmp_path, monkeypatch):
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    (python_dir / "python.exe").write_text("")
    monkeypatch.setattr(setup, "PYTHON_DIR", python_dir)
    assert setup.is_python_ready() is True


def test_is_playwright_ready_false(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "PLAYWRIGHT_MARKER", tmp_path / ".playwright_done")
    assert setup.is_playwright_ready() is False


def test_is_playwright_ready_true(tmp_path, monkeypatch):
    marker = tmp_path / ".playwright_done"
    marker.write_text("done")
    monkeypatch.setattr(setup, "PLAYWRIGHT_MARKER", marker)
    assert setup.is_playwright_ready() is True
