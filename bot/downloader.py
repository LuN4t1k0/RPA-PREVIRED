import os
import queue
import re
import threading
from playwright.sync_api import Page

from bot.discovery import _abrir_planillas_pagadas, _ir_a_lista_empresas
from checkpoint import Checkpoint
from models import BotMessage, Estado, Empresa, Nomina, Planilla
from rut import limpiar_rut

MESES = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


def _componente_ruta(value: str, fallback: str) -> str:
    """Convierte texto proveniente del portal en una carpeta segura y legible."""
    componente = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    return componente or fallback


def _ruta_salida_planilla(
    output_base: str,
    rut_empresa: str,
    periodo: str,
    nomina_slug: str,
    institucion: str,
) -> tuple[str, str]:
    """Deja cada PDF directamente en la carpeta de su AFP."""
    afp = _componente_ruta(institucion, "AFP")
    nomina = _componente_ruta(nomina_slug, "NOMINA")
    output_dir = os.path.join(output_base, afp)
    nombre_archivo = f"{limpiar_rut(rut_empresa)}_{periodo}_{nomina}.pdf"
    return output_dir, nombre_archivo


def _click_ingresar_empresa(page: Page, empresa: Empresa):
    """Hace clic en el botón Ingresar de la fila correcta, distinguiendo duplicados por nombre."""
    rut_buscado = limpiar_rut(empresa.rut)
    filas = page.locator("tr:has(button.ingresar)")
    coincidencias = []

    for i in range(filas.count()):
        candidate = filas.nth(i)
        rut_mostrado = candidate.locator("td").nth(1).inner_text().strip()
        rut_normalizado = limpiar_rut(rut_mostrado)
        if rut_normalizado == rut_buscado:
            coincidencias.append(candidate)

    if not coincidencias:
        raise RuntimeError(f"No se encontró la empresa con RUT {empresa.rut}.")

    fila = coincidencias[0]
    for candidate in coincidencias:
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
    _abrir_planillas_pagadas(page)
    page.wait_for_timeout(1000)


def _buscar_planillas(page: Page, periodo: str, nomina: Nomina):
    # Asegura que el formulario esté en estado limpio:
    # - caso normal: #mesR0 oculto → abrirlo
    # - caso roto (ISAPRE+AFP): #mesR0 visible pero botón Buscar desapareció
    #   → cerrar el panel (toggle) y volver a abrirlo para resetearlo
    if page.locator("#mesR0").count() == 0:
        _abrir_planillas_pagadas(page)
        page.wait_for_timeout(500)
    elif page.locator("button:has-text('Buscar')").count() == 0:
        # Formulario visible pero roto: ocultar pulsando el toggle y reabrir
        try:
            page.locator("span#ver_planillas_pagadas").click(timeout=3_000)
            page.wait_for_timeout(300)
        except Exception:
            pass
        _abrir_planillas_pagadas(page)
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
    # "Todas las Instituciones" puede no existir si el combo ya filtró por AFP
    opciones_inst = page.locator("#combo_instituciones option").all_inner_texts()
    if any("todas" in o.lower() for o in opciones_inst):
        page.select_option("#combo_instituciones", label=next(
            o for o in opciones_inst if "todas" in o.lower()
        ))
    page.click("button:has-text('Buscar')")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Auto-sanity: si el formulario quedó visible pero sin botón Buscar,
    # es señal de que esta nómina no tiene datos AFP (nómina ISAPRE u otro tipo).
    # Reseteamos el formulario aquí mismo para que la próxima búsqueda parta limpia.
    if (page.locator("#mesR0").count() > 0
            and page.locator("button:has-text('Buscar')").count() == 0):
        try:
            page.locator("span#ver_planillas_pagadas").click(timeout=3_000)
            page.wait_for_timeout(300)
        except Exception:
            pass
        _abrir_planillas_pagadas(page)
        page.wait_for_timeout(500)


