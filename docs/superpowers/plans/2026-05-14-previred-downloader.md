# Previred Downloader Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir una app Streamlit desplegada en Railway que automatiza la descarga de planillas AFP pagadas desde Previred para múltiples empresas y períodos históricos.

**Architecture:** Streamlit wizard de 5 pasos en el que Playwright corre headless en un `BotThread` (daemon thread con su propio asyncio loop). La UI se comunica con el bot via `queue.Queue` y `threading.Event`. Los PDFs se descargan a un directorio temporal y se ofrecen al usuario como ZIP.

**Tech Stack:** Python 3.12, Playwright (async), Streamlit ≥1.32, pytest, pytest-asyncio, Docker (Railway).

---

## Estructura de archivos

```
previred-downloader/
├── Dockerfile
├── requirements.txt
├── .env.example
├── app.py                   # Streamlit wizard + máquina de estados
├── models.py                # Dataclasses: Empresa, Nomina, Planilla, BotMessage
├── checkpoint.py            # Lee/escribe checkpoint.json
├── zip_builder.py           # Construye ZIP en memoria desde directorio
├── bot/
│   ├── __init__.py
│   ├── thread.py            # BotThread: asyncio en hilo separado
│   ├── login.py             # Login automático en Previred
│   ├── discovery.py         # Extrae empresas, períodos y nóminas
│   └── downloader.py        # Descarga PDFs por institución AFP
└── tests/
    ├── test_models.py
    ├── test_checkpoint.py
    ├── test_zip_builder.py
    └── test_bot_thread.py
```

---

## Task 1: Bootstrap del proyecto

**Files:**
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `.env.example`
- Create: `bot/__init__.py`
- Create: `tests/__init__.py` (vacío)

- [ ] **Step 1: Crear `requirements.txt`**

```
streamlit>=1.32.0
playwright>=1.44.0
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Crear `Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium --with-deps

COPY . .

EXPOSE 8501
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

- [ ] **Step 3: Crear `.env.example`**

```
# Opcional: clave para cifrar sesión
SECRET_KEY=cambia-esto
```

- [ ] **Step 4: Crear `bot/__init__.py` vacío**

```python
```

- [ ] **Step 5: Instalar dependencias localmente**

```bash
pip install -r requirements.txt
playwright install chromium
```

Expected: sin errores.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt Dockerfile .env.example bot/__init__.py
git commit -m "chore: project bootstrap"
```

---

## Task 2: Models

**Files:**
- Create: `models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Escribir test**

```python
# tests/test_models.py
from models import Estado, Nomina, Empresa, Planilla, BotMessage

def test_estado_values():
    assert Estado.OK == "OK"
    assert Estado.SIN_DATOS == "SIN_DATOS"
    assert Estado.ERROR == "ERROR"
    assert Estado.OMITIDO == "OMITIDO"

def test_nomina_slug():
    n = Nomina(nombre="COLCHONES LQ ENE2010", slug="COLCHONES_LQ_ENE2010")
    assert n.slug == "COLCHONES_LQ_ENE2010"

def test_empresa_defaults():
    e = Empresa(rut="61.703.000-4", nombre="Empresa Nacional de Minería")
    assert e.nominas_por_periodo == {}

def test_planilla_estado_default():
    p = Planilla(
        rut_empresa="61.703.000-4",
        periodo="2010-01",
        nomina="COLCHONES_LQ_ENE2010",
        institucion="AFP Capital",
        folio="2008201001341342",
        estado=Estado.OK,
    )
    assert p.ruta_archivo is None
    assert p.error_msg is None

def test_bot_message_defaults():
    m = BotMessage(tipo="progreso")
    assert m.datos == {}
```

- [ ] **Step 2: Ejecutar test — debe fallar**

```bash
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: Implementar `models.py`**

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Estado(str, Enum):
    OK = "OK"
    SIN_DATOS = "SIN_DATOS"
    ERROR = "ERROR"
    OMITIDO = "OMITIDO"


@dataclass
class Nomina:
    nombre: str
    slug: str


@dataclass
class Empresa:
    rut: str
    nombre: str
    nominas_por_periodo: dict = field(default_factory=dict)  # {"yyyy-mm": [Nomina]}


@dataclass
class Planilla:
    rut_empresa: str
    periodo: str
    nomina: str
    institucion: str
    folio: str
    estado: Estado
    ruta_archivo: Optional[str] = None
    error_msg: Optional[str] = None


@dataclass
class BotMessage:
    tipo: str  # "progreso_empresa", "planilla", "fin", "error_login", "error_fatal"
    datos: dict = field(default_factory=dict)
```

- [ ] **Step 4: Ejecutar test — debe pasar**

```bash
pytest tests/test_models.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add domain models"
```

---

## Task 3: Checkpoint

**Files:**
- Create: `checkpoint.py`
- Create: `tests/test_checkpoint.py`

- [ ] **Step 1: Escribir tests**

