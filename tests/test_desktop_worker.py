from desktop_backend.worker import planilla_payload, selected_empresa, serialize_nominas
from models import Empresa, Estado, Nomina, Planilla


def test_selected_empresa_filtra_solo_nominas_elegidas():
    empresa = Empresa(rut="76.123.456-7", nombre="Empresa Demo")
    empresa.nominas_por_periodo = {
        "2026-01": [Nomina(nombre="Nomina A", slug="A"), Nomina(nombre="Nomina B", slug="B")],
        "2026-02": [Nomina(nombre="Nomina C", slug="C")],
    }

    result = selected_empresa(empresa, [{"periodo": "2026-01", "slug": "B"}])

    assert list(result.nominas_por_periodo) == ["2026-01"]
    assert [item.slug for item in result.nominas_por_periodo["2026-01"]] == ["B"]
    assert [item.slug for item in empresa.nominas_por_periodo["2026-01"]] == ["A", "B"]


def test_serialize_nominas_expone_contrato_del_renderer():
    empresa = Empresa(rut="1-9", nombre="Demo")
    empresa.nominas_por_periodo = {"2026-03": [Nomina(nombre="Mensual", slug="MENSUAL")]}

    assert serialize_nominas(empresa) == [
        {"periodo": "2026-03", "nominas": [{"nombre": "Mensual", "slug": "MENSUAL"}]}
    ]


def test_planilla_payload_convierte_enum_a_json():
    planilla = Planilla(
        rut_empresa="1-9",
        periodo="2026-03",
        nomina="MENSUAL",
        institucion="AFP Demo",
        folio="123",
        estado=Estado.OK,
        tamaño_bytes=2048,
    )

    payload = planilla_payload(planilla)

    assert payload["estado"] == "OK"
    assert payload["tamaño_bytes"] == 2048