def _descargar_pdf_institucion(page: Page, icono_pdf, output_dir: str, nombre_archivo: str) -> str:
    """
    Tres flujos según el tipo de empresa:
    - Flujo A: clic → descarga directa en page + pestaña vacía.
    - Flujo B: clic → popup window con radio buttons → Imprimir → descarga en popup.
    - Flujo C: clic → panel AJAX inline (#bus_cc/modalCC) → radio Total Empresa
               → button#aceptar_modal → window.open('/wEmpresas/CtrlPdf') → PDF inline
               (sin evento download). Se captura via page.context.route.
    """
    ruta = os.path.join(output_dir, nombre_archivo)
    downloads_main: list = []
    new_pages: list = []
    downloads_new_pages: list = []
    pdf_bytes_list: list[bytes] = []

    def on_download(dl):
        downloads_main.append(dl)

    def on_page(p):
        new_pages.append(p)
        p.on("download", lambda d: downloads_new_pages.append(d))

    def capture_pdf(route, request):
        if request.method != "GET":
            route.continue_()
            return
        try:
            response = route.fetch(timeout=30_000)
            body = response.body()
            content_type = response.headers.get("content-type", "").lower()
            if body.startswith(b"%PDF") or "application/pdf" in content_type:
                pdf_bytes_list.append(body)
            route.fulfill(response=response)
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    page.on("download", on_download)
    page.context.on("page", on_page)
    # Previred actualmente abre CtrlPdf directamente en una pestaña, sin evento
    # download ni botón Imprimir. Interceptar desde antes del clic permite
    # conservar el cuerpo PDF de ese nuevo flujo y también sirve para Flujo C.
    page.context.route("**/CtrlPdf**", capture_pdf)

    try:
        icono_pdf.click()
        page.wait_for_timeout(3000)

        if pdf_bytes_list:
            with open(ruta, "wb") as f:
                f.write(pdf_bytes_list[0])
            for p in new_pages:
                try:
                    p.close()
                except Exception:
                    pass
            return ruta

        elif downloads_main:
            # Flujo A: descarga directa en la página principal
            downloads_main[0].save_as(ruta)
            for p in new_pages:
                try:
                    p.close()
                except Exception:
                    pass
            return ruta

        elif new_pages:
            # Flujo B: popup window con radio buttons (window.open inmediato)
            popup = new_pages[-1]
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            radios = popup.locator("input[type='radio']")
            if radios.count() > 0:
                radios.first.click()
                popup.click("button:has-text('Imprimir')")
            elif "/CtrlPdf" not in popup.url:
                raise Exception("Flujo B: popup sin opciones ni botón Imprimir")
            for _ in range(30):
                if downloads_new_pages or downloads_main or pdf_bytes_list:
                    break
                page.wait_for_timeout(500)
            if pdf_bytes_list:
                with open(ruta, "wb") as f:
                    f.write(pdf_bytes_list[0])
                try:
                    popup.close()
                except Exception:
                    pass
                return ruta
            dl = (downloads_new_pages[0] if downloads_new_pages
                  else downloads_main[0] if downloads_main else None)
            if dl is None:
                raise Exception("Flujo B: sin descarga tras Imprimir en popup")
            dl.save_as(ruta)
            try:
                popup.close()
            except Exception:
                pass
            return ruta

        else:
            # Flujo C: panel AJAX inline — PDF servido inline en nueva ventana (sin download event)
            panel_btn = page.locator("button#aceptar_modal")
            if panel_btn.count() == 0 or not panel_btn.first.is_visible():
                raise Exception("No se detectó descarga, popup ni panel #aceptar_modal")

            total_empresa = page.locator("input[name='web_tipo_busqueda'][value='0']")
            if total_empresa.count() > 0:
                try:
                    total_empresa.first.click()
                except Exception:
                    pass
            panel_btn.first.click()
            # Esperar hasta 15s: AJAX POST + window.open + navegación + respuesta PDF
            for _ in range(30):
                if pdf_bytes_list:
                    break
                page.wait_for_timeout(500)

            for p in new_pages:
                try:
                    p.close()
                except Exception:
                    pass

            if not pdf_bytes_list:
                raise Exception("Flujo C: sin PDF capturado tras aceptar_modal")

            with open(ruta, "wb") as f:
                f.write(pdf_bytes_list[0])

            # Flujo C deja el panel #bus_cc visible, lo que puede bloquear "Buscar"
            # en la siguiente iteración. Lo ocultamos via JS como lo haría el portal.
            try:
                page.evaluate("""
                    var panel = document.getElementById('bus_cc');
                    if (panel) panel.style.display = 'none';
                    var modal = document.getElementById('modalCC');
                    if (modal) modal.style.display = 'none';
                """)
            except Exception:
                pass

            return ruta

    finally:
        try:
            page.context.unroute("**/CtrlPdf**", capture_pdf)
        except Exception:
            pass
        page.remove_listener("download", on_download)
        page.context.remove_listener("page", on_page)

    raise Exception("Sin descarga capturada")


