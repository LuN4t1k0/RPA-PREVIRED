# Paso 4 Timeline UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el log de texto plano del paso 4 por un timeline interactivo con spinner animado, ítems pendientes en gris y chip de progreso "X / Y".

**Architecture:** El bot emite dos mensajes nuevos (`plan` e `inicio_item`). La UI los acumula en tres listas de session_state (`timeline_plan`, `timeline_pending`, `timeline_done`) y las renderiza con `_render_timeline()` que devuelve HTML con CSS animado inline servido vía `st.markdown(unsafe_allow_html=True)`.

**Tech Stack:** Python 3.12, Streamlit, dataclasses, HTML/CSS inline (no dependencias nuevas).

---

## Archivos que cambian

| Archivo | Qué cambia |
|---|---|
| `models.py` | `Planilla` gana `tamaño_bytes: int = 0` |
| `bot/downloader.py` | `descargar_empresa()` emite `plan` e `inicio_item`; popula `tamaño_bytes` en OK |
| `app.py` | Nuevos defaults de session_state; handlers para `plan`/`inicio_item`/`status`; `_render_timeline()`; reemplaza el bloque del log |

---

## Task 1: Extender Planilla con tamaño_bytes

**Files:**
- Modify: `models.py:27-36`

- [ ] **Step 1: Añadir el campo**

Reemplazar en `models.py`:

```python
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
    tamaño_bytes: int = 0
```

- [ ] **Step 2: Verificar que no rompe nada**

```bash
cd /ruta/al/proyecto
.venv/bin/python3 -c "from models import Planilla, Estado; p = Planilla('rut','2026-01','nom','Capital','folio',Estado.OK); print(p.tamaño_bytes)"
```

Salida esperada: `0`

- [ ] **Step 3: Commit**

```bash
git add models.py
git commit -m "feat: add tamaño_bytes field to Planilla dataclass"
```

---

## Task 2: Emitir plan, inicio_item y tamaño_bytes desde el downloader

**Files:**
- Modify: `bot/downloader.py:274-365`

- [ ] **Step 1: Añadir mensaje `plan` al inicio de descargar_empresa**

En `bot/downloader.py`, reemplazar la función `descargar_empresa` completa:

```python
def descargar_empresa(
    page: Page,
    empresa: Empresa,
    output_base: str,
    checkpoint: Checkpoint,
    msg_queue: queue.Queue,
    stop_event: threading.Event,
):
    _navegar_a_planillas_pagadas(page, empresa)

    # Enviar plan completo para que la UI muestre ítems pendientes
    plan_items = [
        (periodo, nomina.nombre)
        for periodo, nominas in empresa.nominas_por_periodo.items()
        for nomina in nominas
    ]
    msg_queue.put(BotMessage(tipo="plan", datos={"items": plan_items}))

    for periodo, nominas in empresa.nominas_por_periodo.items():
        for nomina in nominas:
            if stop_event.is_set():
                return

            # Avisar qué nómina se está procesando ahora
            msg_queue.put(BotMessage(tipo="inicio_item", datos={
                "periodo": periodo,
                "nomina": nomina.nombre,
            }))

            # Intentar la búsqueda; si falla, recuperar la página y reintentar una vez
            try:
                _buscar_planillas(page, periodo, nomina)
            except Exception as e_buscar:
                msg_queue.put(BotMessage(tipo="status", datos={
                    "msg": f"⚠️ Error buscando {periodo}/{nomina.nombre}: {e_buscar}. Recuperando…"
                }))
                try:
                    _recuperar_pagina(page, empresa)
                    _buscar_planillas(page, periodo, nomina)
                except Exception as e_retry:
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion="AFP", folio="", estado=Estado.ERROR,
                        error_msg=f"Buscar falló tras recuperación: {e_retry}",
                    )
                    msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                    continue

            sin_datos = page.locator("text=No se encontraron planillas").count()
            if sin_datos > 0:
                planilla = Planilla(
                    rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                    institucion="AFP", folio="", estado=Estado.SIN_DATOS,
                )
                msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                continue

            # Expandir filas colapsadas para que los íconos sean clickeables
            for expand in page.locator("a[id^='oculta_nomina']").all():
                expand.click()
                page.wait_for_timeout(300)

            iconos = page.locator("img[src*='planillas.gif']")
            count = iconos.count()

            for i in range(count):
                if stop_event.is_set():
                    return

                icono = iconos.nth(i)
                img_id = icono.get_attribute("id") or ""
                partes = img_id.split("#")
                folio = partes[1] if len(partes) > 1 else ""
                nombre_inst = partes[-1] if partes else ""

                if checkpoint.esta_completo(empresa.rut, periodo, nomina.slug, nombre_inst):
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OMITIDO,
                    )
                    msg_queue.put(BotMessage(tipo="planilla", datos={"planilla": planilla}))
                    continue

                rut_clean = empresa.rut.replace(".", "").replace("-", "")
                output_dir = os.path.join(output_base, periodo, nomina.slug)
                os.makedirs(output_dir, exist_ok=True)
                nombre_archivo = f"{rut_clean}_{nombre_inst.replace(' ', '_')}_{periodo}.pdf"

                try:
                    ruta = _descargar_pdf_institucion(page, icono, output_dir, nombre_archivo)
                    planilla = Planilla(
                        rut_empresa=empresa.rut, periodo=periodo, nomina=nomina.slug,
                        institucion=nombre_inst, folio=folio, estado=Estado.OK,
                        ruta_archivo=ruta,
                        tamaño_bytes=os.path.getsize(ruta),
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

- [ ] **Step 2: Verificar sintaxis**

```bash
.venv/bin/python3 -c "import bot.downloader; print('OK')"
```

Salida esperada: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/downloader.py
git commit -m "feat: emit plan/inicio_item messages and populate tamaño_bytes"
```

