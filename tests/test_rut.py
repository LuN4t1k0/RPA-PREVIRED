import pytest

import bot.login
from rut import es_rut_valido, formatear_rut, limpiar_rut, normalizar_rut, validar_rut


@pytest.mark.parametrize(
    ("entrada", "normalizado", "formateado"),
    [
        ("156440213", "15644021-3", "15.644.021-3"),
        ("15.644.021-3", "15644021-3", "15.644.021-3"),
        (" 15 644 021 k ", "15644021-K", "15.644.021-K"),
    ],
)
def test_normaliza_y_formatea_rut(entrada, normalizado, formateado):
    assert normalizar_rut(entrada) == normalizado
    assert formatear_rut(entrada) == formateado


@pytest.mark.parametrize("rut", ["15.644.021-3", "12.345.678-5", "6-K"])
def test_valida_digito_verificador(rut):
    assert es_rut_valido(rut)
    assert validar_rut(rut) == normalizar_rut(rut)


@pytest.mark.parametrize("rut", ["", "123", "12.345.678-9", "ABC", "0-0"])
def test_rechaza_rut_invalido(rut):
    assert not es_rut_valido(rut)
    with pytest.raises(ValueError, match="RUT inválido"):
        validar_rut(rut)


def test_limpiar_rut_solo_acepta_separadores_conocidos():
    assert limpiar_rut("12.345.678-5") == "123456785"
    with pytest.raises(ValueError, match="RUT inválido"):
        limpiar_rut("12/345/678/5")


def test_login_rechaza_rut_invalido_antes_de_abrir_el_navegador(monkeypatch):
    playwright_iniciado = False

    def iniciar_playwright():
        nonlocal playwright_iniciado
        playwright_iniciado = True
        raise AssertionError("No debe iniciar Playwright con un RUT inválido")

    monkeypatch.setattr(bot.login, "sync_playwright", iniciar_playwright)

    with pytest.raises(ValueError, match="RUT inválido"):
        bot.login.abrir_sesion("12.345.678-9", "secreto")

    assert not playwright_iniciado
