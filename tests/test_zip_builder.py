import io
import os
import zipfile
import tempfile
import pytest
from zip_builder import construir_zip


@pytest.fixture
def directorio_con_pdfs(tmp_path):
    (tmp_path / "Capital").mkdir(parents=True)
    (tmp_path / "Cuprum").mkdir(parents=True)
    (tmp_path / "Capital" / "617030004_2010-01_COLCHONES.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "Cuprum" / "617030004_2010-01_COLCHONES.pdf").write_bytes(b"%PDF-1.4 fake2")
    (tmp_path / "checkpoint.json").write_text("{}")
    return tmp_path


def test_zip_contiene_archivos(directorio_con_pdfs):
    buffer = construir_zip(str(directorio_con_pdfs))
    with zipfile.ZipFile(buffer) as zf:
        nombres = zf.namelist()
    assert nombres == [
        "Capital/617030004_2010-01_COLCHONES.pdf",
        "Cuprum/617030004_2010-01_COLCHONES.pdf",
    ]
    assert "checkpoint.json" not in nombres


def test_zip_retorna_bytes_io(directorio_con_pdfs):
    buffer = construir_zip(str(directorio_con_pdfs))
    assert isinstance(buffer, io.BytesIO)
    assert buffer.tell() == 0  # listo para leer


def test_zip_directorio_vacio(tmp_path):
    buffer = construir_zip(str(tmp_path))
    with zipfile.ZipFile(buffer) as zf:
        assert zf.namelist() == []
