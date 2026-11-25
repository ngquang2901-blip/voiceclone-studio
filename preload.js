// Bridge for the main UI (served by the engine). Only these calls cross into the desktop shell.
const { contextBridge, ipcRenderer } = require("electron");
const arg = (k) => (process.argv.find((a) => a.startsWith(`--${k}=`)) || "").split("=").slice(1).join("=");

contextBridge.exposeInMainWorld("vc", {
  engineUrl: arg("vc-engine"),
  version: arg("vc-version"),
  showItemInFolder: (p) => ipcRenderer.invoke("show-item", p),
  restartEngine: () => ipcRenderer.invoke("restart-engine"),
  onEngineExit: (fn) => ipcRenderer.on("engine-exit", () => fn()),
  checkUpdate: () => ipcRenderer.invoke("update-check"),
  installUpdate: (onProgress) => { ipcRenderer.removeAllListeners("update-progress"); ipcRenderer.on("update-progress", (_, f) => onProgress(f)); return ipcRenderer.invoke("update-install"); },
});