---

## Task 3: Implementar _render_timeline() en app.py

**Files:**
- Modify: `app.py` — añadir función antes de `paso_descargando()`

- [ ] **Step 1: Insertar la función `_render_timeline` en app.py**

Añadir justo antes de la línea `# ── PASO 4: Descargando`:

```python
# ── Timeline renderer ─────────────────────────────────────────────────────────
_TL_CSS = """
<style>
@keyframes tl-spin{to{transform:rotate(360deg)}}
@keyframes tl-pulse{0%,100%{opacity:1}50%{opacity:.35}}
.tl-wrap{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;
         max-height:460px;overflow-y:auto;padding:4px 0}
.tl-row{display:flex;align-items:flex-start;gap:10px;padding:4px 0;
        border-bottom:1px solid #f3f4f6}
.tl-row:last-child{border:none}
.tl-dot{width:13px;height:13px;border-radius:50%;flex-shrink:0;margin-top:2px}
.dot-ok{background:#22c55e}.dot-err{background:#ef4444}
.dot-warn{background:#f59e0b}.dot-skip{background:#d1d5db}
.dot-pending{background:#fff;border:2px solid #d1d5db}
.tl-spinner{width:13px;height:13px;border-radius:50%;flex-shrink:0;margin-top:2px;
            border:2.5px solid #ede9fe;border-top-color:#7B2FBE;
            animation:tl-spin .7s linear infinite}
.tl-text{flex:1;min-width:0;line-height:1.4}
.txt-ok{color:#15803d}.txt-err{color:#dc2626}.txt-warn{color:#92400e}
.txt-skip{color:#6b7280}.txt-active{color:#7B2FBE;font-weight:600}
.txt-pending{color:#9ca3af}
.tl-kb{font-size:11px;color:#9ca3af;margin-left:6px}
.tl-sub{font-size:11px;color:#7B2FBE;animation:tl-pulse 1.5s ease-in-out infinite}
.tl-sep{height:1px;background:#e5e7eb;margin:6px 0}
.tl-prog-wrap{background:#f1f5f9;border-radius:4px;height:6px;margin:10px 0 6px}
.tl-prog-fill{background:linear-gradient(90deg,#7B2FBE,#a855f7);
              height:6px;border-radius:4px;transition:width .4s}
.tl-chip{display:inline-block;background:#f3e8ff;border:1px solid #d6bcfa;
         border-radius:20px;padding:2px 10px;font-size:12px;color:#6b21a8;
         font-weight:600;float:right;margin-top:-4px}
</style>
"""

_ESTADO_DOT  = {"OK": "dot-ok", "ERROR": "dot-err", "SIN_DATOS": "dot-warn", "OMITIDO": "dot-skip"}
_ESTADO_TXT  = {"OK": "txt-ok", "ERROR": "txt-err", "SIN_DATOS": "txt-warn", "OMITIDO": "txt-skip"}
_ESTADO_ICON = {"OK": "✅", "ERROR": "❌", "SIN_DATOS": "⚠️", "OMITIDO": "⏭️"}


def _render_timeline(
    plan: list,      # [(periodo, nomina_nombre), ...]
    pending: list,   # [(periodo, nomina_nombre), ...]  — los que faltan
    done: list,      # [{"inst", "periodo", "nomina", "estado", "kb"}, ...]
    current: dict | None,  # {"periodo", "nomina", "sub"} | None
) -> str:
    parts = [_TL_CSS]

    # ── Chip de progreso y barra ──────────────────────────────────────────────
    total = len(plan)
    completados = total - len(pending) - (1 if current else 0)
    completados = max(0, completados)
    pct = int(completados / total * 100) if total else 0
    parts.append(
        f'<div class="tl-chip">{completados} / {total} nóminas</div>'
        f'<div class="tl-prog-wrap"><div class="tl-prog-fill" style="width:{pct}%"></div></div>'
    )

    # ── Sección de completados ────────────────────────────────────────────────
    parts.append('<div class="tl-wrap">')
    visible_done = done[-60:]  # máximo 60 ítems
    for item in visible_done:
        estado = item["estado"]
        dot   = _ESTADO_DOT.get(estado, "dot-skip")
        txt   = _ESTADO_TXT.get(estado, "txt-skip")
        icon  = _ESTADO_ICON.get(estado, "•")
        kb    = f'<span class="tl-kb">{item["kb"]} KB</span>' if item.get("kb") else ""
        inst  = item.get("inst", "")
        per   = item.get("periodo", "")
        parts.append(
            f'<div class="tl-row">'
            f'<div class="tl-dot {dot}"></div>'
            f'<div class="tl-text"><span class="{txt}">{icon} {per} / {inst}</span>{kb}</div>'
            f'</div>'
        )

    # ── Separador + ítem activo ───────────────────────────────────────────────
    if current:
        parts.append('<div class="tl-sep"></div>')
        sub_html = f'<div class="tl-sub">{current["sub"]}</div>' if current.get("sub") else ""
        parts.append(
            f'<div class="tl-row">'
            f'<div class="tl-spinner"></div>'
            f'<div class="tl-text">'
            f'<span class="txt-active">{current["periodo"]} / {current["nomina"]}…</span>'
            f'{sub_html}'
            f'</div></div>'
        )

    # ── Separador + pendientes ────────────────────────────────────────────────
    if pending:
        parts.append('<div class="tl-sep"></div>')
        show = pending[:4]
        for per, nom in show:
            parts.append(
                f'<div class="tl-row">'
                f'<div class="tl-dot dot-pending"></div>'
                f'<div class="tl-text"><span class="txt-pending">{per} / {nom}</span></div>'
                f'</div>'
            )
        restantes = len(pending) - len(show)
        if restantes > 0:
            parts.append(
                f'<div class="tl-row" style="opacity:.5">'
                f'<div class="tl-dot dot-pending"></div>'
                f'<div class="tl-text"><span class="txt-pending">+ {restantes} más pendientes…</span></div>'
                f'</div>'
            )

    parts.append('</div>')  # cierra tl-wrap
    return "\n".join(parts)
```

