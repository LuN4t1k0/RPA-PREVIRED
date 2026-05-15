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
    "download_log": [],
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

    opciones = [f"{e.nombre}  ({e.rut})" for e in empresas]
    idx = st.selectbox("Empresa", range(len(opciones)), format_func=lambda i: opciones[i])

    col1, col2 = st.columns(2)
    desde = col1.text_input("Desde (yyyy-mm)", value=st.session_state.desde, placeholder="2010-01")
    hasta = col2.text_input("Hasta (yyyy-mm)", value=st.session_state.hasta, placeholder="2024-12")

    if st.button("▶ Buscar nóminas", type="primary", use_container_width=True):
        if not desde or not hasta:
            st.error("Ingresa el rango de períodos.")
            return
        st.session_state.empresa_seleccionada = empresas[idx]
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
        st.warning("No se encontraron nóminas en el rango seleccionado.")
        if st.button("← Volver"):
            st.session_state.paso = 2
            st.session_state.discovery_done = False
            st.rerun()
        return

    seleccion = {}
    for periodo, nominas in sorted(empresa.nominas_por_periodo.items()):
        st.markdown(f"**{periodo}**")
        for nomina in nominas:
            key = (periodo, nomina.slug)
            checked = st.checkbox(nomina.nombre, value=True, key=str(key))
            seleccion[key] = checked

    st.session_state.seleccion = seleccion
    total = sum(seleccion.values())

    st.divider()
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


# ── PASO 4: Descargando ───────────────────────────────────────────────────────
def paso_descargando():
    _barra_pasos(4)
    st.title("⬇️ Descargando planillas...")
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

    log_lines = st.session_state.get("download_log", [])
    if log_lines:
        st.code("\n".join(log_lines[-20:]), language=None)

    BADGE = {"OK": "✅", "SIN_DATOS": "⚠️", "ERROR": "❌", "OMITIDO": "⏭️"}

    msg = _poll(session)
    if msg is None:
        return

    if msg.tipo == "planilla":
        p = msg.datos["planilla"]
        badge = BADGE.get(p.estado, "•")
        st.session_state.download_log.append(f"{badge} {p.periodo} / {p.institucion}")
        st.session_state.planillas.append(p)
        st.rerun()
    elif msg.tipo == "fin_descarga":
        st.session_state.task_running = False
        st.session_state.zip_buffer = construir_zip(st.session_state.tmpdir)
        st.session_state.download_log = []
        st.session_state.paso = 5
        st.rerun()
    elif msg.tipo == "error_fatal":
        st.error(f"Error fatal: {msg.datos.get('msg')}")
        st.session_state.task_running = False


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
