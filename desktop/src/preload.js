const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopApi", {
  getAppInfo: () => ipcRenderer.invoke("app:getInfo"),
  login: (credentials) => ipcRenderer.invoke("worker:login", credentials),
  discover: (options) => ipcRenderer.invoke("worker:discover", options),
  download: (selected) => ipcRenderer.invoke("worker:download", selected),
  cancel: () => ipcRenderer.invoke("worker:cancel"),
  saveResult: (sourcePath) => ipcRenderer.invoke("file:saveResult", sourcePath),
  checkForUpdates: () => ipcRenderer.invoke("update:check"),
  downloadUpdate: () => ipcRenderer.invoke("update:download"),
  installUpdate: () => ipcRenderer.invoke("update:install"),
  onWorkerEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("worker:event", listener);
    return () => ipcRenderer.removeListener("worker:event", listener);
  },
  onUpdateEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("update:event", listener);
    return () => ipcRenderer.removeListener("update:event", listener);
  }
});