def _recuperar_pagina(page: Page, empresa: Empresa):
    """
    Intenta restaurar la página al formulario de búsqueda de Planillas Pagadas.
    Cierra ventanas huérfanas y re-navega si es necesario.
    """
    # Cerrar cualquier ventana/pestaña extra que haya quedado abierta
    for ctx_page in page.context.pages:
        if ctx_page != page:
            try:
                ctx_page.close()
            except Exception:
                pass

    # Si ya estamos en el formulario, listo
    try:
        if page.locator("#mesR0").count() > 0:
            return
    except Exception:
        pass

    # Intentar abrir Planillas Pagadas desde el estado actual
    try:
        _abrir_planillas_pagadas(page)
        page.wait_for_timeout(500)
        if page.locator("#mesR0").count() > 0:
            return
    except Exception:
        pass

    # Último recurso: navegar de nuevo desde la lista de empresas
    _navegar_a_planillas_pagadas(page, empresa)


def descargar_empresa(
    page: Page,
    empresa: Empresa,
    output_base: str,
    checkpoint: Checkpoint,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    _navegar_a_planillas_pagadas(page, empresa)

    # Enviar plan completo para que la UI muestre ítems pendientes
    plan_items = [
        (periodo, nomina.nombre)
        for periodo, nominas in empresa.nominas_por_periodo.items()
        for nomina in nominas
    ]
    msg_queue.put(BotMessage(tipo="plan", datos={"items": plan_items}))

    for periodo, nominas in empresa.nominas_por_periodo.items():
        for nomina in nominas:
            if stop_event.is_set():
                return

            # Avisar qué nómina se está procesando ahora
            msg_queue.put(BotMessage(tipo="inicio_item", datos={
                "periodo": periodo,
                "nomina": nomina.nombre,
            }))

            # Intentar la búsqueda; si falla, recuperar la página y reintentar una vez
            try:
                _buscar_planillas(page, periodo, nomina)
            except Exception as e_buscar:
                msg_queue.put(BotMessage(tipo="status", datos={
                    "msg": f"⚠️ Error buscando {periodo}/{nomina.nombre}: {e_buscar}. Recuperando…"
                }))
                try:
                    _recuperar_pagina(page, empresa)
                    _buscar_planillas(page, periodo, nomina)
                except Exception as e_retry:
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion="AFP", folio="", estado=Estado.ERROR,
                        error_msg=f"Buscar falló tras recuperación: {e_retry}",
                    )
                    msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                    continue

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

                output_dir, nombre_archivo = _ruta_salida_planilla(
                    output_base,
                    empresa.rut,
                    periodo,
                    nomina.slug,
                    nombre_inst,
                )
                os.makedirs(output_dir, exist_ok=True)

                try:
                    ruta = _descargar_pdf_institucion(page, icono, output_dir, nombre_archivo)
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OK,
                        ruta_archivo=ruta,
                        tamaño_bytes=os.path.getsize(ruta),
                    )
                    checkpoint.marcar(planilla)
                except Exception as e:
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.ERROR,
                        error_msg=str(e),
                    )

                msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