```python
# tests/test_checkpoint.py
import json
import os
import tempfile
import pytest
from models import Estado, Planilla
from checkpoint import Checkpoint


@pytest.fixture
def tmp_checkpoint(tmp_path):
    return Checkpoint(path=str(tmp_path / "checkpoint.json"))


def test_checkpoint_empty_on_start(tmp_checkpoint):
    assert tmp_checkpoint.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is False


def test_checkpoint_marcar_ok(tmp_checkpoint):
    tmp_checkpoint.marcar(
        Planilla(
            rut_empresa="61703000-4", periodo="2010-01", nomina="NOM",
            institucion="AFP Capital", folio="123", estado=Estado.OK,
        )
    )
    assert tmp_checkpoint.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is True


def test_checkpoint_no_marca_errores(tmp_checkpoint):
    tmp_checkpoint.marcar(
        Planilla(
            rut_empresa="61703000-4", periodo="2010-01", nomina="NOM",
            institucion="AFP Capital", folio="123", estado=Estado.ERROR,
        )
    )
    assert tmp_checkpoint.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is False


def test_checkpoint_persiste_en_disco(tmp_path):
    path = str(tmp_path / "checkpoint.json")
    c1 = Checkpoint(path=path)
    c1.marcar(
        Planilla(
            rut_empresa="61703000-4", periodo="2010-01", nomina="NOM",
            institucion="AFP Capital", folio="123", estado=Estado.OK,
        )
    )
    c2 = Checkpoint(path=path)
    assert c2.esta_completo("61703000-4", "2010-01", "NOM", "AFP Capital") is True
```

- [ ] **Step 2: Ejecutar — debe fallar**

```bash
pytest tests/test_checkpoint.py -v
```

Expected: `ModuleNotFoundError: No module named 'checkpoint'`

- [ ] **Step 3: Implementar `checkpoint.py`**

```python
import json
import os
from models import Estado, Planilla


class Checkpoint:
    def __init__(self, path: str = "checkpoint.json"):
        self._path = path
        self._completados: set[str] = self._cargar()

    def _key(self, rut: str, periodo: str, nomina: str, institucion: str) -> str:
        return f"{rut}|{periodo}|{nomina}|{institucion}"

    def _cargar(self) -> set:
        if not os.path.exists(self._path):
            return set()
        with open(self._path) as f:
            return set(json.load(f))

    def _guardar(self):
        with open(self._path, "w") as f:
            json.dump(list(self._completados), f)

    def esta_completo(self, rut: str, periodo: str, nomina: str, institucion: str) -> bool:
        return self._key(rut, periodo, nomina, institucion) in self._completados

    def marcar(self, planilla: Planilla):
        if planilla.estado == Estado.OK:
            self._completados.add(
                self._key(planilla.rut_empresa, planilla.periodo, planilla.nomina, planilla.institucion)
            )
            self._guardar()
```

- [ ] **Step 4: Ejecutar — debe pasar**

```bash
pytest tests/test_checkpoint.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add checkpoint.py tests/test_checkpoint.py
git commit -m "feat: add checkpoint for resume support"
```

---

## Task 4: ZIP Builder

**Files:**
- Create: `zip_builder.py`
- Create: `tests/test_zip_builder.py`

- [ ] **Step 1: Escribir tests**

```python
# tests/test_zip_builder.py
import io
import os
import zipfile
import tempfile
import pytest
from zip_builder import construir_zip


@pytest.fixture
def directorio_con_pdfs(tmp_path):
    (tmp_path / "61703000-4" / "2010-01" / "COLCHONES").mkdir(parents=True)
    (tmp_path / "61703000-4" / "2010-01" / "COLCHONES" / "AFP_Capital_123.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "61703000-4" / "2010-01" / "COLCHONES" / "AFP_Cuprum_456.pdf").write_bytes(b"%PDF-1.4 fake2")
    return tmp_path


def test_zip_contiene_archivos(directorio_con_pdfs):
    buffer = construir_zip(str(directorio_con_pdfs))
    with zipfile.ZipFile(buffer) as zf:
        nombres = zf.namelist()
    assert "61703000-4/2010-01/COLCHONES/AFP_Capital_123.pdf" in nombres
    assert "61703000-4/2010-01/COLCHONES/AFP_Cuprum_456.pdf" in nombres


def test_zip_retorna_bytes_io(directorio_con_pdfs):
    buffer = construir_zip(str(directorio_con_pdfs))
    assert isinstance(buffer, io.BytesIO)
    assert buffer.tell() == 0  # listo para leer


def test_zip_directorio_vacio(tmp_path):
    buffer = construir_zip(str(tmp_path))
    with zipfile.ZipFile(buffer) as zf:
        assert zf.namelist() == []
```

- [ ] **Step 2: Ejecutar — debe fallar**

```bash
pytest tests/test_zip_builder.py -v
```

Expected: `ModuleNotFoundError: No module named 'zip_builder'`

- [ ] **Step 3: Implementar `zip_builder.py`**

```python
import io
import os
import zipfile


def construir_zip(directorio: str) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for raiz, _, archivos in os.walk(directorio):
            for archivo in archivos:
                ruta_abs = os.path.join(raiz, archivo)
                ruta_rel = os.path.relpath(ruta_abs, directorio)
                zf.write(ruta_abs, ruta_rel)
    buffer.seek(0)
    return buffer
```

