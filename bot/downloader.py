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


def _click_ingresar_empresa(page: Page, empresa: Empresa):
    """Hace clic en el botón Ingresar de la fila correcta, distinguiendo duplicados por nombre."""
    filas = page.locator("tr:has(button.ingresar)").filter(
        has=page.locator(f"td:has-text('{empresa.rut}')")
    )
    fila = filas.first
    for i in range(filas.count()):
        candidate = filas.nth(i)
        if candidate.locator("td").nth(2).inner_text().strip() == empresa.nombre:
            fila = candidate
            break
    fila.locator("button.ingresar").click()


def _navegar_a_planillas_pagadas(page: Page, empresa: Empresa):
    _ir_a_lista_empresas(page)
    _click_ingresar_empresa(page, empresa)
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
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)
    page.select_option("#yearR0", value=año)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.select_option("#combo_nominas", label=nomina.nombre)
    page.select_option("#combo_tipo_institucion", label="AFP")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)
    page.select_option("#combo_instituciones", label="Todas las Instituciones")
    page.click("button:has-text('Buscar')")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def _descargar_pdf_institucion(page: Page, icono_pdf, output_dir: str, nombre_archivo: str) -> str:
    """
    Maneja dos flujos:
    - Flujo A: clic → descarga directa en page + pestaña vacía (cerrar y guardar).
    - Flujo B: clic → popup con radio buttons → seleccionar Total Empresa → Imprimir → descarga en popup.
    """
    new_pages: list = []
    page_handler = lambda p: new_pages.append(p)
    page.context.on("page", page_handler)

    download = None
    try:
        try:
            with page.expect_download(timeout=5000) as dl_info:
                icono_pdf.click()
                page.wait_for_timeout(2000)
            download = dl_info.value
            # Flujo A: cerrar la pestaña vacía que abrió
            for p in new_pages:
                try:
                    p.close()
                except Exception:
                    pass
        except Exception:
            # Flujo B: el clic abrió un popup con formulario (sin descarga directa en page)
            page.wait_for_timeout(1000)
            if not new_pages:
                raise Exception("No ocurrió descarga directa ni se abrió popup")
            popup = new_pages[-1]
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            with popup.expect_download(timeout=15000) as dl_info:
                radios = popup.locator("input[type='radio']")
                if radios.count() > 0:
                    radios.first.click()
                popup.click("button:has-text('Imprimir')")
            download = dl_info.value
            try:
                popup.close()
            except Exception:
                pass
    finally:
        page.context.remove_listener("page", page_handler)

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
