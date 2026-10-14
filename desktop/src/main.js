const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { spawn } = require("child_process");
const { app, BrowserWindow, dialog, ipcMain, net, protocol, shell } = require("electron");
const { autoUpdater } = require("electron-updater");

protocol.registerSchemesAsPrivileged([
  { scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true } }
]);

const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173";
let mainWindow;
let workerProcess;
let workerBuffer = "";
let activeOutputPath = "";
let updateTimer;
let updateAvailable = null;
let updateDownloaded = null;
let updateDownloading = false;

function rendererRoot() {
  return path.join(__dirname, "..", "dist-ui");
}

function registerRendererProtocol() {
  if (!app.isPackaged) return;
  protocol.handle("app", (request) => {
    const requestUrl = new URL(request.url);
    const requestedPath = decodeURIComponent(requestUrl.pathname);
    const relativePath = requestedPath === "/" ? "index.html" : requestedPath.replace(/^\/+/, "");
    const filePath = path.normalize(path.join(rendererRoot(), relativePath));
    const relativeToRoot = path.relative(path.normalize(rendererRoot()), filePath);
    if (relativeToRoot.startsWith("..") || path.isAbsolute(relativeToRoot)) {
      return new Response("Not found", { status: 404 });
    }
    return net.fetch(pathToFileURL(filePath).toString());
  });
}

function appRoot() {
  return app.isPackaged ? path.join(process.resourcesPath, "app") : path.resolve(__dirname, "..", "..");
}

function workerPath() {
  return path.join(appRoot(), "desktop_backend", "worker.py");
}

function pythonCommand() {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  if (app.isPackaged) {
    const runtimeRoot = path.join(process.resourcesPath, "python-runtime");
    const candidates = process.platform === "win32"
      ? [path.join(runtimeRoot, "python.exe"), path.join(runtimeRoot, "Scripts", "python.exe")]
      : [path.join(runtimeRoot, "bin", "python")];
    const bundled = candidates.find((candidate) => fs.existsSync(candidate));
    if (bundled) return bundled;
  }
  const developmentCandidates = process.platform === "win32"
    ? [path.join(appRoot(), ".venv", "Scripts", "python.exe")]
    : [path.join(appRoot(), ".venv", "bin", "python")];
  const developmentPython = developmentCandidates.find((candidate) => fs.existsSync(candidate));
  if (developmentPython) return developmentPython;
  return process.platform === "win32" ? "python" : "python3";
}

function workerEnv() {
  // Windows otherwise inherits the active ANSI code page for redirected
  // stdio. The worker protocol is JSON-lines and Electron always decodes it
  // as UTF-8, so both sides must use the same encoding.
  const env = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8"
  };
  if (app.isPackaged) {
    const browsersPath = path.join(process.resourcesPath, "ms-playwright");
    if (fs.existsSync(browsersPath)) env.PLAYWRIGHT_BROWSERS_PATH = browsersPath;
  }
  return env;
}

function sendWorkerEvent(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("worker:event", payload);
}

function startWorker() {
  if (workerProcess) return workerProcess;
  const python = pythonCommand();
  workerBuffer = "";
  workerProcess = spawn(python, [workerPath()], {
    cwd: appRoot(),
    env: workerEnv(),
    windowsHide: true,
    stdio: ["pipe", "pipe", "pipe"]
  });

  workerProcess.stdout.setEncoding("utf8");
  workerProcess.stderr.setEncoding("utf8");
  workerProcess.stdout.on("data", (chunk) => {
    workerBuffer += chunk;
    const lines = workerBuffer.split(/\r?\n/);
    workerBuffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        sendWorkerEvent(JSON.parse(line));
      } catch {
        sendWorkerEvent({ type: "log", message: line });
      }
    }
  });
  workerProcess.stderr.on("data", (chunk) => {
    sendWorkerEvent({ type: "log", level: "error", message: chunk.trim() });
  });
  workerProcess.on("error", (error) => {
    sendWorkerEvent({ type: "error_fatal", message: `No se pudo iniciar Python: ${error.message}` });
  });
  workerProcess.on("exit", (code) => {
    workerProcess = null;
    sendWorkerEvent({ type: "worker_exit", code });
  });
  return workerProcess;
}

