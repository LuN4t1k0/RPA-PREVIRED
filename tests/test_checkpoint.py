import json
import os
import tempfile
import pytest
from models import Estado, Planilla
from checkpoint import Checkpoint


@pytest.fixture
def tmp_checkpoint(tmp_path):
    return Checkpoint(path=str(tmp_path / "checkpoint.json"))


def test_checkpoint_empty_on_start(tmp_checkpoint):
    assert tmp_checkpoint.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is False


def test_checkpoint_marcar_ok(tmp_checkpoint):
    tmp_checkpoint.marcar(
        Planilla(
            rut_empresa="61703000-4", periodo="2010-01", nomina="NOM",
            institucion="AFP Capital", folio="123", estado=Estado.OK,
        )
    )
    assert tmp_checkpoint.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is True


def test_checkpoint_no_marca_errores(tmp_checkpoint):
    tmp_checkpoint.marcar(
        Planilla(
            rut_empresa="61703000-4", periodo="2010-01", nomina="NOM",
            institucion="AFP Capital", folio="123", estado=Estado.ERROR,
        )
    )
    assert tmp_checkpoint.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is False


def test_checkpoint_persiste_en_disco(tmp_path):
    path = str(tmp_path / "checkpoint.json")
    c1 = Checkpoint(path=path)
    c1.marcar(
        Planilla(
            rut_empresa="61703000-4", periodo="2010-01", nomina="NOM",
            institucion="AFP Capital", folio="123", estado=Estado.OK,
        )
    )
    c2 = Checkpoint(path=path)
    assert c2.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is True
