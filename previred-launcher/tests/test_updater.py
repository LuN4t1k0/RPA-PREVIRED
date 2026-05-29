import io
import zipfile

import updater


def test_get_local_sha_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "VERSION_FILE", tmp_path / ".version")
    assert updater.get_local_sha() == ""


def test_get_local_sha_existing(tmp_path, monkeypatch):
    version_file = tmp_path / ".version"
    version_file.write_text("abc123\n")
    monkeypatch.setattr(updater, "VERSION_FILE", version_file)
    assert updater.get_local_sha() == "abc123"


def test_needs_update_true(tmp_path, monkeypatch):
    version_file = tmp_path / ".version"
    version_file.write_text("abc123")
    monkeypatch.setattr(updater, "VERSION_FILE", version_file)
    monkeypatch.setattr(updater, "get_remote_sha", lambda: "def456")
    assert updater.needs_update() is True


def test_needs_update_false(tmp_path, monkeypatch):
    version_file = tmp_path / ".version"
    version_file.write_text("abc123")
    monkeypatch.setattr(updater, "VERSION_FILE", version_file)
    monkeypatch.setattr(updater, "get_remote_sha", lambda: "abc123")
    assert updater.needs_update() is False


def _make_github_zip(files: dict) -> bytes:
    """Build a zip mimicking GitHub's top-level owner-repo-sha/ folder."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(f"owner-repo-abc123/{name}", content)
    return buf.getvalue()


def test_extract_zip_contents(tmp_path):
    raw = _make_github_zip(
        {
            "app.py": "print('hello')",
            "bot/__init__.py": "",
            "requirements.txt": "streamlit\n",
        }
    )
    app_dir = tmp_path / "app"
    updater.extract_zip_contents(raw, app_dir)

    assert (app_dir / "app.py").read_text() == "print('hello')"
    assert (app_dir / "bot" / "__init__.py").exists()
    assert (app_dir / "requirements.txt").read_text() == "streamlit\n"


def test_extract_zip_overwrites_existing(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "old_file.txt").write_text("old")

    raw = _make_github_zip({"app.py": "new"})
    updater.extract_zip_contents(raw, app_dir)

    assert not (app_dir / "old_file.txt").exists()
    assert (app_dir / "app.py").read_text() == "new"
