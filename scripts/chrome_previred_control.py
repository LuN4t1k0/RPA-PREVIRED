"""Diagnostic controller for an already-open Chrome Previred session."""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.downloader import _descargar_pdf_institucion, descargar_empresa
from checkpoint import Checkpoint
from models import BotMessage, Empresa, Nomina


def normalize_rut(value: str) -> str:
    return value.replace(".", "").replace("-", "").strip().upper()


def select_company(page: Page, rut: str) -> None:
    rows = page.locator("tr:has(button.ingresar)")
    target = normalize_rut(rut)
    for index in range(rows.count()):
        row = rows.nth(index)
        row_rut = row.locator("td").nth(1).inner_text().strip()
        if normalize_rut(row_rut) != target:
            continue
        name = row.locator("td").nth(2).inner_text().strip()
        print(f"[company] {row_rut} — {name}", flush=True)
        row.locator("button.ingresar").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)
        return
    raise RuntimeError(f"No se encontró la empresa {rut}.")


def open_paid_forms(page: Page) -> None:
    page.locator("#tipoPago a:has-text('Remuneraciones')").click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("Imprimir Documentos", exact=True).click()
    page.wait_for_timeout(400)
    link = page.locator("span#ver_planillas_pagadas")
    if link.is_visible():
        link.click()
    else:
        link.evaluate("element => element.click()")
    page.wait_for_load_state("networkidle")
    page.locator("#mesR0").wait_for(state="visible", timeout=20_000)
    print("[ok] Formulario Planillas Pagadas abierto.", flush=True)


def inspect_period(page: Page, period: str) -> None:
    year, month = period.split("-")
    page.select_option("#mesR0", value=month)
    page.wait_for_load_state("networkidle")
    page.select_option("#yearR0", value=year)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    options = [
        item.strip()
        for item in page.locator("#combo_nominas option").all_inner_texts()
        if item.strip() and "seleccione" not in item.lower()
    ]
    print(f"[period] {period}: {len(options)} nóminas", flush=True)
    for option in options:
        print(f"  - {option}", flush=True)


class ConsoleQueue(queue.Queue):
    def put(self, item: BotMessage, *args, **kwargs) -> None:
        if item.tipo == "status":
            print(f"[status] {item.datos.get('msg', '')}", flush=True)
        elif item.tipo == "planilla":
            planilla = item.datos["planilla"]
            print(
                f"[result] {planilla.institucion}: {planilla.estado.value} "
                f"{planilla.error_msg or planilla.ruta_archivo}",
                flush=True,
            )
        super().put(item, *args, **kwargs)


def download_period(page: Page, rut: str, company: str, period: str, nomina: str) -> None:
    output = Path("artifacts/chrome-live-download").resolve()
    output.mkdir(parents=True, exist_ok=True)
    empresa = Empresa(rut=rut, nombre=company)
    empresa.nominas_por_periodo = {
        period: [Nomina(nombre=nomina, slug="REMUNERACIONES")]
    }
    descargar_empresa(
        page,
        empresa,
        str(output),
        Checkpoint(str(output / "checkpoint.json")),
        ConsoleQueue(),
        threading.Event(),
    )
    pdfs = sorted(output.rglob("*.pdf"))
    print(f"[download] PDFs guardados: {len(pdfs)}", flush=True)
    for pdf in pdfs:
        print(f"  - {pdf.name} ({pdf.stat().st_size} bytes)", flush=True)


def download_first_visible(page: Page) -> None:
    icons = page.locator("img[src*='planillas.gif']")
    if icons.count() == 0:
        raise RuntimeError("La página actual no contiene íconos de planillas.")
    icon = icons.first
    parts = (icon.get_attribute("id") or "").split("#")
    institution = parts[-1] if parts else "AFP"
    output = Path("artifacts/chrome-live-download/one").resolve()
    output.mkdir(parents=True, exist_ok=True)
    filename = f"prueba_{institution.replace(' ', '_')}.pdf"
    result = _descargar_pdf_institucion(page, icon, str(output), filename)
    path = Path(result)
    print(f"[download] {path.name} ({path.stat().st_size} bytes)", flush=True)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("state", "company", "paid", "period", "download", "download-one"),
    )
    parser.add_argument("--rut", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--period", default="")
    parser.add_argument("--nomina", default="")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        context = browser.contexts[0]
        page = next(
            (candidate for candidate in context.pages if "/wEmpresas/CtrlFce" in candidate.url),
            context.pages[0],
        )
        if args.action == "state":
            for index, candidate in enumerate(context.pages):
                controls = candidate.locator(
                    "button, input[type='button'], input[type='submit']"
                ).evaluate_all(
                    "els => els.map(e => (e.innerText || e.value || e.id || '').trim()).filter(Boolean)"
                )
                radio_count = candidate.locator("input[type='radio']").count()
                print(
                    f"[page {index}] {candidate.title()} | {candidate.url} | "
                    f"radios={radio_count} | "
                    f"controls={controls}",
                    flush=True,
                )
        if args.action == "company":
            select_company(page, args.rut)
        elif args.action == "paid":
            open_paid_forms(page)
        elif args.action == "period":
            inspect_period(page, args.period)
        elif args.action == "download":
            download_period(page, args.rut, args.company, args.period, args.nomina)
        elif args.action == "download-one":
            for candidate in list(context.pages):
                if candidate != page:
                    candidate.close()
            download_first_visible(page)
        print(f"[state] {page.title()} | {page.url}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
