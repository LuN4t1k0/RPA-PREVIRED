import os
import queue
import threading
from playwright.sync_api import Page

from bot.discovery import _ir_a_lista_empresas
from checkpoint import Checkpoint
from models import BotMessage, Estado, Empresa, Nomina, Planilla

MESES = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


def _navegar_a_planillas_pagadas(page: Page, empresa: Empresa):
    _ir_a_lista_empresas(page)
    fila = page.locator("tr:has(button.ingresar)").filter(
        has=page.locator(f"td:has-text('{empresa.rut}')")
    ).first
    fila.locator("button.ingresar").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.click("#tipoPago a:has-text('Remuneraciones')")
    page.wait_for_load_state("networkidle")
    page.click("text=Imprimir Documentos")
    page.wait_for_timeout(500)
    page.click("span#ver_planillas_pagadas")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)


def _buscar_planillas(page: Page, periodo: str, nomina: Nomina):
    # Asegura que el formulario de búsqueda esté visible (se oculta tras cada Buscar)
    if page.locator("#mesR0").count() == 0:
        page.click("span#ver_planillas_pagadas")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
    año, mes = periodo.split("-")
    page.select_option("#mesR0", label=MESES[mes])
    page.select_option("#yearR0", value=año)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.locator("select").nth(2).select_option(label=nomina.nombre)
    page.select_option("#combo_tipo_institucion", label="AFP")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)
    page.select_option("#combo_instituciones", label="Todas las Instituciones")
    page.click("button:has-text('Buscar')")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def _descargar_pdf_institucion(page: Page, icono_pdf, output_dir: str, nombre_archivo: str) -> str:
    # El click abre una pestaña vacía y dispara la descarga; cerramos la pestaña extra.
    with page.context.expect_page() as blank_info:
        with page.expect_download() as dl_info:
            icono_pdf.click()
    try:
        blank_info.value.close()
    except Exception:
        pass
    download = dl_info.value
    ruta = os.path.join(output_dir, nombre_archivo)
    download.save_as(ruta)
    return ruta


def descargar_empresa(
    page: Page,
    empresa: Empresa,
    output_base: str,
    checkpoint: Checkpoint,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    _navegar_a_planillas_pagadas(page, empresa)

    for periodo, nominas in empresa.nominas_por_periodo.items():
        for nomina in nominas:
            if stop_event.is_set():
                return

            _buscar_planillas(page, periodo, nomina)

            sin_datos = page.locator("text=No se encontraron planillas").count()
            if sin_datos > 0:
                planilla = Planilla(
                    rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                    institucion="AFP", folio="", estado=Estado.SIN_DATOS,
                )
                msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                continue

            # Expandir filas colapsadas para que los íconos sean clickeables
            for expand in page.locator("a[id^='oculta_nomina']").all():
                expand.click()
                page.wait_for_timeout(300)

            # El id del img tiene formato planilla_individual#{folio}#{idx}#{token}#{institucion}
            iconos = page.locator("img[src*='planillas.gif']")
            count = iconos.count()

            for i in range(count):
                if stop_event.is_set():
                    return

                icono = iconos.nth(i)
                img_id = icono.get_attribute("id") or ""
                partes = img_id.split("#")
                folio = partes[1] if len(partes) > 1 else ""
                nombre_inst = partes[-1] if partes else ""

                if checkpoint.esta_completo(empresa.rut, periodo, nomina.slug, nombre_inst):
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OMITIDO,
                    )
                    msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                    continue

                rut_clean = empresa.rut.replace(".", "").replace("-", "")
                output_dir = os.path.join(output_base, periodo, nomina.slug)
                os.makedirs(output_dir, exist_ok=True)
                nombre_archivo = f"{rut_clean}_{nombre_inst.replace(' ', '_')}_{periodo}.pdf"

                try:
                    ruta = _descargar_pdf_institucion(page, icono, output_dir, nombre_archivo)
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OK,
                        ruta_archivo=ruta,
                    )
                    checkpoint.marcar(planilla)
                except Exception as e:
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.ERROR,
                        error_msg=str(e),
                    )

                msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
