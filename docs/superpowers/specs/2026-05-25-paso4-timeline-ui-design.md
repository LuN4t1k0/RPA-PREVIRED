# Paso 4 — Timeline UI Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el log de texto plano del paso 4 por un timeline interactivo que muestre en todo momento qué está descargando el bot, eliminando la sensación de que quedó colgado.

**Architecture:** Tres nuevos tipos de mensaje (`plan`, `inicio_item`) fluyen del bot hacia la UI. El estado de la UI pasa de una lista plana de líneas a tres listas separadas (`pending`, `current`, `done`) que el componente `_render_timeline()` convierte en HTML con spinner animado y progreso.

**Tech Stack:** Streamlit + `st.markdown(unsafe_allow_html=True)` para el timeline HTML; dataclass `Planilla` extendida con `tamaño_bytes`; CSS animation inline para el spinner morado.

---

## Diseño aprobado (mockup)

```
⬇️ Descargando…                          [ 7 / 20 listos ]
████████████░░░░░░░░░░  (barra de progreso 35%)

  ●  ✅ 2026-01 / Capital          42 KB
  ●  ✅ 2026-01 / Cuprum           24 KB
  ●  ✅ 2026-01 / Habitat          59 KB
  ●  ❌ 2026-01 / Provida          (Buscar falló)
  ●  ⚠️ 2026-01 / UNO             sin datos
     ────────────────────────────────────
  ⟳  Buscando planillas 2026-02 / SOP 022026…   ← spinner morado
     navegando al formulario                      ← sub-texto pulsante
     ────────────────────────────────────
  ○  2026-02 / Capital             (pendiente)
  ○  2026-02 / Cuprum              (pendiente)
  ○  2026-02 / Habitat             (pendiente)
  ○  + 10 más pendientes…

[ ⏹ Detener y descargar lo que tengo ]
```

---

## Cambios por archivo

### `models.py`
- Añadir `tamaño_bytes: int = 0` a `Planilla`

### `bot/downloader.py`
- `descargar_empresa()` envía `BotMessage(tipo="plan", datos={"items": [...]})` al inicio, donde `items` es la lista plana de `(periodo, nomina.nombre)` que se va a procesar.
- Antes de cada `_buscar_planillas()`, envía `BotMessage(tipo="inicio_item", datos={"periodo": periodo, "nomina": nomina.nombre})`.
- Al crear `Planilla` con `estado=Estado.OK`, populamos `tamaño_bytes=os.path.getsize(ruta)`.

### `app.py`
**Session state nuevo:**
```python
"timeline_plan": [],     # [(periodo, nomina_nombre), ...] — plan completo
"timeline_done": [],     # [dict con periodo/nomina/inst/estado/kb] — completados
"timeline_current": None,# {"periodo": ..., "nomina": ..., "sub": ...} | None
```

**Nuevos handlers en `paso_descargando()`:**
- `msg.tipo == "plan"` → guarda `timeline_plan` en session_state
- `msg.tipo == "inicio_item"` → actualiza `timeline_current`
- `msg.tipo == "status"` → actualiza `timeline_current["sub"]` (sub-texto del spinner)
- `msg.tipo == "planilla"` → añade a `timeline_done`; si `estado==OK`, incluye KB

**Función `_render_timeline(plan, done, current) -> str`:**
Genera el HTML completo del timeline:
1. Contadores: cuenta ítems en `done` por estado → chip `"N OK · M ❌"`
2. Barra de progreso: `len(done) / len(plan)` como porcentaje (sólo cuenta nominas, no instituciones individuales)
3. Sección completados: un `<div>` por entrada en `done`, con dot de color según estado y KB si está disponible
4. Separador `<hr>`
5. Ítem activo: spinner CSS morado + texto + sub-texto pulsante (si `current` no es None)
6. Separador `<hr>`
7. Pendientes: los `(periodo, nomina)` de `plan` que todavía no aparecen en `done` ni son `current`; mostrar hasta 4, luego "+ N más…"
8. Límite del timeline: max 50 ítems en la sección de completados (los últimos 50), con scroll via `overflow-y: auto; max-height: 420px`

**CSS inline (en la string HTML):**
```css
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.tl-spinner { border:2.5px solid #ede9fe; border-top-color:#7B2FBE;
              border-radius:50%; width:13px; height:13px;
              animation: spin 0.7s linear infinite; }
```

**Reemplaza** el bloque actual:
```python
# ANTES
log_lines = st.session_state.get("download_log", [])
if log_lines:
    with st.container(height=400, border=True):
        for line in log_lines:
            st.markdown(line)
```

Por:
```python
# DESPUÉS
html = _render_timeline(
    st.session_state.get("timeline_plan", []),
    st.session_state.get("timeline_done", []),
    st.session_state.get("timeline_current"),
)
st.markdown(html, unsafe_allow_html=True)
```

**Limpieza al ir al paso 5:** eliminar `download_log` del estado y también `timeline_plan / timeline_done / timeline_current`.

---

## Inicialización de session_state

Añadir al dict de defaults en `app.py`:
```python
"timeline_plan": [],
"timeline_done": [],
"timeline_current": None,
```

Eliminar `"download_log": []` (ya no se usa).

---

## Comportamiento en casos borde

| Caso | Comportamiento |
|---|---|
| Bot aún no envió `plan` (primera carga) | Timeline vacío, barra al 0% |
| `current` es None (entre ítems) | No se muestra sección activa — no debería verse "colgado" porque el próximo `inicio_item` llega rápido |
| Error fatal → paso 5 | `timeline_current = None` antes de ir al paso 5 |
| Detener manual | `timeline_current = None` antes de ir al paso 5 |
| `tamaño_bytes == 0` en un OK | No mostrar KB (solo el ✅) |

---

## Lo que NO cambia

- Lógica de descarga (`_descargar_pdf_institucion`, flujos A/B/C)
- Checkpoint y deduplicación
- Botón "Detener y descargar lo que tengo"
- Transición automática a paso 5 en error fatal o hilo muerto
- Paso 5 (listo / descarga ZIP)
