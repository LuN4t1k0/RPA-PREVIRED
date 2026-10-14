# Previred Downloader Desktop

Cliente Electron + React que reutiliza el motor Python/Playwright del proyecto sin ejecutar Streamlit ni abrir un navegador externo.

## Desarrollo

```bash
cd desktop
npm install
npm run dev
```

En desarrollo detecta primero el entorno `.venv` de la raíz y luego usa `python3`. Para indicar otro intérprete:

```bash
PYTHON_BIN=/ruta/a/python npm run dev
```

## Distribución

- `npm run pack`: compila la UI y crea un paquete usando un runtime ya preparado.
- `npm run pack:full`: además genera el runtime Python y descarga Chromium.
- `npm run dist -- --win`: genera el instalador NSIS y metadatos del actualizador.

El workflow `desktop-release.yml` ejecuta el build completo en Windows y publica los artefactos en GitHub Releases. La aplicación consulta esas releases con `electron-updater`.

## Arquitectura

```text
Electron main process
  ├─ React renderer (wizard)
  ├─ IPC seguro mediante preload/contextBridge
  └─ Python worker persistente (JSON Lines)
       └─ bot/ existente + Playwright Chromium embebido
```

Las credenciales se envían al worker en memoria y no se persisten. Los resultados se generan primero en un ZIP temporal y el usuario elige dónde guardarlo.

## Smoke test con Docker

La prueba pública no necesita credenciales:

```bash
docker compose -f docker-compose.smoke.yml run --rm previred-smoke \
  python scripts/previred_smoke.py --public-only
```

Para probar login y listado de empresas sin guardar ni compartir la contraseña:

```bash
docker compose -f docker-compose.smoke.yml run --rm previred-smoke
```

Para probar una empresa y un rango completo sin guardar credenciales:

```bash
docker compose -f docker-compose.smoke.yml run --rm previred-smoke \
  python scripts/previred_smoke.py \
  --company-rut 93830000-3 --desde 2019-01 --hasta 2019-12
```

El proceso solicita RUT y contraseña directamente en la terminal. Si falla, deja `failure.png`, `failure.html`, `failure-url.txt` y `trace.zip` en `artifacts/previred-smoke/`.
