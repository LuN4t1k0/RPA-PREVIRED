import io
import zipfile
from pathlib import Path

import app


class _Empresa:
    rut = "76.123.456-7"


def test_local_zip_output_path_uses_documents_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    path = app._local_zip_output_path(_Empresa(), "2026-01", "2026-05")

    output = Path(path)
    assert output.name == "planillas_761234567_2026-01_2026-05.zip"
    assert output.parent.name == "Previred Downloader"
    assert output.parent.parent.name == "Documents"


def test_save_zip_to_disk_preserves_buffer_position(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("a.txt", "ok")
    buffer.seek(0)

    output = tmp_path / "nested" / "planillas.zip"
    app._save_zip_to_disk(buffer, str(output))

    assert output.exists()
    assert buffer.tell() == 0
    with zipfile.ZipFile(output) as zf:
        assert zf.read("a.txt") == b"ok"
