import io
import os
import zipfile
import tempfile
import pytest
from zip_builder import construir_zip


@pytest.fixture
def directorio_con_pdfs(tmp_path):
    (tmp_path / "61703000-4" / "2010-01" / "COLCHONES").mkdir(parents=True)
    (tmp_path / "61703000-4" / "2010-01" / "COLCHONES" / "AFP_Capital_123.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "61703000-4" / "2010-01" / "COLCHONES" / "AFP_Cuprum_456.pdf").write_bytes(b"%PDF-1.4 fake2")
    return tmp_path


def test_zip_contiene_archivos(directorio_con_pdfs):
    buffer = construir_zip(str(directorio_con_pdfs))
    with zipfile.ZipFile(buffer) as zf:
        nombres = zf.namelist()
    assert "61703000-4/2010-01/COLCHONES/AFP_Capital_123.pdf" in nombres
    assert "61703000-4/2010-01/COLCHONES/AFP_Cuprum_456.pdf" in nombres


def test_zip_retorna_bytes_io(directorio_con_pdfs):
    buffer = construir_zip(str(directorio_con_pdfs))
    assert isinstance(buffer, io.BytesIO)
    assert buffer.tell() == 0  # listo para leer


def test_zip_directorio_vacio(tmp_path):
    buffer = construir_zip(str(tmp_path))
    with zipfile.ZipFile(buffer) as zf:
        assert zf.namelist() == []
