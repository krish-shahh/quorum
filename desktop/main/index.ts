import { app, BrowserWindow, ipcMain } from "electron";
import * as path from "path";
import { startFlask, stopFlask, waitForFlask } from "./flask";
import { askClaude, generateSpecYaml } from "./claude";
import { listStrategies, readStrategyFile, runQuorumCommand, saveStrategy } from "./quorumCli";
import { withQueue } from "./queue";

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

// Two headless-process bridges share this pattern (spawn, stream chunks
// over IPC, resolve with the final result) but are queued separately:
// Claude asks are cheap/read-only so a couple can run at once; CLI test
// runs (backtest/shadow-sleeve) fetch data and burn CPU, so only one
// runs at a time — a second request waits for a slot instead of
// contending with the first.
ipcMain.handle("claude:ask", async (
  event, requestId: string, question: string, context: string | undefined, resumeSessionId: string | undefined,
) => {
  return withQueue("claude", 2, () =>
    askClaude(question, context, (chunk) => {
      event.sender.send(`claude:chunk:${requestId}`, chunk);
    }, { resumeSessionId })
  );
});

ipcMain.handle("quorum:list-strategies", async () => listStrategies());
ipcMain.handle("quorum:read-strategy", async (_event, strategyId: string) => readStrategyFile(strategyId));
ipcMain.handle("quorum:save-strategy", async (_event, strategyId: string, yamlContent: string) =>
  saveStrategy(strategyId, yamlContent)
);

ipcMain.handle("claude:generate-spec", async (
  event, requestId: string, kind: "strategy", specId: string, description: string, existingYaml: string | undefined,
  opts: { resumeSessionId?: string; retryError?: string; model?: string } | undefined,
) => {
  return withQueue("claude", 2, () =>
    generateSpecYaml(kind, specId, description, existingYaml, (chunk) => {
      event.sender.send(`claude:chunk:${requestId}`, chunk);
    }, opts)
  );
});

ipcMain.handle("quorum:run", async (event, requestId: string, args: string[]) => {
  return withQueue("quorum-cli", 1, () =>
    runQuorumCommand(args, (chunk) => {
      event.sender.send(`quorum:chunk:${requestId}`, chunk);
    })
  );
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
