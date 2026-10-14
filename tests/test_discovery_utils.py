from unittest.mock import MagicMock

from bot.discovery import _ir_a_lista_empresas, _periodos_en_rango, _slug


def test_periodos_en_rango_mismo_mes():
    assert _periodos_en_rango("2024-12", "2024-12") == ["2024-12"]


def test_periodos_en_rango_cruce_año():
    result = _periodos_en_rango("2024-11", "2025-02")
    assert result == ["2024-11", "2024-12", "2025-01", "2025-02"]


def test_slug():
    assert _slug("COLCHONES LQ ENE2010") == "COLCHONES_LQ_ENE2010"
    assert _slug("AFP-Capital (2)") == "AFP_CAPITAL_2"


def test_ir_a_lista_empresas_usa_acceso_directo_desde_empresa():
    page = MagicMock()
    page.url = "https://www.previred.com/wEmpresas/CtrlFce"

    rows = MagicMock()
    rows.count.return_value = 0
    listado = MagicMock()
    listado.count.return_value = 1
    link = MagicMock()
    link.is_visible.return_value = False
    listado.first = link

    page.locator.side_effect = lambda selector: {
        "tr:has(button.ingresar)": rows,
        "span#listado_empresas": listado,
    }[selector]

    _ir_a_lista_empresas(page)

    link.click.assert_not_called()
    link.evaluate.assert_called_once_with("element => element.click()")
    page.wait_for_selector.assert_called_once_with(
        "tr:has(button.ingresar)", timeout=20_000
    )
    page.wait_for_url.assert_not_called()
