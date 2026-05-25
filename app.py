import queue
import tempfile
import threading
import time
import streamlit as st

from bot.login import abrir_sesion
from bot.discovery import obtener_empresas, obtener_nominas_empresa
from bot.downloader import descargar_empresa
from bot.session import PlaywrightSession
from checkpoint import Checkpoint
from models import BotMessage, Estado
from zip_builder import construir_zip

st.set_page_config(page_title="Previred Downloader", page_icon="📄", layout="centered")

# ── Inicialización de estado ──────────────────────────────────────────────────
for key, default in {
    "paso": 1,
    "session": None,           # PlaywrightSession (hilo persistente)
    "task_running": False,
    "stop_event": None,
    "empresas": [],
    "empresas_cargadas": False,
    "empresa_seleccionada": None,
    "desde": "",
    "hasta": "",
    "discovery_done": False,
    "seleccion": {},
    "planillas": [],
    "tmpdir": None,
    "zip_buffer": None,
    "discovery_status": "",
    "timeline_plan": [],
    "timeline_pending": [],
    "timeline_done": [],
    "timeline_current": None,
    "download_log_final_error": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def _barra_pasos(actual: int):
    pasos = ["1. Acceso", "2. Empresa", "3. Selección", "4. Descargando", "5. Listo"]
    cols = st.columns(len(pasos))
    for i, (col, nombre) in enumerate(zip(cols, pasos), start=1):
        if i < actual:
            col.markdown(f"<div style='text-align:center;color:#888'>✓ {nombre}</div>", unsafe_allow_html=True)
        elif i == actual:
            col.markdown(f"<div style='text-align:center;font-weight:bold;color:#7B2FBE'>{nombre}</div>", unsafe_allow_html=True)
        else:
            col.markdown(f"<div style='text-align:center;color:#ccc'>{nombre}</div>", unsafe_allow_html=True)
    st.divider()


def _poll(session: PlaywrightSession):
    """Lee un mensaje de la cola. Si no hay, reprograma el rerun y retorna None."""
    try:
        return session.msg_queue.get_nowait()
    except Exception:
        time.sleep(0.3)
        st.rerun()
        return None


# ── PASO 1: Acceso ────────────────────────────────────────────────────────────
def paso_acceso():
    _barra_pasos(1)
    st.title("📄 Previred Downloader")
    st.subheader("Ingresa tus credenciales")

    with st.form("form_acceso"):
        col1, col2 = st.columns(2)
        rut = col1.text_input("RUT", placeholder="15.644.021-3")
        password = col2.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("▶ Conectar", use_container_width=True, type="primary")

    if submitted:
        if not rut or not password:
            st.error("Ingresa RUT y contraseña.")
            return

        session = PlaywrightSession()
        session.start()

        done = threading.Event()
        login_error: list[str] = []
        _rut, _password = rut, password

        def do_login(sess: PlaywrightSession):
            try:
                pw, browser, ctx, page = abrir_sesion(_rut, _password)
                sess.pw = pw
                sess.browser = browser
                sess.page = page
            except ValueError as e:
                login_error.append(str(e))
            finally:
                done.set()

        session.submit(do_login)

        with st.spinner("Conectando con Previred..."):
            done.wait(timeout=30)

        if login_error:
            st.error(login_error[0])
            session.stop()
        else:
            st.session_state.session = session
            st.session_state.paso = 2
            st.rerun()


# ── PASO 2: Elegir empresa ────────────────────────────────────────────────────
def paso_elegir_empresa():
    _barra_pasos(2)
    st.title("🏢 Selecciona la empresa")
    session: PlaywrightSession = st.session_state.session

    # ── Fase A: cargar lista ──────────────────────────────────────────────────
    if not st.session_state.empresas_cargadas:
        if not st.session_state.task_running:
            session.drain()

            def tarea_empresas(sess: PlaywrightSession):
                empresas = obtener_empresas(sess.page)
                sess.msg_queue.put(BotMessage(tipo="empresas_cargadas", datos={"empresas": empresas}))

            session.submit(tarea_empresas)
            st.session_state.task_running = True

        st.info("⏳ Cargando lista de empresas...")
        msg = _poll(session)
        if msg is None:
            return

        if msg.tipo == "empresas_cargadas":
            st.session_state.empresas = msg.datos["empresas"]
            st.session_state.empresas_cargadas = True
            st.session_state.task_running = False
            st.rerun()
        elif msg.tipo == "error_fatal":
            st.error(f"Error cargando empresas: {msg.datos.get('msg')}")
            st.session_state.task_running = False
        return

    # ── Fase B: selección ─────────────────────────────────────────────────────
    empresas = st.session_state.empresas
    if not empresas:
        st.warning("No se encontraron empresas en tu cuenta.")
        if st.button("↩ Volver al inicio"):
            st.session_state.session.stop()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        return

    busqueda = st.text_input("🔍 Buscar empresa", placeholder="Nombre o RUT…")
    if busqueda:
        q = busqueda.lower()
        filtradas = [e for e in empresas if q in e.nombre.lower() or q in e.rut.replace(".", "").lower()]
    else:
        filtradas = empresas

    if not filtradas:
        st.warning("Sin resultados para esa búsqueda.")
        filtradas = empresas

    opciones = [f"{e.nombre}  ({e.rut})" for e in filtradas]
    if busqueda:
        st.caption(f"{len(filtradas)} de {len(empresas)} empresas")
    idx = st.selectbox("Empresa", range(len(opciones)), format_func=lambda i: opciones[i], label_visibility="collapsed")

    col1, col2 = st.columns(2)
    desde = col1.text_input("Desde (yyyy-mm)", value=st.session_state.desde, placeholder="2010-01")
    hasta = col2.text_input("Hasta (yyyy-mm)", value=st.session_state.hasta, placeholder="2024-12")

    if st.button("▶ Buscar nóminas", type="primary", use_container_width=True):
        if not desde or not hasta:
            st.error("Ingresa el rango de períodos.")
            return
        st.session_state.empresa_seleccionada = filtradas[idx]
        st.session_state.desde = desde
        st.session_state.hasta = hasta
        st.session_state.discovery_done = False
        st.session_state.paso = 3
        st.rerun()


# ── PASO 3: Selección (discovery + checkboxes) ────────────────────────────────
def paso_seleccion():
    _barra_pasos(3)
    empresa = st.session_state.empresa_seleccionada
    session: PlaywrightSession = st.session_state.session

    # ── Fase A: discovery ─────────────────────────────────────────────────────
    if not st.session_state.discovery_done:
        st.title("🔍 Buscando nóminas...")
        st.caption(f"{empresa.nombre}  ({empresa.rut})")

        if not st.session_state.task_running:
            session.drain()
            stop_event = threading.Event()
            st.session_state.stop_event = stop_event

            _desde = st.session_state.desde
            _hasta = st.session_state.hasta

            def tarea_discovery(sess: PlaywrightSession):
                obtener_nominas_empresa(sess.page, empresa, _desde, _hasta, sess.msg_queue, stop_event)
                sess.msg_queue.put(BotMessage(tipo="fin_discovery", datos={}))

            session.submit(tarea_discovery)
            st.session_state.task_running = True

        ultimo_status = st.session_state.discovery_status
        st.info(f"⏳ {ultimo_status}" if ultimo_status else "⏳ Iniciando búsqueda...")

        msg = _poll(session)
        if msg is None:
            return

        if msg.tipo == "status":
            st.session_state.discovery_status = msg.datos.get("msg", "")
            st.rerun()
        elif msg.tipo in ("progreso_empresa", "fin_discovery"):
            st.session_state.discovery_done = True
            st.session_state.discovery_status = ""
            st.session_state.task_running = False
            st.rerun()
        elif msg.tipo == "error_fatal":
            st.error(f"Error: {msg.datos.get('msg')}")
            st.session_state.task_running = False
        return

    # ── Fase B: selección ─────────────────────────────────────────────────────
    st.title("☑️ Selecciona qué descargar")
    st.caption(f"Empresa: **{empresa.nombre}** ({empresa.rut})")

    if not empresa.nominas_por_periodo:
        st.warning(
            f"No se encontraron nóminas AFP para **{empresa.nombre}** "
            f"entre **{st.session_state.desde}** y **{st.session_state.hasta}**. "
            "Intenta con un rango de períodos diferente (por ejemplo, años más recientes)."
        )
        if st.button("← Cambiar período"):
            st.session_state.paso = 2
            st.session_state.discovery_done = False
            st.rerun()
        return

    seleccion = {}
    with st.container(height=480, border=True):
        for periodo, nominas in sorted(empresa.nominas_por_periodo.items()):
            st.markdown(f"**{periodo}**")
            for nomina in nominas:
                key = (periodo, nomina.slug)
                checked = st.checkbox(nomina.nombre, value=True, key=str(key))
                seleccion[key] = checked

    st.session_state.seleccion = seleccion
    total = sum(seleccion.values())

    col1, col2 = st.columns([3, 1])
    col1.caption(f"{total} nóminas seleccionadas")

    if col2.button("⬇ Descargar", type="primary", disabled=total == 0):
        empresa.nominas_por_periodo = {
            periodo: [n for n in nominas if seleccion.get((periodo, n.slug), False)]
            for periodo, nominas in empresa.nominas_por_periodo.items()
        }
        empresa.nominas_por_periodo = {k: v for k, v in empresa.nominas_por_periodo.items() if v}
        st.session_state.tmpdir = tempfile.mkdtemp()
        st.session_state.paso = 4
        st.rerun()


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
              height:6px;border-radius:4px}
