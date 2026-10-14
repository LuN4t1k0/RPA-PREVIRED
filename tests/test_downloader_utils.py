from unittest.mock import MagicMock

import pytest

from bot.downloader import _click_ingresar_empresa, _ruta_salida_planilla
from models import Empresa


def _company_row(rut: str, name: str):
    row = MagicMock()
    cells = MagicMock()
    rut_cell = MagicMock()
    name_cell = MagicMock()
    rut_cell.inner_text.return_value = rut
    name_cell.inner_text.return_value = name
    cells.nth.side_effect = lambda index: {1: rut_cell, 2: name_cell}[index]
    row.locator.side_effect = lambda selector: {
        "td": cells,
        "button.ingresar": row.enter_button,
    }[selector]
    return row


def test_click_ingresar_empresa_acepta_rut_formateado_en_tabla():
    other = _company_row("11.111.111-1", "OTRA EMPRESA")
    target = _company_row("93.830.000-3", "COMPAÑIAS CIC S.A.")
    rows = MagicMock()
    rows.count.return_value = 2
    rows.nth.side_effect = [other, target]
    page = MagicMock()
    page.locator.return_value = rows

    _click_ingresar_empresa(
        page,
        Empresa(rut="93830000-3", nombre="COMPAÑIAS CIC S.A."),
    )

    target.enter_button.click.assert_called_once_with()
    other.enter_button.click.assert_not_called()


def test_click_ingresar_empresa_informa_rut_ausente():
    rows = MagicMock()
    rows.count.return_value = 0
    page = MagicMock()
    page.locator.return_value = rows

    with pytest.raises(RuntimeError, match="No se encontró la empresa"):
        _click_ingresar_empresa(page, Empresa(rut="93830000-3", nombre="EMPRESA"))


def test_ruta_salida_planilla_organiza_por_afp(tmp_path):
    output_dir, filename = _ruta_salida_planilla(
        str(tmp_path),
        "93.830.000-3",
        "2026-09",
        "REMUNERACIONES",
        "AFP Capital",
    )

    assert output_dir == str(tmp_path / "AFP_Capital")
    assert filename == "938300003_2026-09_REMUNERACIONES.pdf"


def test_ruta_salida_planilla_limpia_componentes_inseguros(tmp_path):
    output_dir, filename = _ruta_salida_planilla(
        str(tmp_path),
        "93.830.000-3",
        "2026-09",
        "NÓMINA/ESPECIAL",
        "AFP/Prueba",
    )

    assert output_dir == str(tmp_path / "AFP_Prueba")
    assert filename == "938300003_2026-09_N_MINA_ESPECIAL.pdf"
