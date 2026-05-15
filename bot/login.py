from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright


def abrir_sesion(rut: str, password: str) -> tuple[Playwright, Browser, BrowserContext, Page]:
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()

    page.goto("https://www.previred.com/wPortal/login/login.jsp")
    page.wait_for_load_state("networkidle")

    page.fill("input#web_rut2", rut)
    page.fill("input#web_password", password)
    page.click("button#login")

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