.tl-chip{display:inline-block;background:#f3e8ff;border:1px solid #d6bcfa;
         border-radius:20px;padding:2px 10px;font-size:12px;color:#6b21a8;
         font-weight:600;float:right;margin-top:-4px}
</style>
"""

_ESTADO_DOT  = {"OK": "dot-ok", "ERROR": "dot-err", "SIN_DATOS": "dot-warn", "OMITIDO": "dot-skip"}
_ESTADO_TXT  = {"OK": "txt-ok", "ERROR": "txt-err", "SIN_DATOS": "txt-warn", "OMITIDO": "txt-skip"}
_ESTADO_ICON = {"OK": "✅", "ERROR": "❌", "SIN_DATOS": "⚠️", "OMITIDO": "⏭️"}


def _render_timeline(
    plan: list,
    pending: list,
    done: list,
    current: dict | None,
) -> str:
    """Genera el HTML del timeline de descarga.

    plan    — [(periodo, nomina_nombre), ...] plan completo
    pending — [(periodo, nomina_nombre), ...] ítems aún no iniciados
    done    — [{"inst","periodo","nomina","estado","kb"}, ...] completados
    current — {"periodo","nomina","sub"} | None ítem activo
    """
    parts = [_TL_CSS]

    # Chip de progreso y barra
    total = len(plan)
    completados = total - len(pending) - (1 if current else 0)
    completados = max(0, completados)
    pct = int(completados / total * 100) if total else 0
    parts.append(
        f'<div class="tl-chip">{completados} / {total} nóminas</div>'
        f'<div class="tl-prog-wrap">'
        f'<div class="tl-prog-fill" style="width:{pct}%"></div></div>'
    )

    # Sección de completados (máx 60 ítems)
    parts.append('<div class="tl-wrap">')
    for item in done[-60:]:
        estado = item["estado"]
        dot  = _ESTADO_DOT.get(estado, "dot-skip")
        txt  = _ESTADO_TXT.get(estado, "txt-skip")
        icon = _ESTADO_ICON.get(estado, "•")
        kb   = f'<span class="tl-kb">{item["kb"]} KB</span>' if item.get("kb") else ""
        parts.append(
            f'<div class="tl-row">'
            f'<div class="tl-dot {dot}"></div>'
            f'<div class="tl-text">'
            f'<span class="{txt}">{icon} {item.get("periodo","")} / {item.get("inst","")}</span>'
            f'{kb}</div></div>'
        )

    # Ítem activo
    if current:
        parts.append('<div class="tl-sep"></div>')
        sub = f'<div class="tl-sub">{current["sub"]}</div>' if current.get("sub") else ""
        parts.append(
            f'<div class="tl-row">'
            f'<div class="tl-spinner"></div>'
            f'<div class="tl-text">'
            f'<span class="txt-active">{current["periodo"]} / {current["nomina"]}…</span>'
            f'{sub}</div></div>'
        )

    # Pendientes
    if pending:
        parts.append('<div class="tl-sep"></div>')
        for per, nom in pending[:4]:
            parts.append(
                f'<div class="tl-row">'
                f'<div class="tl-dot dot-pending"></div>'
                f'<div class="tl-text">'
                f'<span class="txt-pending">{per} / {nom}</span></div></div>'
            )
        restantes = len(pending) - 4
        if restantes > 0:
            parts.append(
                f'<div class="tl-row" style="opacity:.5">'
                f'<div class="tl-dot dot-pending"></div>'
                f'<div class="tl-text">'
                f'<span class="txt-pending">+ {restantes} más pendientes…</span>'
                f'</div></div>'
            )

    parts.append('</div>')
    return "\n".join(parts)


# ── PASO 4: Descargando ───────────────────────────────────────────────────────
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

    # ── Timeline ──────────────────────────────────────────────────────────────
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

    # ── Detectar hilo muerto (crash inesperado sin error_fatal) ───────────────
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
        st.session_state.timeline_pending = [
            (p, n) for p, n in st.session_state.get("timeline_pending", [])
            if not (p == periodo and n == nomina)
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
            "periodo": p.periodo,
            "nomina":  p.nomina,
            "inst":    p.institucion,
            "estado":  p.estado,
            "kb":      kb,
        })
        st.session_state.planillas.append(p)
        st.rerun()

    elif msg.tipo == "fin_descarga":
        _ir_a_paso5_con_lo_descargado()

    elif msg.tipo == "error_fatal":
        _ir_a_paso5_con_lo_descargado(msg.datos.get("msg", "Error desconocido"))


# ── PASO 5: Listo ─────────────────────────────────────────────────────────────
def paso_listo():
    _barra_pasos(5)

    error_final = st.session_state.pop("download_log_final_error", None)
    if error_final:
        st.warning(f"⚠️ La descarga se interrumpió:\n\n{error_final}")
        st.title("📦 Planillas descargadas hasta aquí")
    else:
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
        empresa = st.session_state.empresa_seleccionada
        rut_clean = empresa.rut.replace(".", "").replace("-", "") if empresa else "planillas"
        st.download_button(
            label="⬇️ Descargar ZIP con todas las planillas",
            data=st.session_state.zip_buffer,
            file_name=f"planillas_{rut_clean}.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary",
        )

    if st.button("↩ Nueva ejecución", use_container_width=True):
        sess = st.session_state.get("session")
        if sess:
            sess.stop()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# ── Despacho de pasos ─────────────────────────────────────────────────────────
paso = st.session_state.paso
if paso == 1:
    paso_acceso()
elif paso == 2:
    paso_elegir_empresa()
elif paso == 3:
    paso_seleccion()
elif paso == 4:
    paso_descargando()
elif paso == 5:
    paso_listo()
