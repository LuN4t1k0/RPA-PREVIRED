from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


async def abrir_sesion(rut: str, password: str) -> tuple[Playwright, Browser, BrowserContext, Page]:
    """
    Abre Chromium headless, navega a Previred y hace login.
    Retorna (playwright, browser, context, page) — el llamador debe cerrarlos.
    Lanza ValueError si el login falla.

    Selectors verificados contra https://www.previred.com/wPortal/login/login.jsp:
      - RUT:      input#web_rut2   (text, class "form-control jKP_rut")
      - Clave:    input#web_password  (password)
      - Submit:   button#login     (type=submit, text "INGRESAR")
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()

    # Navegar directo al formulario de login (el enlace "INGRESAR AQUÍ" apunta aquí)
    await page.goto("https://www.previred.com/wPortal/login/login.jsp")
    await page.wait_for_load_state("networkidle")

    # El campo RUT usa la clase jKP_rut que puede auto-formatear (puntos y guión).
    # Se usa fill() para poblar el valor crudo; el JS del sitio maneja el formato.
    await page.fill("input#web_rut2", rut)
    await page.fill("input#web_password", password)
    await page.click("button#login")

    try:
        await page.wait_for_url("**/wPortal/**", timeout=15_000)
        # Verificar que no regresamos a la página de login (indicaría credenciales incorrectas)
        if "login.jsp" in page.url:
            raise Exception("Redirigido de vuelta al login")
    except Exception:
        await browser.close()
        await pw.stop()
        raise ValueError("Login fallido: verifica RUT y contraseña")

    return pw, browser, context, page


async def cerrar_sesion(pw: Playwright, browser: Browser):
    await browser.close()
    await pw.stop()