- [ ] **Step 4: Ejecutar — debe pasar**

```bash
pytest tests/test_zip_builder.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add zip_builder.py tests/test_zip_builder.py
git commit -m "feat: add in-memory ZIP builder"
```

---

## Task 5: BotThread

**Files:**
- Create: `bot/thread.py`
- Create: `tests/test_bot_thread.py`

- [ ] **Step 1: Escribir tests**

```python
# tests/test_bot_thread.py
import asyncio
import queue
import threading
import time
import pytest
from bot.thread import BotThread
from models import BotMessage


async def tarea_exitosa(msg_queue: queue.Queue, stop_event: threading.Event):
    msg_queue.put(BotMessage(tipo="progreso_empresa", datos={"empresa": "Test SA"}))
    msg_queue.put(BotMessage(tipo="fin", datos={"total": 1}))


async def tarea_con_error(msg_queue: queue.Queue, stop_event: threading.Event):
    raise ValueError("algo salió mal")


async def tarea_con_stop(msg_queue: queue.Queue, stop_event: threading.Event):
    for i in range(100):
        if stop_event.is_set():
            return
        await asyncio.sleep(0.01)


def test_bot_thread_envia_mensajes():
    q = queue.Queue()
    stop = threading.Event()
    t = BotThread(coro_fn=tarea_exitosa, msg_queue=q, stop_event=stop)
    t.start()
    t.join(timeout=5)
    mensajes = []
    while not q.empty():
        mensajes.append(q.get())
    tipos = [m.tipo for m in mensajes]
    assert "progreso_empresa" in tipos
    assert "fin" in tipos


def test_bot_thread_captura_excepcion():
    q = queue.Queue()
    stop = threading.Event()
    t = BotThread(coro_fn=tarea_con_error, msg_queue=q, stop_event=stop)
    t.start()
    t.join(timeout=5)
    assert t.exception is not None
    assert "algo salió mal" in str(t.exception)
    msg = q.get_nowait()
    assert msg.tipo == "error_fatal"


def test_bot_thread_respeta_stop_event():
    q = queue.Queue()
    stop = threading.Event()
    t = BotThread(coro_fn=tarea_con_stop, msg_queue=q, stop_event=stop)
    t.start()
    time.sleep(0.05)
    stop.set()
    t.join(timeout=3)
    assert not t.is_alive()
```

- [ ] **Step 2: Ejecutar — debe fallar**

```bash
pytest tests/test_bot_thread.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implementar `bot/thread.py`**

```python
import asyncio
import queue
import threading
from typing import Callable

from models import BotMessage


