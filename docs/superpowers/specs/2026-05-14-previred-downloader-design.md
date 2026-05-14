# Diseño — Previred Downloader Bot

**Fecha:** 2026-05-14  
**Estado:** Aprobado

---

## Resumen

Herramienta web desplegada en Railway que automatiza la descarga de planillas previsionales pagadas desde Previred para múltiples empresas y períodos históricos. El usuario interactúa a través de un wizard de 5 pasos en Streamlit. Playwright corre headless en el servidor haciendo login automático (sin 2FA).

---

## Decisiones de diseño

| Decisión | Elección | Razón |
|---|---|---|
| Stack | Python + Playwright | Mejor soporte para múltiples pestañas y descargas |
| UI | Streamlit wizard | User-friendly sin necesidad de instalar nada |
| Deploy | Railway (un solo servicio) | Simple, sin infraestructura adicional |
| Instituciones MVP | Solo AFP | Alcance inicial acordado |
| Login | Automático (RUT + contraseña) | No hay 2FA en las cuentas |
| Nóminas | El usuario elige cuáles incluir | Control explícito antes de ejecutar |
| Períodos | Rango global (desde/hasta) igual para todas las empresas | Simplicidad |
| Destino archivos | ZIP descargable desde la app | Sin integraciones externas |
| Broker de estado | queue.Queue + checkpoint.json | Suficiente para un solo usuario; Redis es overkill |
| Credenciales | Solo en memoria durante la sesión | Nunca se persisten |

---

## Arquitectura

```
Railway (un solo servicio, un solo proceso)
├── Streamlit (UI + máquina de estados en st.session_state)
└── BotThread (daemon thread con asyncio.run())
    └── Playwright headless Chromium
```

**Comunicación Streamlit ↔ BotThread:**
- `queue.Queue` — el bot envía mensajes de progreso; Streamlit los lee en cada rerun
- `threading.Event` — Streamlit señala al bot cuándo iniciar y detener

**Archivos temporales:**
- PDFs se descargan a `tempfile.mkdtemp()` durante la sesión
- Al finalizar se construye un ZIP en memoria (`io.BytesIO`)
- El directorio temporal se elimina tras entregar el ZIP

---

## Flujo de pantallas (wizard)

```
[1. Acceso] → [2. Descubriendo] → [3. Selección] → [4. Descargando] → [5. Listo]
```

### Paso 1 — Acceso
- Campos: RUT, Contraseña, Desde (mes/año), Hasta (mes/año)
- Botón: **"Comenzar"**
- El bot abre Chromium headless y hace login en Previred
- Si el login falla (credenciales incorrectas o error de red): muestra mensaje de error en el mismo paso 1 y permite reintentar sin recargar la página

### Paso 2 — Descubriendo
- Pantalla de espera con barra de progreso animada
- Mensaje: *"Encontrando empresas disponibles… (23 de 47)"*
- El bot navega al Administrador de Empresas y extrae todas las empresas
- Para cada empresa × período, obtiene las nóminas disponibles

### Paso 3 — Selección
- Tabla de empresas con checkbox para incluir/excluir
- Al expandir una empresa: lista de nóminas por período con checkbox
- Botón: **"Descargar planillas seleccionadas"**

### Paso 4 — Descargando
- Lista en tiempo real: empresa → período → institución → badge de estado
- Estados: ✅ OK / ⚠️ Sin datos / ❌ Error
- Sin interacción del usuario

### Paso 5 — Listo
- Métricas: archivos descargados / sin datos / errores
- Botón: **"Descargar ZIP"**
- Botón: **"Nueva ejecución"** (vuelve al paso 1)

---

## Estructura del proyecto

```
previred-downloader/
├── Dockerfile
├── requirements.txt
├── app.py                  # Streamlit app + máquina de estados
├── bot/
│   ├── __init__.py
│   ├── thread.py           # BotThread: asyncio loop en hilo separado
│   ├── login.py            # Automatiza login en Previred
│   ├── discovery.py        # Extrae empresas, períodos y nóminas
│   └── downloader.py       # Descarga PDFs por institución AFP
├── models.py               # Dataclasses: Empresa, Nomina, Planilla, Estado
├── checkpoint.py           # Lee/escribe checkpoint.json para reanudar
└── zip_builder.py          # Empaqueta output/ en ZIP en memoria
```

---

## Estructura del ZIP descargable

```
planillas.zip
└── {rut_empresa}/
    └── {yyyy-mm}/
        └── {nomina_slug}/
            └── {institucion}_{folio}.pdf
```

**Ejemplo:**
```
planillas.zip
└── 61703000-4/
    └── 2010-01/
        └── COLCHONES_LQ_ENE2010/
            └── AFP_Capital_2008201001341342.pdf
            └── AFP_Cuprum_2001201001158951.pdf
            └── AFP_Habitat_2002201001365918.pdf
```

---

## Estados de planilla

| Estado | Significado | Acción |
|---|---|---|
| `OK` | PDF descargado correctamente | Se incluye en el ZIP |
| `SIN_DATOS` | El período no tiene planillas en Previred | Se registra en log, no falla |
| `ERROR` | Falló la descarga | Se registra; reintentable relanzando |
| `OMITIDO` | Ya existía en el checkpoint | Se salta silenciosamente |

---

## Checkpoint

Archivo `checkpoint.json` en el filesystem del servidor. Registra cada combinación `(rut_empresa, yyyy-mm, nomina, institucion)` completada con estado `OK`.

Si el bot se interrumpe (pod Railway reiniciado, timeout, error), al relanzar la misma sesión salta los ítems ya completados.

**Limitación MVP:** el checkpoint es efímero (Railway no garantiza persistencia de disco entre deploys). Para el MVP esto es aceptable — se puede reejecutar.

---

## Navegación interna en Previred

Flujo que automatiza el bot por cada empresa × período × nómina:

```
/wPortal/CtrlFce  (portal principal)
  → /wEmpresas/CtrlFce  (administrador de empresas)
    → click "Ingresar" (por empresa)
      → click "Remuneraciones"
        → menú lateral: Imprimir Documentos → Planillas Pagadas
          → seleccionar Mes + Año
          → seleccionar Nómina
          → seleccionar Institución: AFP / Todas las Instituciones
          → click "Buscar"
            → por cada fila AFP en resultados:
              → click icono PDF
              → modal: seleccionar "Total Empresa" → click "Imprimir"
              → nueva pestaña /wEmpresas/CtrlPdf
              → descargar PDF
              → cerrar pestaña
```

---

## Deploy en Railway

### Dockerfile

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

### Variables de entorno Railway

| Variable | Uso |
|---|---|
| `SECRET_KEY` | Cifrado de credenciales en session_state (opcional para MVP) |

### Consideraciones

- Filesystem efímero: ZIP se genera en memoria (`io.BytesIO`), no depende de disco persistente
- Un solo pod, sin necesidad de escalar
- Las credenciales de Previred solo viven en `st.session_state` durante la sesión activa y nunca se escriben a disco ni logs

---

## Fuera del alcance (MVP)

- Instituciones distintas a AFP (Isapre, IPS, CCAF, Mutualidad)
- Login con 2FA
- Subida automática a Google Drive u otro storage externo
- Múltiples usuarios concurrentes
- OCR o procesamiento del contenido de los PDFs
- Modificar o subir información en Previred
