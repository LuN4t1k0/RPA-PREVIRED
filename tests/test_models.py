from models import Estado, Nomina, Empresa, Planilla, BotMessage

def test_estado_values():
    assert Estado.OK == "OK"
    assert Estado.SIN_DATOS == "SIN_DATOS"
    assert Estado.ERROR == "ERROR"
    assert Estado.OMITIDO == "OMITIDO"

def test_nomina_slug():
    n = Nomina(nombre="COLCHONES LQ ENE2010", slug="COLCHONES_LQ_ENE2010")
    assert n.slug == "COLCHONES_LQ_ENE2010"

def test_empresa_defaults():
    e = Empresa(rut="61.703.000-4", nombre="Empresa Nacional de Minería")
    assert e.nominas_por_periodo == {}

def test_planilla_estado_default():
    p = Planilla(
        rut_empresa="61.703.000-4",
        periodo="2010-01",
        nomina="COLCHONES_LQ_ENE2010",
        institucion="AFP Capital",
        folio="2008201001341342",
        estado=Estado.OK,
    )
    assert p.ruta_archivo is None
    assert p.error_msg is None

def test_bot_message_defaults():
    m = BotMessage(tipo="progreso")
    assert m.datos == {}
