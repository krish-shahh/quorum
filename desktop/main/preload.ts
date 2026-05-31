import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  flaskPort: 5050,
  platform: process.platform,
});