- [ ] **Step 2: Verificar sintaxis**

```bash
.venv/bin/python3 -c "import app; print('OK')"
```

Salida esperada: `OK`

- [ ] **Step 3: Verificar que _render_timeline produce HTML válido**

```bash
.venv/bin/python3 - <<'EOF'
import sys; sys.path.insert(0,".")
from app import _render_timeline
plan = [("2026-01","SOP 012026"),("2026-02","SOP 022026"),("2026-03","SOP 032026")]
pending = [("2026-02","SOP 022026"),("2026-03","SOP 032026")]
done = [{"inst":"Capital","periodo":"2026-01","nomina":"SOP 012026","estado":"OK","kb":42},
        {"inst":"Cuprum","periodo":"2026-01","nomina":"SOP 012026","estado":"ERROR","kb":0}]
current = {"periodo":"2026-02","nomina":"SOP 022026","sub":"navegando al formulario"}
html = _render_timeline(plan, pending, done, current)
assert "<div class" in html
assert "Capital" in html
assert "SOP 022026" in html
assert "tl-spinner" in html
assert "SOP 032026" in html
print("OK — HTML generado correctamente")
EOF
```

Salida esperada: `OK — HTML generado correctamente`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add _render_timeline() HTML timeline component"
```

---

## Task 4: Conectar paso_descargando() al timeline

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Actualizar defaults de session_state**

En `app.py`, en el dict de inicialización (bloque `for key, default in {...}.items():`), reemplazar:

```python
    "download_log": [],
    "download_log_final_error": None,
```

Por:

```python
    "timeline_plan": [],
    "timeline_pending": [],
    "timeline_done": [],
    "timeline_current": None,
    "download_log_final_error": None,
```

- [ ] **Step 2: Actualizar _ir_a_paso5_con_lo_descargado**

Reemplazar la función existente:

```python
def _ir_a_paso5_con_lo_descargado(motivo: str | None = None):
    """Construye el ZIP con lo que hay en tmpdir y avanza al paso 5."""
    if motivo:
        st.session_state.download_log_final_error = motivo
    st.session_state.zip_buffer = construir_zip(st.session_state.tmpdir)
    st.session_state.timeline_plan = []
    st.session_state.timeline_pending = []
    st.session_state.timeline_done = []
    st.session_state.timeline_current = None
    st.session_state.task_running = False
    st.session_state.paso = 5
    st.rerun()
