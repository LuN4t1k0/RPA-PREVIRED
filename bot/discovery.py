import queue
import re
import threading
from playwright.sync_api import Page

from models import BotMessage, Empresa, Nomina


def _periodos_en_rango(desde: str, hasta: str) -> list[str]:
    año_d, mes_d = map(int, desde.split("-"))
    año_h, mes_h = map(int, hasta.split("-"))
    periodos = []
    año, mes = año_d, mes_d
    while (año, mes) <= (año_h, mes_h):
        periodos.append(f"{año:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            mes = 1
            año += 1
    return periodos


def _slug(nombre: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", nombre.upper()).strip("_")


def _status(msg_queue: queue.Queue, texto: str):
    msg_queue.put(BotMessage(tipo="status", datos={"msg": texto}))


def _ir_a_lista_empresas(page: Page):
    """Navega al listado de empresas desde cualquier estado del portal."""
    # Ya estamos en la lista
    if page.locator("tr:has(button.ingresar)").count() > 0:
        return

    # Si estamos dentro de wEmpresas (empresa dashboard o planillas), volver al portal via Inicio
    if "wPortal" not in page.url:
        page.locator("a:has-text('Inicio')").first.click()
        page.wait_for_url("**/wPortal/**", timeout=15_000)
        page.wait_for_load_state("networkidle")

    # Desde el portal, ir a la lista de empresas
    page.wait_for_selector("li#empresa", state="visible", timeout=10_000)
    page.click("li#empresa")
    page.wait_for_url("**/wEmpresas/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("tr:has(button.ingresar)", timeout=15_000)


def obtener_empresas(page: Page) -> list[Empresa]:
    """Extrae lista de empresas desde el Administrador de Empresas."""
    _ir_a_lista_empresas(page)

    empresas = []
    filas = page.locator("tr:has(button.ingresar)")
    count = filas.count()

    for i in range(count):
        fila = filas.nth(i)
        celdas = fila.locator("td")
        rut = celdas.nth(1).inner_text().strip()
        nombre = celdas.nth(2).inner_text().strip()
        if rut:
            empresas.append(Empresa(rut=rut, nombre=nombre))

    return empresas


def obtener_nominas_empresa(
    page: Page,
    empresa: Empresa,
    desde: str,
    hasta: str,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    meses = {
        "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
        "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
        "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
    }

    _status(msg_queue, f"Navegando a {empresa.nombre}...")
    _ir_a_lista_empresas(page)

    fila = page.locator("tr:has(button.ingresar)").filter(
        has=page.locator(f"td:has-text('{empresa.rut}')")
    ).first
    fila.locator("button.ingresar").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    _status(msg_queue, f"{empresa.nombre} → Remuneraciones → Planillas Pagadas")
    page.click("#tipoPago a:has-text('Remuneraciones')")
    page.wait_for_load_state("networkidle")
    page.click("text=Imprimir Documentos")
    page.wait_for_timeout(500)
    page.click("span#ver_planillas_pagadas")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    periodos = _periodos_en_rango(desde, hasta)
    for idx, periodo in enumerate(periodos, 1):
        if stop_event.is_set():
            return

        _status(msg_queue, f"{empresa.nombre} — buscando {periodo} ({idx}/{len(periodos)})")
        año, mes = periodo.split("-")
        page.select_option("#mesR0", label=meses[mes])
        page.select_option("#yearR0", value=año)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        nomina_select = page.locator("select").nth(2)
        opciones = nomina_select.locator("option").all_inner_texts()
        nominas = [
            Nomina(nombre=o.strip(), slug=_slug(o.strip()))
            for o in opciones
            if o.strip() and "seleccione" not in o.lower()
        ]

        if nominas:
            empresa.nominas_por_periodo[periodo] = nominas

    msg_queue.put(BotMessage(tipo="progreso_empresa", datos={"empresa": empresa.nombre}))
