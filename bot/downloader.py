import asyncio
import os
import queue
import threading
from playwright.async_api import Page

from checkpoint import Checkpoint
from models import BotMessage, Estado, Empresa, Nomina, Planilla

MESES = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


async def _navegar_a_planillas_pagadas(page: Page, empresa: Empresa):
    await page.goto("https://www.previred.com/wEmpresas/CtrlFce")
    await page.wait_for_load_state("networkidle")
    fila = page.locator("tr").filter(has=page.locator(f"td:has-text('{empresa.rut}')")).first
    await fila.locator("input[value='Ingresar']").click()
    await page.wait_for_load_state("networkidle")
    await page.click("input[value='Remuneraciones'], button:has-text('Remuneraciones')")
    await page.wait_for_load_state("networkidle")
    await page.click("text=Imprimir Documentos")
    await page.click("text=Planillas Pagadas")
    await page.wait_for_load_state("networkidle")


async def _buscar_planillas(page: Page, periodo: str, nomina: Nomina):
    año, mes = periodo.split("-")
    await page.select_option("select[name*='mes']", label=MESES[mes])
    await page.select_option("select[name*='anio']", value=año)
    await page.wait_for_timeout(500)
    await page.select_option("select[name*='nomina']", label=nomina.nombre)
    await page.select_option("select[name*='tipo']", label="AFP")
    await page.select_option("select[name*='institucion']", index=0)  # "Todas las Instituciones"
    await page.click("input[value='Buscar'], button:has-text('Buscar')")
    await page.wait_for_load_state("networkidle")


async def _descargar_pdf_institucion(
    page: Page,
    icono_pdf,
    output_dir: str,
    nombre_archivo: str,
) -> str:
    """
    Hace click en el icono PDF, selecciona 'Total Empresa', descarga el PDF.
    Retorna la ruta del archivo guardado.
    """
    async with page.context.expect_page() as popup_info:
        await icono_pdf.click()

    popup = await popup_info.value
    await popup.wait_for_load_state("networkidle")

    # En el modal: seleccionar "Total Empresa" y click Imprimir
    await popup.click("input[value='0']")  # radio "Total Empresa"
    async with popup.expect_download() as dl_info:
        await popup.click("input[value='Imprimir'], button:has-text('Imprimir')")

    download = await dl_info.value
    ruta = os.path.join(output_dir, nombre_archivo)
    await download.save_as(ruta)
    await popup.close()
    return ruta


async def descargar_empresa(
    page: Page,
    empresa: Empresa,
    output_base: str,
    checkpoint: Checkpoint,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    await _navegar_a_planillas_pagadas(page, empresa)

    for periodo, nominas in empresa.nominas_por_periodo.items():
        for nomina in nominas:
            if stop_event.is_set():
                return

            await _buscar_planillas(page, periodo, nomina)

            # Verificar si hay resultados
            sin_datos = await page.locator("text=No se encontraron planillas").count()
            if sin_datos > 0:
                planilla = Planilla(
                    rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                    institucion="AFP", folio="", estado=Estado.SIN_DATOS,
                )
                msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                continue

            # Obtener filas de resultados (una por institución AFP)
            iconos = page.locator("img[src*='pdf'], a[href*='CtrlPdf']")
            filas_inst = page.locator("table tr").filter(has=iconos)
            count = await filas_inst.count()

            for i in range(count):
                if stop_event.is_set():
                    return

                fila = filas_inst.nth(i)
                nombre_inst = (await fila.locator("td").first.inner_text()).strip()
                folio_el = fila.locator("td").nth(1)
                folio = (await folio_el.inner_text()).strip()

                if checkpoint.esta_completo(empresa.rut, periodo, nomina.slug, nombre_inst):
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OMITIDO,
                    )
                    msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                    continue

                output_dir = os.path.join(
                    output_base, empresa.rut.replace(".", "").replace("-", ""),
                    periodo, nomina.slug,
                )
                os.makedirs(output_dir, exist_ok=True)
                nombre_archivo = f"{nombre_inst.replace(' ', '_')}_{folio}.pdf"

                try:
                    icono = fila.locator("img[src*='pdf'], a[href*='CtrlPdf']").first
                    ruta = await _descargar_pdf_institucion(page, icono, output_dir, nombre_archivo)
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
