from bot.discovery import _periodos_en_rango, _slug


def test_periodos_en_rango_mismo_mes():
    assert _periodos_en_rango("2024-12", "2024-12") == ["2024-12"]


def test_periodos_en_rango_cruce_año():
    result = _periodos_en_rango("2024-11", "2025-02")
    assert result == ["2024-11", "2024-12", "2025-01", "2025-02"]


def test_slug():
    assert _slug("COLCHONES LQ ENE2010") == "COLCHONES_LQ_ENE2010"
    assert _slug("AFP-Capital (2)") == "AFP_CAPITAL_2"
