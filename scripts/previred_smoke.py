"""Docker-friendly smoke test for the live Previred navigation flow.

Credentials are read from environment variables or requested interactively. They
are never written to artifacts. On failure, the script stores a screenshot, the
current DOM and a Playwright trace under the configured artifacts directory.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import traceback
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.discovery import _ir_a_lista_empresas, obtener_empresas, obtener_nominas_empresa
from bot.login import _cerrar_dialogs
from models import BotMessage, Empresa


LOGIN_URL = "https://www.previred.com/wPortal/login/login.jsp"


class ConsoleBridge:
    def put(self, message: BotMessage) -> None:
        if message.tipo == "status":
            print(f"[status] {message.datos.get('msg', '')}", flush=True)


class NeverStop:
    @staticmethod
    def is_set() -> bool:
        return False


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-only", action="store_true", help="Validate only the public login page.")
    parser.add_argument("--artifacts", default="/artifacts")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--company-rut", default=os.environ.get("PREVIRED_COMPANY_RUT", ""))
    parser.add_argument("--desde", default=os.environ.get("PREVIRED_DESDE", ""))
    parser.add_argument("--hasta", default=os.environ.get("PREVIRED_HASTA", ""))
    return parser.parse_args()


def require_visible(page: Page, selector: str, label: str) -> None:
    locator = page.locator(selector)
    locator.wait_for(state="visible", timeout=20_000)
    print(f"[ok] {label}: {selector}", flush=True)


def normalize_rut(value: str) -> str:
    return value.replace(".", "").replace("-", "").strip().upper()


def clear_login_fields(page: Page) -> None:
    """Remove credentials from the page before collecting diagnostics."""
    for selector in ("input#web_rut2", "input#web_password"):
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.fill("", timeout=1_000)
        except Exception:
            pass


def write_failure_artifacts(page: Page, artifacts: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    clear_login_fields(page)
    try:
        page.screenshot(path=str(artifacts / "failure.png"), full_page=True)
    except Exception:
        pass
    try:
        (artifacts / "failure.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        (artifacts / "failure-url.txt").write_text(page.url, encoding="utf-8")
    except Exception:
        pass


def credentials() -> tuple[str, str]:
    rut = os.environ.get("PREVIRED_RUT", "").strip()
    password = os.environ.get("PREVIRED_PASSWORD", "")
    if not rut:
        rut = input("RUT Previred: ").strip()
    if not password:
        password = getpass.getpass("Contraseña Previred: ")
    if not rut or not password:
        raise RuntimeError("Se requieren RUT y contraseña para la prueba autenticada.")
    return rut, password


def main() -> int:
    args = arguments()
    artifacts = Path(args.artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    trace_path = artifacts / "trace.zip"

    pw = browser = context = page = None
    trace_started = False
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1_500)
        _cerrar_dialogs(page)

        require_visible(page, "input#web_rut2", "campo RUT")
        require_visible(page, "input#web_password", "campo contraseña")
        require_visible(page, "button#login", "botón de acceso")
        page.screenshot(path=str(artifacts / "login-page.png"), full_page=True)

        if args.public_only:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            trace_started = True
            print("[success] La página pública y sus selectores de login están operativos.", flush=True)
            return 0

        rut, password = credentials()
        page.fill("input#web_rut2", rut)
        page.fill("input#web_password", password)
        _cerrar_dialogs(page)
        try:
            page.click("button#login", timeout=10_000)
        except Exception:
            page.evaluate("document.querySelector('button#login').click()")

        page.wait_for_url("**/wPortal/**", timeout=20_000)
        if "login.jsp" in page.url:
            raise RuntimeError("Previred devolvió al formulario de login; revisa las credenciales.")
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        trace_started = True
        page.screenshot(path=str(artifacts / "after-login.png"), full_page=True)
        print(f"[ok] Login completado. URL: {page.url}", flush=True)

        empresas = obtener_empresas(page)
        print(f"[success] Empresas disponibles: {len(empresas)}", flush=True)
        page.screenshot(path=str(artifacts / "company-list.png"), full_page=True)

        company_rut = args.company_rut.strip()
        desde = args.desde.strip()
        hasta = args.hasta.strip()
        if company_rut and desde and hasta:
            target_rut = normalize_rut(company_rut)
            source = next((item for item in empresas if normalize_rut(item.rut) == target_rut), None)
            if source is None:
                raise RuntimeError(f"No se encontró la empresa {company_rut} entre las disponibles.")
            print(
                f"[test] Empresa {company_rut}; períodos {desde} a {hasta}.",
                flush=True,
            )
            empresa = Empresa(rut=source.rut, nombre=source.nombre)
            obtener_nominas_empresa(page, empresa, desde, hasta, ConsoleBridge(), NeverStop())
            page.screenshot(path=str(artifacts / "after-discovery.png"), full_page=True)
            total = sum(len(items) for items in empresa.nominas_por_periodo.values())
            print(f"[success] Nóminas AFP encontradas: {total}", flush=True)
            print("[test] Verificando regreso directo al listado de empresas.", flush=True)
            _ir_a_lista_empresas(page)
            rows = page.locator("tr:has(button.ingresar)").count()
            print(f"[success] Regreso al listado operativo: {rows} empresas.", flush=True)
        else:
            print(
                "[info] Discovery de períodos omitido. Define PREVIRED_COMPANY_RUT, "
                "PREVIRED_DESDE y PREVIRED_HASTA para incluirlo.",
                flush=True,
            )
        return 0
    except Exception as exc:
        if page is not None:
            write_failure_artifacts(page, artifacts)
        print(f"[failure] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1
    finally:
        if context is not None and trace_started:
            try:
                context.tracing.stop(path=str(trace_path))
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