```

- [ ] **Step 3: Reemplazar el cuerpo de paso_descargando()**

Reemplazar la función `paso_descargando()` completa:

```python
def paso_descargando():
    _barra_pasos(4)
    st.title("⬇️ Descargando planillas…")
    session: PlaywrightSession = st.session_state.session

    if not st.session_state.task_running:
        session.drain()
        stop_event = threading.Event()
        st.session_state.stop_event = stop_event

        _empresa = st.session_state.empresa_seleccionada
        _tmpdir = st.session_state.tmpdir
        checkpoint = Checkpoint(path=f"{_tmpdir}/checkpoint.json")

        def tarea_descarga(sess: PlaywrightSession):
            descargar_empresa(sess.page, _empresa, _tmpdir, checkpoint, sess.msg_queue, stop_event)
            sess.msg_queue.put(BotMessage(tipo="fin_descarga", datos={}))

        session.submit(tarea_descarga)
        st.session_state.task_running = True

    # ── Renderizar timeline ───────────────────────────────────────────────────
    html = _render_timeline(
        st.session_state.get("timeline_plan", []),
        st.session_state.get("timeline_pending", []),
        st.session_state.get("timeline_done", []),
        st.session_state.get("timeline_current"),
    )
    st.markdown(html, unsafe_allow_html=True)

    # ── Botón de parada manual ────────────────────────────────────────────────
    if st.button("⏹ Detener y descargar lo que tengo", use_container_width=True):
        if st.session_state.stop_event:
            st.session_state.stop_event.set()
        _ir_a_paso5_con_lo_descargado()
        return

    # ── Detectar hilo muerto ──────────────────────────────────────────────────
    if not session.is_alive():
        _ir_a_paso5_con_lo_descargado("El proceso del bot terminó inesperadamente.")
        return

    # ── Leer siguiente mensaje ────────────────────────────────────────────────
    msg = _poll(session)
    if msg is None:
        return

    if msg.tipo == "plan":
        items = [tuple(i) for i in msg.datos.get("items", [])]
        st.session_state.timeline_plan = items
        st.session_state.timeline_pending = list(items)
        st.rerun()

    elif msg.tipo == "inicio_item":
        periodo = msg.datos.get("periodo", "")
        nomina  = msg.datos.get("nomina", "")
        # Quitar este ítem de los pendientes
        pending = st.session_state.get("timeline_pending", [])
        st.session_state.timeline_pending = [
            (p, n) for p, n in pending if not (p == periodo and n == nomina)
        ]
        st.session_state.timeline_current = {"periodo": periodo, "nomina": nomina, "sub": ""}
        st.rerun()

    elif msg.tipo == "status":
        current = st.session_state.get("timeline_current") or {}
        current["sub"] = msg.datos.get("msg", "")
        st.session_state.timeline_current = current
        st.rerun()

    elif msg.tipo == "planilla":
        p = msg.datos["planilla"]
        kb = round(p.tamaño_bytes / 1024) if p.tamaño_bytes else 0
        st.session_state.timeline_done.append({
            "periodo":  p.periodo,
            "nomina":   p.nomina,
            "inst":     p.institucion,
            "estado":   p.estado,
            "kb":       kb if kb > 0 else 0,
        })
        st.session_state.planillas.append(p)
        st.rerun()

    elif msg.tipo == "fin_descarga":
        _ir_a_paso5_con_lo_descargado()

    elif msg.tipo == "error_fatal":
        _ir_a_paso5_con_lo_descargado(msg.datos.get("msg", "Error desconocido"))
```

- [ ] **Step 4: Verificar sintaxis**

```bash
.venv/bin/python3 -c "import app; print('OK')"
```

Salida esperada: `OK`

- [ ] **Step 5: Smoke test manual**

```bash
.venv/bin/streamlit run app.py --server.port=8502
```

Abrir http://localhost:8502, ingresar con las credenciales de prueba, seleccionar una empresa con pocos períodos (ej. 1-2 meses), iniciar la descarga y verificar:
- Se ve la barra de progreso y el chip "0 / N nóminas"
- A medida que avanza aparece el spinner morado con el texto de la nómina actual
- Los completados aparecen arriba con ✅/❌/⚠️ y KB
- Los pendientes aparecen en gris debajo del spinner
- El botón "Detener" sigue funcionando y lleva al paso 5

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: replace download log with animated timeline in paso 4"
```

- [ ] **Step 7: Push a Railway**

```bash
git push
```
