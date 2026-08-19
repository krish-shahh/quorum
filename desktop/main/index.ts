import { app, BrowserWindow, ipcMain } from "electron";
import * as path from "path";
import { startFlask, stopFlask, waitForFlask } from "./flask";
import { askClaude } from "./claude";

let mainWindow: BrowserWindow | null = null;

const isDev = !app.isPackaged;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: "#ffffff",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

ipcMain.handle("claude:ask", async (event, requestId: string, question: string, context?: string) => {
  return askClaude(question, context, (chunk) => {
    event.sender.send(`claude:chunk:${requestId}`, chunk);
  });
});

app.on("ready", async () => {
  startFlask();
  await waitForFlask();
  createWindow();
});

app.on("window-all-closed", () => {
  stopFlask();
  app.quit();
});

app.on("before-quit", () => {
  stopFlask();
});
