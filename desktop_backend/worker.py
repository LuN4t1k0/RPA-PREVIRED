"""Persistent JSON-lines worker used by the Electron desktop client.

Playwright objects stay on this process' main thread. A small stdin reader thread
accepts commands and can set the cancellation event while a long operation runs.
"""

from __future__ import annotations

import json
import queue
import signal
import sys
import tempfile
import threading
import traceback
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.discovery import obtener_empresas, obtener_nominas_empresa
from bot.downloader import descargar_empresa
from bot.login import abrir_sesion
from checkpoint import Checkpoint
from models import BotMessage, Empresa, Estado, Nomina, Planilla
from zip_builder import construir_zip


COMMANDS: queue.Queue[dict | None] = queue.Queue()
CANCEL_EVENT = threading.Event()


def emit(event_type: str, **payload) -> None:
    print(json.dumps({"type": event_type, **payload}, ensure_ascii=False), flush=True)


def planilla_payload(planilla: Planilla) -> dict:
    data = asdict(planilla)
    data["estado"] = planilla.estado.value if isinstance(planilla.estado, Estado) else str(planilla.estado)
    return data


class EventBridge:
    """Queue-compatible adapter that forwards bot messages to Electron."""

    def put(self, message: BotMessage) -> None:
        payload = dict(message.datos)
        planilla = payload.get("planilla")
        if isinstance(planilla, Planilla):
            payload["planilla"] = planilla_payload(planilla)
        emit(message.tipo, **payload)


def read_commands() -> None:
    for raw_line in sys.stdin:
        try:
            command = json.loads(raw_line)
        except json.JSONDecodeError:
            emit("error", message="Electron envio un comando invalido al motor Python.")
            continue

        if command.get("type") == "cancel":
            CANCEL_EVENT.set()
        else:
            COMMANDS.put(command)
    CANCEL_EVENT.set()
    COMMANDS.put(None)


def serialize_empresas(empresas: list[Empresa]) -> list[dict]:
    return [{"rut": item.rut, "nombre": item.nombre} for item in empresas]


def serialize_nominas(empresa: Empresa) -> list[dict]:
    return [
        {
            "periodo": periodo,
            "nominas": [{"nombre": nomina.nombre, "slug": nomina.slug} for nomina in nominas],
        }
        for periodo, nominas in sorted(empresa.nominas_por_periodo.items())
    ]


def selected_empresa(source: Empresa, selected: list[dict]) -> Empresa:
    allowed = {(str(item.get("periodo")), str(item.get("slug"))) for item in selected}
    result = Empresa(rut=source.rut, nombre=source.nombre)
    result.nominas_por_periodo = {
        periodo: [Nomina(nombre=n.nombre, slug=n.slug) for n in nominas if (periodo, n.slug) in allowed]
        for periodo, nominas in source.nominas_por_periodo.items()
    }
    result.nominas_por_periodo = {key: value for key, value in result.nominas_por_periodo.items() if value}
    return result


def close_browser(pw, browser) -> None:
    if browser:
        try:
            browser.close()
        except Exception:
            pass
    if pw:
        try:
            pw.stop()
        except Exception:
            pass


def main() -> int:
    signal.signal(signal.SIGINT, lambda *_: CANCEL_EVENT.set())
    signal.signal(signal.SIGTERM, lambda *_: CANCEL_EVENT.set())
    threading.Thread(target=read_commands, daemon=True).start()

    pw = browser = page = None
    empresas: list[Empresa] = []
    active_empresa: Empresa | None = None
    bridge = EventBridge()
    emit("worker_ready")

    try:
        while True:
            command = COMMANDS.get()
            if command is None:
                break
            command_type = command.get("type")

            try:
                if command_type == "login":
                    CANCEL_EVENT.clear()
                    close_browser(pw, browser)
                    pw = browser = page = None
                    emit("status", message="Conectando con Previred...")
                    pw, browser, _context, page = abrir_sesion(
                        str(command.get("rut", "")).strip(),
                        str(command.get("password", "")),
                    )
                    emit("status", message="Cargando empresas disponibles...")
                    empresas = obtener_empresas(page)
                    active_empresa = None
                    emit("login_success", empresas=serialize_empresas(empresas))

                elif command_type == "discover":
                    if page is None:
                        raise RuntimeError("Debes iniciar sesion antes de buscar nominas.")
                    CANCEL_EVENT.clear()
                    rut = str(command.get("rut", ""))
                    nombre = str(command.get("nombre", ""))
                    source = next((e for e in empresas if e.rut == rut and e.nombre == nombre), None)
                    if source is None:
                        raise RuntimeError("No se encontro la empresa seleccionada.")
                    active_empresa = Empresa(rut=source.rut, nombre=source.nombre)
                    obtener_nominas_empresa(
                        page,
                        active_empresa,
                        str(command.get("desde", "")),
                        str(command.get("hasta", "")),
                        bridge,
                        CANCEL_EVENT,
                    )
                    if CANCEL_EVENT.is_set():
                        emit("canceled")
                    else:
                        emit("discovery_complete", nominas=serialize_nominas(active_empresa))

                elif command_type == "download":
                    if page is None or active_empresa is None:
                        raise RuntimeError("Primero selecciona una empresa y busca sus nominas.")
                    CANCEL_EVENT.clear()
                    empresa = selected_empresa(active_empresa, list(command.get("selected", [])))
                    if not empresa.nominas_por_periodo:
                        raise RuntimeError("Selecciona al menos una nomina para descargar.")

                    output_path = Path(str(command.get("outputPath", ""))).resolve()
                    if not output_path.name:
                        raise RuntimeError("No se definio el archivo de salida.")
                    run_dir = Path(tempfile.mkdtemp(prefix="previred-desktop-"))
                    checkpoint = Checkpoint(path=str(run_dir / "checkpoint.json"))
                    descargar_empresa(page, empresa, str(run_dir), checkpoint, bridge, CANCEL_EVENT)

                    zip_buffer = construir_zip(str(run_dir))
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(zip_buffer.getvalue())
                    emit(
                        "download_complete" if not CANCEL_EVENT.is_set() else "download_canceled",
                        outputPath=str(output_path),
                    )

                elif command_type == "shutdown":
                    break
                else:
                    emit("error", message=f"Comando desconocido: {command_type}")
            except Exception as exc:
                emit("error_fatal", message=str(exc), detail=traceback.format_exc(limit=4))
    finally:
        close_browser(pw, browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
