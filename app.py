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
    "desde": "",
    "hasta": "",
    "discovery_procesadas": 0,
    "download_log": [],
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

    # Track progress in session_state so it persists across reruns
    if "discovery_procesadas" not in st.session_state:
        st.session_state.discovery_procesadas = 0

    total_empresas = max(len(st.session_state.empresas), 1)
    procesadas = st.session_state.discovery_procesadas

    progreso = st.progress(min(procesadas / total_empresas, 1.0))
    estado_txt = st.empty()
    if procesadas > 0:
        estado_txt.text(f"Procesando empresas... ({procesadas}/{total_empresas})")
    else:
        estado_txt.text("Iniciando búsqueda...")

    # Read one message per rerun
    q = st.session_state.msg_queue
    try:
        msg: BotMessage = q.get_nowait()
    except Exception:
        # No message yet — rerun to poll again if thread still alive
        if t.is_alive():
            import time
            time.sleep(0.3)
            st.rerun()
        return

    if msg.tipo == "progreso_empresa":
        st.session_state.discovery_procesadas += 1
        st.rerun()

    elif msg.tipo == "fin_discovery":
        st.session_state.discovery_procesadas = 0  # reset for next run
        st.session_state.bot_thread = None
        st.session_state.paso = 3
        st.rerun()

    elif msg.tipo == "error_fatal":
        st.error(f"Error: {msg.datos.get('msg')}")
        st.session_state.bot_thread = None


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


# ── PASO 4: Descargando ───────────────────────────────────────────────────────
def paso_descargando():
    _barra_pasos(4)
    st.title("⬇️ Descargando planillas...")

    if st.session_state.bot_thread is None:
        msg_queue = queue.Queue()
        stop_event = threading.Event()
        st.session_state.msg_queue = msg_queue
        st.session_state.stop_event = stop_event

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

    # Show accumulated log lines
    log_lines = st.session_state.get("download_log", [])
    if log_lines:
        st.code("\n".join(log_lines[-20:]), language=None)

    # Read one message per rerun
    try:
        msg: BotMessage = q.get_nowait()
    except Exception:
        if t.is_alive():
            import time
            time.sleep(0.3)
            st.rerun()
        return

    BADGE = {"OK": "✅", "SIN_DATOS": "⚠️", "ERROR": "❌", "OMITIDO": "⏭️"}

    if msg.tipo == "planilla":
        p = msg.datos["planilla"]
        badge = BADGE.get(p.estado, "•")
        linea = f"{badge} {p.rut_empresa} / {p.periodo} / {p.institucion}"
        if "download_log" not in st.session_state:
            st.session_state.download_log = []
        st.session_state.download_log.append(linea)
        st.session_state.planillas.append(p)
        st.rerun()

    elif msg.tipo == "fin_descarga":
        st.session_state.bot_thread = None
        st.session_state.zip_buffer = construir_zip(st.session_state.tmpdir)
        st.session_state.download_log = []  # reset for next run
        st.session_state.paso = 5
        st.rerun()

    elif msg.tipo == "error_fatal":
        st.error(f"Error fatal: {msg.datos.get('msg')}")
        st.session_state.bot_thread = None


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


# ── Despacho de pasos ─────────────────────────────────────────────────────────
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