function sendCommand(command) {
  const worker = startWorker();
  if (!worker.stdin.destroyed) worker.stdin.write(`${JSON.stringify(command)}\n`);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1220,
    height: 850,
    minWidth: 980,
    minHeight: 700,
    title: "Previred Downloader",
    icon: path.join(__dirname, "..", "build", "icon.png"),
    backgroundColor: "#f6f7fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

async function showApp() {
  createWindow();
  if (app.isPackaged) await mainWindow.loadURL("app://renderer/index.html");
  else await mainWindow.loadURL(DEV_SERVER_URL);
  setupAutoUpdates();
}

function sendUpdateEvent(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("update:event", payload);
}

function setupAutoUpdates() {
  if (!app.isPackaged || updateTimer) return;
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on("checking-for-update", () => sendUpdateEvent({ type: "checking", message: "Buscando actualizaciones..." }));
  autoUpdater.on("update-available", (info) => {
    updateAvailable = info;
    updateDownloaded = null;
    sendUpdateEvent({ type: "available", version: info.version, message: `Actualizacion ${info.version} disponible.` });
  });
  autoUpdater.on("update-not-available", () => {
    updateAvailable = null;
    sendUpdateEvent({ type: "not-available", message: "Estas usando la ultima version." });
  });
  autoUpdater.on("download-progress", (progress) => sendUpdateEvent({
    type: "downloading", percent: progress.percent, message: `Descargando ${Math.round(progress.percent || 0)}%`
  }));
  autoUpdater.on("update-downloaded", (info) => {
    updateDownloading = false;
    updateDownloaded = info;
    sendUpdateEvent({ type: "downloaded", version: info.version, message: "Actualizacion lista para instalar." });
  });
  autoUpdater.on("error", (error) => {
    updateDownloading = false;
    sendUpdateEvent({ type: "error", message: `Error de actualizacion: ${error.message}` });
  });
  autoUpdater.checkForUpdates().catch(() => {});
  updateTimer = setInterval(() => autoUpdater.checkForUpdates().catch(() => {}), 4 * 60 * 60 * 1000);
}

ipcMain.handle("app:getInfo", async () => ({ version: app.getVersion(), packaged: app.isPackaged }));
ipcMain.handle("worker:login", async (_event, credentials) => {
  if (!credentials?.rut || !credentials?.password) return { ok: false, message: "Ingresa RUT y contraseña." };
  sendCommand({ type: "login", rut: credentials.rut, password: credentials.password });
  return { ok: true };
});
ipcMain.handle("worker:discover", async (_event, options) => {
  if (!options?.rut || !options?.desde || !options?.hasta) return { ok: false, message: "Completa la empresa y el rango de periodos." };
  sendCommand({ type: "discover", ...options });
  return { ok: true };
});
ipcMain.handle("worker:download", async (_event, selected) => {
  if (!Array.isArray(selected) || selected.length === 0) return { ok: false, message: "Selecciona al menos una nomina." };
  activeOutputPath = path.join(app.getPath("temp"), `previred-${Date.now()}-${crypto.randomBytes(4).toString("hex")}.zip`);
  sendCommand({ type: "download", selected, outputPath: activeOutputPath });
  return { ok: true, outputPath: activeOutputPath };
});
ipcMain.handle("worker:cancel", async () => {
  if (workerProcess && !workerProcess.stdin.destroyed) sendCommand({ type: "cancel" });
  return { ok: true };
});
ipcMain.handle("file:saveResult", async (_event, sourcePath) => {
  if (!sourcePath || !fs.existsSync(sourcePath)) return { ok: false, message: "No hay un ZIP disponible." };
  const result = await dialog.showSaveDialog(mainWindow, {
    title: "Guardar planillas",
    defaultPath: "planillas_previred.zip",
    filters: [{ name: "Archivo ZIP", extensions: ["zip"] }]
  });
  if (result.canceled || !result.filePath) return { ok: false, canceled: true };
  fs.copyFileSync(sourcePath, result.filePath);
  return { ok: true, filePath: result.filePath };
});
ipcMain.handle("update:check", async () => {
  if (!app.isPackaged) return { ok: false, message: "Disponible solo en la aplicacion instalada." };
  try { await autoUpdater.checkForUpdates(); return { ok: true }; }
  catch (error) { return { ok: false, message: error.message }; }
});
ipcMain.handle("update:download", async () => {
  if (!updateAvailable) return { ok: false, message: "No hay una actualizacion disponible." };
  if (updateDownloading) return { ok: true };
  updateDownloading = true;
  try { await autoUpdater.downloadUpdate(); return { ok: true }; }
  catch (error) { updateDownloading = false; return { ok: false, message: error.message }; }
});
ipcMain.handle("update:install", async () => {
  if (!updateDownloaded) return { ok: false, message: "La actualizacion aun no esta lista." };
  if (workerProcess) sendCommand({ type: "shutdown" });
  setImmediate(() => autoUpdater.quitAndInstall(false, true));
  return { ok: true };
});

const hasLock = app.requestSingleInstanceLock();
if (!hasLock) app.quit();
else {
  app.on("second-instance", () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });
  app.whenReady().then(async () => {
    registerRendererProtocol();
    await showApp();
    startWorker();
  }).catch((error) => {
    dialog.showErrorBox("Previred Downloader", error.message);
    app.quit();
  });
}

app.on("before-quit", () => {
  if (updateTimer) clearInterval(updateTimer);
  if (workerProcess) workerProcess.kill();
});
app.on("window-all-closed", () => app.quit());
