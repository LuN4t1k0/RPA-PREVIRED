import asyncio
import queue
import re
import threading
from playwright.async_api import Page

from models import BotMessage, Empresa, Nomina


def _periodos_en_rango(desde: str, hasta: str) -> list[str]:
    """Genera lista ['yyyy-mm', ...] entre desde y hasta inclusive."""
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


async def obtener_empresas(page: Page) -> list[Empresa]:
    """Extrae lista de empresas desde Administrador de Empresas.

    NOTE: Selectors are best-guess estimates pending manual verification against
    https://www.previred.com/wEmpresas/CtrlFce (requires credentials).
    Verified login selectors are in bot/login.py.
    """
    await page.goto("https://www.previred.com/wEmpresas/CtrlFce")
    await page.wait_for_load_state("networkidle")

    empresas = []
    filas = page.locator("table tr").filter(has=page.locator("input[value='Ingresar']"))
    count = await filas.count()

    for i in range(count):
        fila = filas.nth(i)
        celdas = fila.locator("td")
        rut = (await celdas.nth(0).inner_text()).strip()
        nombre = (await celdas.nth(1).inner_text()).strip()
        empresas.append(Empresa(rut=rut, nombre=nombre))

    return empresas


async def obtener_nominas_empresa(
    page: Page,
    empresa: Empresa,
    desde: str,
    hasta: str,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    """Para una empresa, navega a Planillas Pagadas y descubre las nóminas
    disponibles por período. Escribe resultados en empresa.nominas_por_periodo.

    NOTE: Selectors for Remuneraciones nav, month/year selects, and nomina
    select are best-guess estimates pending manual verification against the
    live Previred portal (requires credentials).
    """
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

    meses = {
        "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
        "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
        "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
    }

    for periodo in _periodos_en_rango(desde, hasta):
        if stop_event.is_set():
            return

        año, mes = periodo.split("-")
        await page.select_option("select[name*='mes'], select:near(:text('Período'))", label=meses[mes])
        await page.select_option("select[name*='anio'], select[name*='año']", value=año)
        await page.wait_for_timeout(500)

        opciones = await page.locator("select[name*='nomina'] option").all_inner_texts()
        nominas = [
            Nomina(nombre=o.strip(), slug=_slug(o.strip()))
            for o in opciones
            if o.strip() and "seleccione" not in o.lower()
        ]

        if nominas:
            empresa.nominas_por_periodo[periodo] = nominas

    msg_queue.put(BotMessage(tipo="progreso_empresa", datos={"empresa": empresa.nombre}))


async def descubrir_todo(
    page: Page,
    empresas: list[Empresa],
    desde: str,
    hasta: str,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    """Recorre todas las empresas descubriendo nóminas en el rango dado."""
    for empresa in empresas:
        if stop_event.is_set():
            return
        await obtener_nominas_empresa(page, empresa, desde, hasta, msg_queue, stop_event)

    msg_queue.put(BotMessage(tipo="fin_discovery", datos={"total": len(empresas)}))
