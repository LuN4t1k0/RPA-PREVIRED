from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

from rut import validar_rut


def _cerrar_dialogs(page: Page) -> None:
    """Descarta cualquier modal jQuery UI visible para que no bloquee el formulario."""
    overlay = page.locator(".ui-widget-overlay")
    if overlay.count() == 0 or not overlay.first.is_visible():
        return
    # Intentar cerrar por el botón X del diálogo
    close_btn = page.locator(".ui-dialog-titlebar-close")
    if close_btn.count() > 0 and close_btn.first.is_visible():
        close_btn.first.click()
        page.wait_for_timeout(500)
        return
    # Intentar cualquier botón de tipo "Cerrar", "Aceptar", "OK" dentro de un diálogo
    for label in ("Cerrar", "Aceptar", "OK", "Close", "Accept"):
        btn = page.locator(f".ui-dialog button:has-text('{label}')")
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(500)
            return
    # Último recurso: Escape
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


def abrir_sesion(rut: str, password: str) -> tuple[Playwright, Browser, BrowserContext, Page]:
    rut_normalizado = validar_rut(rut)
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()

    page.goto("https://www.previred.com/wPortal/login/login.jsp")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # Cerrar cualquier modal/overlay que bloquee el formulario (aviso, términos, etc.)
    _cerrar_dialogs(page)

    page.fill("input#web_rut2", rut_normalizado)
    page.fill("input#web_password", password)

    # Verificar de nuevo que no haya overlay antes de hacer click
    _cerrar_dialogs(page)
    try:
        page.click("button#login", timeout=10_000)
    except Exception:
        # Fallback: click vía JS, ignorando excepción si el click dispara navegación
        try:
            page.evaluate("document.querySelector('button#login').click()")
        except Exception:
            pass

    try:
        page.wait_for_url("**/wPortal/**", timeout=15_000)
        if "login.jsp" in page.url:
            raise Exception("Redirigido de vuelta al login")
    except Exception:
        browser.close()
        pw.stop()
        raise ValueError("Login fallido: verifica RUT y contraseña")

    return pw, browser, context, page


def cerrar_sesion(pw: Playwright, browser: Browser):
    browser.close()
    pw.stop()
