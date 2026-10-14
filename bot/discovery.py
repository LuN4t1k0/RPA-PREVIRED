import queue
import re
import threading
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from models import BotMessage, Empresa, Nomina
from rut import limpiar_rut


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


# Palabras clave que identifican nóminas que NO son AFP
# (ISAPRE, CCAF, Mutuales, FONASA/IPS, etc.)
_NO_AFP_KEYWORDS = frozenset([
    "isap",        # ISAPRE, Isape, Isapre Consalud…
    "consalud",    # Consalud
    "banmedic",    # Banmédica
    "colmena",     # Colmena Golden Cross
    "fonasa",      # FONASA
    " ips",        # IPS (con espacio para no capturar "Imposiciones")
    "ccaf",        # Cajas de Compensación
    "mutual",      # Mutuales (IST, ACHS, etc.)
    "vida tres",   # Vida Tres
    "masvida",     # Masvida
    "cruz blanca", # Cruz Blanca
])


def _es_nomina_afp(nombre: str) -> bool:
    """Devuelve True si el nombre de la nómina corresponde a AFP (no ISAPRE/CCAF/etc.)."""
    n = nombre.lower()
    return not any(kw in n for kw in _NO_AFP_KEYWORDS)


def _status(msg_queue: queue.Queue, texto: str):
    msg_queue.put(BotMessage(tipo="status", datos={"msg": texto}))


def _ir_a_lista_empresas(page: Page):
    """Navega al listado de empresas desde cualquier estado del portal."""
    # Ya estamos en la lista
    if page.locator("tr:has(button.ingresar)").count() > 0:
        return

    # Dentro de wEmpresas existe un acceso directo al listado. Usarlo evita
    # volver al portal principal, donde li#empresa puede renderizar tarde o no
    # aparecer si la sesión conserva el contexto de la empresa.
    if "wEmpresas" in page.url:
        listado = page.locator("span#listado_empresas")
        if listado.count() > 0:
            if listado.first.is_visible():
                try:
                    listado.first.click(timeout=5_000)
                except Exception:
                    listado.first.evaluate("element => element.click()")
            else:
                listado.first.evaluate("element => element.click()")
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("tr:has(button.ingresar)", timeout=20_000)
            return

    # Fallback desde otras pantallas: volver al portal vía Inicio.
    if "wPortal" not in page.url:
        page.locator("a:has-text('Inicio')").first.click()
        page.wait_for_url("**/wPortal/**", timeout=20_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)  # El portal renderiza li#empresa un momento después de networkidle

    # Desde el portal, usar el acceso visual cuando esté disponible. En
    # algunas sesiones de Windows ese menú no se renderiza, aunque la sesión
    # autenticada sí permite abrir directamente el Administrador de Empresas.
    try:
        page.wait_for_selector("li#empresa", state="visible", timeout=8_000)
        page.click("li#empresa")
        page.wait_for_url("**/wEmpresas/**", timeout=20_000)
    except PlaywrightTimeoutError:
        page.goto("https://www.previred.com/wEmpresas/CtrlFce")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("tr:has(button.ingresar)", timeout=20_000)


def _abrir_planillas_pagadas(page: Page):
    """Abre Planillas Pagadas aunque el overlay lateral intercepte clicks reales."""
    link = page.locator("span#ver_planillas_pagadas")
    link.wait_for(state="visible", timeout=20_000)
    try:
        link.click(timeout=5_000)
    except Exception:
        link.evaluate("element => element.click()")
    page.wait_for_load_state("networkidle")


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

    rut_buscado = limpiar_rut(empresa.rut)
    filas = page.locator("tr:has(button.ingresar)")
    coincidencias = []
    for i in range(filas.count()):
        candidate = filas.nth(i)
        rut_mostrado = candidate.locator("td").nth(1).inner_text().strip()
        if limpiar_rut(rut_mostrado) == rut_buscado:
            coincidencias.append(candidate)

    if not coincidencias:
        raise RuntimeError(f"No se encontró la empresa con RUT {empresa.rut}.")

    fila = coincidencias[0]
    for candidate in coincidencias:
        if candidate.locator("td").nth(2).inner_text().strip() == empresa.nombre:
            fila = candidate
            break
    fila.locator("button.ingresar").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    _status(msg_queue, f"{empresa.nombre} → Remuneraciones → Planillas Pagadas")
    page.click("#tipoPago a:has-text('Remuneraciones')")
    page.wait_for_load_state("networkidle")
    page.click("text=Imprimir Documentos")
    page.wait_for_timeout(500)
    _abrir_planillas_pagadas(page)
    page.wait_for_timeout(1000)

    periodos = _periodos_en_rango(desde, hasta)
    for idx, periodo in enumerate(periodos, 1):
        if stop_event.is_set():
            return

        _status(msg_queue, f"{empresa.nombre} — buscando {periodo} ({idx}/{len(periodos)})")
        # Si el formulario quedó oculto (ej. tras una búsqueda previa), restaurarlo
        if page.locator("#mesR0").count() == 0:
            _abrir_planillas_pagadas(page)
            page.wait_for_timeout(500)
        año, mes = periodo.split("-")
        # Esperar el AJAX de mes antes de cambiar el año para evitar condición de carrera
        try:
            page.select_option("#mesR0", label=meses[mes])
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
            page.select_option("#yearR0", value=año)
        except Exception:
            continue  # Año no disponible en el select → sin planillas para este periodo
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        nomina_select = page.locator("#combo_nominas")
        opciones = nomina_select.locator("option").all_inner_texts()
        nominas = [
            Nomina(nombre=o.strip(), slug=_slug(o.strip()))
            for o in opciones
            if o.strip() and "seleccione" not in o.lower() and _es_nomina_afp(o.strip())
        ]

        if nominas:
            empresa.nominas_por_periodo[periodo] = nominas

    msg_queue.put(BotMessage(tipo="progreso_empresa", datos={"empresa": empresa.nombre}))
