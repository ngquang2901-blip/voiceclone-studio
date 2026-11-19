const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("shell", {
  onStatus: (fn) => ipcRenderer.on("status", (_, s) => fn(s)),
  retry: () => ipcRenderer.invoke("retry"),
  openLogs: () => ipcRenderer.invoke("open-logs"),
  quit: () => ipcRenderer.invoke("quit"),
});