class BotThread(threading.Thread):
    def __init__(self, coro_fn: Callable, msg_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self._coro_fn = coro_fn
        self.msg_queue = msg_queue
        self.stop_event = stop_event
        self.exception: Exception | None = None

    def run(self):
        try:
            asyncio.run(self._coro_fn(self.msg_queue, self.stop_event))
        except Exception as e:
            self.exception = e
            self.msg_queue.put(BotMessage(tipo="error_fatal", datos={"msg": str(e)}))
```

- [ ] **Step 4: Ejecutar — debe pasar**

```bash
pytest tests/test_bot_thread.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bot/thread.py tests/test_bot_thread.py
git commit -m "feat: add BotThread for async playwright in daemon thread"
```

---

## Task 6: Login bot

> No hay tests automáticos para este módulo — requiere sesión real de Previred.
> Se incluye un procedimiento de prueba manual al final.

**Files:**
- Create: `bot/login.py`

- [ ] **Step 1: Implementar `bot/login.py`**

```python
import asyncio
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


async def abrir_sesion(rut: str, password: str) -> tuple[Playwright, Browser, BrowserContext, Page]:
    """
    Abre Chromium headless, navega a Previred y hace login.
    Retorna (playwright, browser, context, page) — el llamador debe cerrarlos.
    Lanza ValueError si el login falla.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()

    await page.goto("https://www.previred.com")
    await page.click("a:has-text('INGRESAR AQUÍ')")
    await page.wait_for_load_state("networkidle")

    await page.fill("input#rut", rut)
    await page.fill("input#clave", password)
    await page.click("input[type='submit'][value='INGRESAR']")

    try:
        await page.wait_for_url("**/wPortal/**", timeout=15_000)
    except Exception:
        await browser.close()
        await pw.stop()
        raise ValueError("Login fallido: verifica RUT y contraseña")

    return pw, browser, context, page


async def cerrar_sesion(pw: Playwright, browser: Browser):
    await browser.close()
    await pw.stop()
```

> **NOTA:** Los selectores exactos (`input#rut`, `input#clave`, etc.) deben verificarse
> inspeccionando el HTML del formulario de login en https://www.previred.com
> antes de ejecutar el bot. Ajustar si difieren.

- [ ] **Step 2: Prueba manual de login**

Crear un archivo temporal `test_login_manual.py` (no commitearlo):

```python
import asyncio
from bot.login import abrir_sesion, cerrar_sesion

async def main():
    pw, browser, ctx, page = await abrir_sesion("TU-RUT", "TU-CLAVE")
    print("Login OK. URL actual:", page.url)
    await cerrar_sesion(pw, browser)

asyncio.run(main())
```

```bash
python test_login_manual.py
```

Expected: `Login OK. URL actual: https://www.previred.com/wPortal/CtrlFce`

Si falla con `ValueError`: abrir DevTools en Chrome manual, inspeccionar el formulario y ajustar los selectores en `bot/login.py`.

- [ ] **Step 3: Commit**

```bash
git add bot/login.py
git commit -m "feat: add headless login automation for Previred"
```

---

## Task 7: Discovery bot

> Prueba manual requerida — necesita sesión autenticada.

**Files:**
- Create: `bot/discovery.py`

- [ ] **Step 1: Implementar `bot/discovery.py`**

```python
import asyncio
import queue
import re
import threading
from datetime import date
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
    """Extrae lista de empresas desde Administrador de Empresas."""
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
    """
    Para una empresa, navega a Planillas Pagadas y descubre las nóminas
    disponibles por período. Escribe resultados en empresa.nominas_por_periodo.
    """
    # Ir a administrador y hacer click en Ingresar para esta empresa
    await page.goto("https://www.previred.com/wEmpresas/CtrlFce")
    await page.wait_for_load_state("networkidle")

    # Buscar la fila con el RUT de la empresa y hacer click en Ingresar
    fila = page.locator("tr").filter(has=page.locator(f"td:has-text('{empresa.rut}')")).first
    await fila.locator("input[value='Ingresar']").click()
    await page.wait_for_load_state("networkidle")

    # Click en Remuneraciones
    await page.click("input[value='Remuneraciones'], button:has-text('Remuneraciones')")
    await page.wait_for_load_state("networkidle")

    # Expandir Imprimir Documentos y click en Planillas Pagadas
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
        # Seleccionar mes y año
        await page.select_option("select[name*='mes'], select:near(:text('Período'))", label=meses[mes])
        await page.select_option("select[name*='anio'], select[name*='año']", value=año)
        await page.wait_for_timeout(500)

        # Leer nóminas disponibles
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
    for empresa in empresas:
        if stop_event.is_set():
            return
        await obtener_nominas_empresa(page, empresa, desde, hasta, msg_queue, stop_event)

    msg_queue.put(BotMessage(tipo="fin_discovery", datos={"total": len(empresas)}))
```

> **NOTA:** Los selectores de `select` para mes, año y nómina deben verificarse
> inspeccionando el HTML de la página Planillas Pagadas en Previred.
> Ajustar `select[name*='mes']` etc. según los atributos reales del formulario.

- [ ] **Step 2: Prueba unitaria de `_periodos_en_rango`**

```python
# Agregar a tests/test_models.py o crear tests/test_discovery_utils.py
from bot.discovery import _periodos_en_rango, _slug

def test_periodos_en_rango_mismo_mes():
    assert _periodos_en_rango("2024-12", "2024-12") == ["2024-12"]

def test_periodos_en_rango_cruce_año():
    result = _periodos_en_rango("2024-11", "2025-02")
    assert result == ["2024-11", "2024-12", "2025-01", "2025-02"]

def test_slug():
    assert _slug("COLCHONES LQ ENE2010") == "COLCHONES_LQ_ENE2010"
    assert _slug("AFP-Capital (2)") == "AFP_CAPITAL_2"
```

```bash
pytest tests/test_discovery_utils.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Prueba manual de discovery**

```python
# test_discovery_manual.py (no commitear)
import asyncio
import queue
import threading
from bot.login import abrir_sesion, cerrar_sesion
from bot.discovery import obtener_empresas, descubrir_todo

async def main():
    pw, browser, ctx, page = await abrir_sesion("TU-RUT", "TU-CLAVE")
    empresas = await obtener_empresas(page)
    print(f"Empresas encontradas: {len(empresas)}")
    for e in empresas[:3]:
        print(f"  {e.rut} - {e.nombre}")

    q = queue.Queue()
    stop = threading.Event()
    # Solo procesar la primera empresa, rango de 2 meses
    await descubrir_todo(page, empresas[:1], "2010-01", "2010-02", q, stop)
    print(f"Nóminas: {empresas[0].nominas_por_periodo}")
    await cerrar_sesion(pw, browser)

asyncio.run(main())
```

Expected: muestra empresas y nóminas detectadas.

- [ ] **Step 4: Commit**

```bash
git add bot/discovery.py tests/test_discovery_utils.py
git commit -m "feat: add discovery bot for companies and nominas"
```

---

## Task 8: Downloader bot

> Prueba manual requerida — necesita sesión autenticada con empresa y período conocidos.

**Files:**
- Create: `bot/downloader.py`

- [ ] **Step 1: Implementar `bot/downloader.py`**

```python
import asyncio
import os
import queue
import threading
from playwright.async_api import Page

from checkpoint import Checkpoint
from models import BotMessage, Estado, Empresa, Nomina, Planilla

MESES = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


async def _navegar_a_planillas_pagadas(page: Page, empresa: Empresa):
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


async def _buscar_planillas(page: Page, periodo: str, nomina: Nomina):
    año, mes = periodo.split("-")
    await page.select_option("select[name*='mes']", label=MESES[mes])
    await page.select_option("select[name*='anio']", value=año)
    await page.wait_for_timeout(500)
    await page.select_option("select[name*='nomina']", label=nomina.nombre)
    await page.select_option("select[name*='tipo']", label="AFP")
    await page.select_option("select[name*='institucion']", index=0)  # "Todas las Instituciones"
    await page.click("input[value='Buscar'], button:has-text('Buscar')")
    await page.wait_for_load_state("networkidle")


async def _descargar_pdf_institucion(
    page: Page,
    icono_pdf,
    output_dir: str,
    nombre_archivo: str,
) -> str:
    """
    Hace click en el icono PDF, selecciona 'Total Empresa', descarga el PDF.
    Retorna la ruta del archivo guardado.
    """
    async with page.context.expect_page() as popup_info:
        await icono_pdf.click()

    popup = await popup_info.value
    await popup.wait_for_load_state("networkidle")

    # En el modal: seleccionar "Total Empresa" y click Imprimir
    await popup.click("input[value='0']")  # radio "Total Empresa"
    async with popup.expect_download() as dl_info:
        await popup.click("input[value='Imprimir'], button:has-text('Imprimir')")

    download = await dl_info.value
    ruta = os.path.join(output_dir, nombre_archivo)
    await download.save_as(ruta)
    await popup.close()
    return ruta


async def descargar_empresa(
    page: Page,
    empresa: Empresa,
    output_base: str,
    checkpoint: Checkpoint,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    await _navegar_a_planillas_pagadas(page, empresa)

    for periodo, nominas in empresa.nominas_por_periodo.items():
        for nomina in nominas:
            if stop_event.is_set():
                return

            await _buscar_planillas(page, periodo, nomina)

            # Verificar si hay resultados
            sin_datos = await page.locator("text=No se encontraron planillas").count()
            if sin_datos > 0:
                planilla = Planilla(
                    rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                    institucion="AFP", folio="", estado=Estado.SIN_DATOS,
                )
                msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                continue

            # Obtener iconos PDF por institución
            iconos = page.locator("img[src*='pdf'], a[href*='CtrlPdf']")
            filas_inst = page.locator("table tr").filter(has=iconos)
            count = await filas_inst.count()

            for i in range(count):
                if stop_event.is_set():
                    return

                fila = filas_inst.nth(i)
                nombre_inst = (await fila.locator("td").first.inner_text()).strip()
                folio_el = fila.locator("td").nth(1)
                folio = (await folio_el.inner_text()).strip()

                if checkpoint.esta_completo(empresa.rut, periodo, nomina.slug, nombre_inst):
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OMITIDO,
                    )
                    msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                    continue

                output_dir = os.path.join(
                    output_base, empresa.rut.replace(".", "").replace("-", ""),
                    periodo, nomina.slug,
                )
                os.makedirs(output_dir, exist_ok=True)
                nombre_archivo = f"{nombre_inst.replace(' ', '_')}_{folio}.pdf"

                try:
                    icono = fila.locator("img[src*='pdf'], a[href*='CtrlPdf']").first
                    ruta = await _descargar_pdf_institucion(page, icono, output_dir, nombre_archivo)
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OK,
                        ruta_archivo=ruta,
                    )
                    checkpoint.marcar(planilla)
                except Exception as e:
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.ERROR,
                        error_msg=str(e),
                    )

                msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
```

> **NOTA:** El selector del icono PDF (`img[src*='pdf']`), del radio "Total Empresa"
> (`input[value='0']`) y del modal de impresión deben verificarse contra el HTML real.
> Ver screenshots: la tabla de resultados muestra iconos de PDF en la última columna.

- [ ] **Step 2: Prueba manual del downloader**

```python
# test_downloader_manual.py (no commitear)
import asyncio
import queue
import threading
import tempfile
from bot.login import abrir_sesion, cerrar_sesion
from bot.discovery import obtener_empresas, obtener_nominas_empresa
from bot.downloader import descargar_empresa
from checkpoint import Checkpoint
from models import Nomina

async def main():
    pw, browser, ctx, page = await abrir_sesion("TU-RUT", "TU-CLAVE")
    empresas = await obtener_empresas(page)
    empresa = empresas[0]
    
    q = queue.Queue()
    stop = threading.Event()
    await obtener_nominas_empresa(page, empresa, "2010-01", "2010-01", q, stop)
    print("Nóminas:", empresa.nominas_por_periodo)

    tmpdir = tempfile.mkdtemp()
    ckpt = Checkpoint(path=f"{tmpdir}/checkpoint.json")
    await descargar_empresa(page, empresa, tmpdir, ckpt, q, stop)

    import os
    for raiz, _, files in os.walk(tmpdir):
        for f in files:
            print(os.path.join(raiz, f))

    await cerrar_sesion(pw, browser)

asyncio.run(main())
```

Expected: imprime rutas de PDFs descargados en tmpdir.

- [ ] **Step 3: Commit**

```bash
git add bot/downloader.py
git commit -m "feat: add PDF downloader per AFP institution"
```

---

## Task 9: Streamlit app — Pasos 1 y 2 (Acceso + Descubriendo)

**Files:**
- Create: `app.py`

- [ ] **Step 1: Crear `app.py` con estado inicial y paso 1**

```python
import queue
import tempfile
import threading
import streamlit as st

from bot.login import abrir_sesion, cerrar_sesion
from bot.discovery import obtener_empresas, descubrir_todo
from bot.downloader import descargar_empresa
from bot.thread import BotThread
from checkpoint import Checkpoint
from models import BotMessage, Estado
from zip_builder import construir_zip

st.set_page_config(page_title="Previred Downloader", page_icon="📄", layout="centered")

# ── Inicialización de estado ──────────────────────────────────────────────────
for key, default in {
    "paso": 1,
    "empresas": [],
    "seleccion": {},          # {(rut, periodo, nomina_slug): bool}
    "planillas": [],          # lista de Planilla procesadas
    "bot_thread": None,
    "msg_queue": None,
    "stop_event": None,
    "pw": None,
    "browser": None,
    "ctx": None,
    "page": None,
    "tmpdir": None,
    "zip_buffer": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def _barra_pasos(actual: int):
    pasos = ["1. Acceso", "2. Descubriendo", "3. Selección", "4. Descargando", "5. Listo"]
    cols = st.columns(len(pasos))
    for i, (col, nombre) in enumerate(zip(cols, pasos), start=1):
        if i < actual:
            col.markdown(f"<div style='text-align:center;color:#888'>✓ {nombre}</div>", unsafe_allow_html=True)
        elif i == actual:
            col.markdown(f"<div style='text-align:center;font-weight:bold;color:#7B2FBE'>{nombre}</div>", unsafe_allow_html=True)
        else:
            col.markdown(f"<div style='text-align:center;color:#ccc'>{nombre}</div>", unsafe_allow_html=True)
    st.divider()


# ── PASO 1: Acceso ────────────────────────────────────────────────────────────
def paso_acceso():
    _barra_pasos(1)
    st.title("📄 Previred Downloader")
    st.subheader("Ingresa tus credenciales y el rango de períodos")

    with st.form("form_acceso"):
        col1, col2 = st.columns(2)
        rut = col1.text_input("RUT", placeholder="15.644.021-3")
        password = col2.text_input("Contraseña", type="password")

        col3, col4 = st.columns(2)
        desde = col3.text_input("Desde (yyyy-mm)", placeholder="2010-01")
        hasta = col4.text_input("Hasta (yyyy-mm)", placeholder="2024-12")

        submitted = st.form_submit_button("▶ Comenzar", use_container_width=True, type="primary")

    if submitted:
        if not all([rut, password, desde, hasta]):
            st.error("Completa todos los campos.")
            return

        with st.spinner("Conectando con Previred..."):
            try:
                import asyncio
                pw, browser, ctx, page = asyncio.run(abrir_sesion(rut, password))
                st.session_state.pw = pw
                st.session_state.browser = browser
                st.session_state.ctx = ctx
                st.session_state.page = page
                st.session_state.desde = desde
                st.session_state.hasta = hasta
                st.session_state.paso = 2
                st.rerun()
            except ValueError as e:
                st.error(str(e))


# ── PASO 2: Descubriendo ──────────────────────────────────────────────────────
def paso_descubriendo():
    _barra_pasos(2)
    st.title("🔍 Buscando empresas y períodos disponibles")

    if st.session_state.bot_thread is None:
        msg_queue = queue.Queue()
        stop_event = threading.Event()
        st.session_state.msg_queue = msg_queue
        st.session_state.stop_event = stop_event

        async def tarea_discovery(mq, se):
            empresas = await obtener_empresas(st.session_state.page)
            st.session_state.empresas = empresas
            await descubrir_todo(
                st.session_state.page, empresas,
                st.session_state.desde, st.session_state.hasta,
                mq, se,
            )

        t = BotThread(coro_fn=tarea_discovery, msg_queue=msg_queue, stop_event=stop_event)
        t.start()
        st.session_state.bot_thread = t

    q = st.session_state.msg_queue
    t = st.session_state.bot_thread

    progreso = st.progress(0)
    estado_txt = st.empty()
    total_empresas = len(st.session_state.empresas) or 1
    procesadas = 0

    while t.is_alive() or not q.empty():
        try:
            msg: BotMessage = q.get(timeout=0.5)
        except Exception:
            continue

        if msg.tipo == "progreso_empresa":
            procesadas += 1
            estado_txt.text(f"Procesando: {msg.datos.get('empresa', '')} ({procesadas}/{total_empresas})")
            progreso.progress(min(procesadas / total_empresas, 1.0))

        elif msg.tipo == "fin_discovery":
            st.session_state.bot_thread = None
            st.session_state.paso = 3
            st.rerun()

        elif msg.tipo == "error_fatal":
            st.error(f"Error: {msg.datos.get('msg')}")
            st.session_state.bot_thread = None
            return


# ── Despacho de pasos ─────────────────────────────────────────────────────────
paso = st.session_state.paso
if paso == 1:
    paso_acceso()
elif paso == 2:
    paso_descubriendo()
else:
    st.info(f"Paso {paso} — próximamente")
```

- [ ] **Step 2: Ejecutar la app y verificar pasos 1 y 2**

```bash
streamlit run app.py
```

Verificar:
- El formulario de acceso se muestra limpio
- Al ingresar credenciales incorrectas: aparece mensaje de error sin crashear
- Con credenciales correctas: avanza al paso 2 con barra de progreso animada
- La barra de pasos muestra el paso activo destacado

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add Streamlit wizard steps 1 and 2 (login + discovery)"
```

---

## Task 10: Streamlit app — Paso 3 (Selección)

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Agregar `paso_seleccion()` en `app.py`**

Agregar esta función antes del bloque de despacho final y agregar `elif paso == 3: paso_seleccion()` al despacho:

```python
# ── PASO 3: Selección ─────────────────────────────────────────────────────────
def paso_seleccion():
    _barra_pasos(3)
    st.title("☑️ Selecciona qué descargar")
    st.caption("Elige las empresas y nóminas que quieres procesar.")

    empresas = st.session_state.empresas
    if not empresas:
        st.warning("No se encontraron empresas con datos en el rango seleccionado.")
        if st.button("← Volver"):
            st.session_state.paso = 1
            st.rerun()
        return

    seleccion = {}

    for empresa in empresas:
        if not empresa.nominas_por_periodo:
            continue

        with st.expander(f"🏢 {empresa.nombre}  —  {empresa.rut}", expanded=False):
            for periodo, nominas in sorted(empresa.nominas_por_periodo.items()):
                st.markdown(f"**{periodo}**")
                for nomina in nominas:
                    key = (empresa.rut, periodo, nomina.slug)
                    checked = st.checkbox(nomina.nombre, value=True, key=str(key))
                    seleccion[key] = checked

    st.session_state.seleccion = seleccion
    total_seleccionado = sum(seleccion.values())

    st.divider()
    col1, col2 = st.columns([3, 1])
    col1.caption(f"{total_seleccionado} nóminas seleccionadas")

    if col2.button("⬇ Descargar", type="primary", disabled=total_seleccionado == 0):
        # Filtrar empresas según selección
        for empresa in empresas:
            empresa.nominas_por_periodo = {
                periodo: [n for n in nominas if seleccion.get((empresa.rut, periodo, n.slug), False)]
                for periodo, nominas in empresa.nominas_por_periodo.items()
            }
            empresa.nominas_por_periodo = {k: v for k, v in empresa.nominas_por_periodo.items() if v}

        st.session_state.tmpdir = tempfile.mkdtemp()
        st.session_state.paso = 4
        st.rerun()
```

- [ ] **Step 2: Actualizar bloque de despacho en `app.py`**

Reemplazar el bloque final de despacho con:

```python
paso = st.session_state.paso
if paso == 1:
    paso_acceso()
elif paso == 2:
    paso_descubriendo()
elif paso == 3:
    paso_seleccion()
else:
    st.info(f"Paso {paso} — próximamente")
```

- [ ] **Step 3: Verificar en browser**

```bash
streamlit run app.py
```

Verificar:
- Cada empresa aparece como expander con sus nóminas por período
- Los checkboxes inician en `True` (todo seleccionado por defecto)
- El contador de "nóminas seleccionadas" se actualiza al marcar/desmarcar
- El botón "Descargar" se deshabilita si no hay ninguna nómina seleccionada

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add Streamlit wizard step 3 (selection)"
```

---

## Task 11: Streamlit app — Pasos 4 y 5 (Descargando + Listo)

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Agregar `paso_descargando()` y `paso_listo()` en `app.py`**

```python
# ── PASO 4: Descargando ───────────────────────────────────────────────────────
def paso_descargando():
    _barra_pasos(4)
    st.title("⬇️ Descargando planillas...")

    if st.session_state.bot_thread is None:
        msg_queue = queue.Queue()
        stop_event = threading.Event()
        st.session_state.msg_queue = msg_queue
        st.session_state.stop_event = stop_event
        st.session_state.planillas = []

        checkpoint = Checkpoint(path=f"{st.session_state.tmpdir}/checkpoint.json")

        async def tarea_descarga(mq, se):
            for empresa in st.session_state.empresas:
                if se.is_set():
                    break
                await descargar_empresa(
                    st.session_state.page, empresa,
                    st.session_state.tmpdir, checkpoint, mq, se,
                )
            mq.put(BotMessage(tipo="fin_descarga", datos={}))

        t = BotThread(coro_fn=tarea_descarga, msg_queue=msg_queue, stop_event=stop_event)
        t.start()
        st.session_state.bot_thread = t

    q = st.session_state.msg_queue
    t = st.session_state.bot_thread

    log = st.empty()
    lineas = []

    BADGE = {
        "OK": "✅", "SIN_DATOS": "⚠️", "ERROR": "❌", "OMITIDO": "⏭️"
    }

    while t.is_alive() or not q.empty():
        try:
            msg: BotMessage = q.get(timeout=0.5)
        except Exception:
            continue

        if msg.tipo == "planilla":
            p = msg.datos["planilla"]
            badge = BADGE.get(p.estado, "•")
            lineas.append(f"{badge} `{p.rut_empresa}` / `{p.periodo}` / {p.institucion}")
            log.markdown("\n".join(lineas[-20:]))  # últimas 20 líneas

        elif msg.tipo == "fin_descarga":
            st.session_state.bot_thread = None
            st.session_state.zip_buffer = construir_zip(st.session_state.tmpdir)
            st.session_state.paso = 5
            st.rerun()

        elif msg.tipo == "error_fatal":
            st.error(f"Error fatal: {msg.datos.get('msg')}")
            st.session_state.bot_thread = None
            return


# ── PASO 5: Listo ─────────────────────────────────────────────────────────────
def paso_listo():
    _barra_pasos(5)
    st.title("🎉 ¡Descarga completa!")

    planillas = st.session_state.planillas
    ok = sum(1 for p in planillas if p.estado == Estado.OK)
    sin_datos = sum(1 for p in planillas if p.estado == Estado.SIN_DATOS)
    errores = sum(1 for p in planillas if p.estado == Estado.ERROR)

    col1, col2, col3 = st.columns(3)
    col1.metric("✅ Descargados", ok)
    col2.metric("⚠️ Sin datos", sin_datos)
    col3.metric("❌ Errores", errores)

    st.divider()

    if st.session_state.zip_buffer:
        st.download_button(
            label="⬇️ Descargar ZIP con todas las planillas",
            data=st.session_state.zip_buffer,
            file_name="planillas_previred.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary",
        )

    if st.button("↩ Nueva ejecución", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
```

- [ ] **Step 2: Actualizar bloque de despacho final**

```python
paso = st.session_state.paso
if paso == 1:
    paso_acceso()
elif paso == 2:
    paso_descubriendo()
elif paso == 3:
    paso_seleccion()
elif paso == 4:
    paso_descargando()
elif paso == 5:
    paso_listo()
```

- [ ] **Step 3: Agregar acumulación de planillas en `paso_descargando`**

En el bloque `if msg.tipo == "planilla":`, agregar antes de la línea de `lineas.append`:

```python
            st.session_state.planillas.append(p)
```

- [ ] **Step 4: Verificar en browser con sesión real**

```bash
streamlit run app.py
```

Verificar flujo completo con una empresa y 1-2 períodos:
- El log de descarga muestra líneas en tiempo real con badges correctos
- Al terminar aparece el paso 5 con métricas y botón de descarga
- El ZIP descargado contiene PDFs con la estructura de carpetas correcta
- "Nueva ejecución" limpia todo el estado y vuelve al paso 1

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add Streamlit wizard steps 4 and 5 (download + done)"
```

---

## Task 12: Configuración Railway

**Files:**
- Create: `railway.toml`

- [ ] **Step 1: Crear `railway.toml`**

```toml
[build]
builder = "dockerfile"

[deploy]
startCommand = "streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true"
healthcheckPath = "/"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
```

- [ ] **Step 2: Verificar build local**

```bash
docker build -t previred-bot .
docker run -p 8501:8501 previred-bot
```

Abrir `http://localhost:8501` y verificar que carga el wizard.

- [ ] **Step 3: Crear `.gitignore`**

```
__pycache__/
*.pyc
.env
checkpoint.json
output/
test_*_manual.py
*.zip
```

- [ ] **Step 4: Commit y push**

```bash
git add railway.toml .gitignore
git commit -m "chore: add Railway config and gitignore"
```

Para deploy: conectar el repositorio en railway.app → New Project → Deploy from GitHub → seleccionar repo → Railway detecta el Dockerfile automáticamente.

---

## Self-Review

**Cobertura de spec:**
- ✅ Login automático (Task 6)
- ✅ Extrae lista de empresas del portal (Task 7)
- ✅ Usuario filtra nóminas antes de ejecutar (Task 10)
- ✅ Rango global de períodos (Task 7 `_periodos_en_rango`)
- ✅ Descarga por institución AFP (Task 8)
- ✅ Estructura ZIP por empresa/período/nómina (Task 4)
- ✅ Estados OK/SIN_DATOS/ERROR/OMITIDO (Task 2, 8)
- ✅ Checkpoint para reanudar (Task 3, 8)
- ✅ Wizard 5 pasos en Streamlit (Tasks 9-11)
- ✅ Deploy Railway con Dockerfile (Task 1, 12)
- ✅ Login fallido muestra error en paso 1 sin crashear (Task 9)
- ✅ Credenciales nunca persistidas (solo en session_state)

**Nota sobre selectores Playwright:** Los selectores de `input#rut`, `input#clave`, `select[name*='mes']` etc. son estimaciones basadas en las capturas de pantalla. Deben verificarse contra el HTML real durante las pruebas manuales de Tasks 6-8 y ajustarse antes de pasar a Task 9.
