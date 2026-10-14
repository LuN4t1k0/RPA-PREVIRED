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
