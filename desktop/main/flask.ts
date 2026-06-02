import { spawn, ChildProcess } from "child_process";
import * as path from "path";
import * as http from "http";

let flaskProcess: ChildProcess | null = null;

const FLASK_PORT = 5050;
const PROJECT_ROOT = path.resolve(__dirname, "../../..");

export function startFlask(): void {
  const pythonPath = process.env.PYTHON_PATH || "python";

  flaskProcess = spawn(pythonPath, ["-m", "quorum.api"], {
    cwd: PROJECT_ROOT,
    env: { ...process.env, FLASK_ENV: "production", PYTHONDONTWRITEBYTECODE: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });

  flaskProcess.stdout?.on("data", (data: Buffer) => {
    console.log(`[flask] ${data.toString().trim()}`);
  });

  flaskProcess.stderr?.on("data", (data: Buffer) => {
    console.error(`[flask] ${data.toString().trim()}`);
  });

  flaskProcess.on("exit", (code) => {
    console.log(`[flask] process exited with code ${code}`);
    flaskProcess = null;
  });
}

export function stopFlask(): void {
  if (!flaskProcess) return;

  flaskProcess.kill("SIGTERM");

  setTimeout(() => {
    if (flaskProcess && !flaskProcess.killed) {
      flaskProcess.kill("SIGKILL");
    }
  }, 3000);
}

export function waitForFlask(timeoutMs = 30000): Promise<void> {
  const start = Date.now();
  let settled = false;

  return new Promise((resolve, reject) => {
    const check = () => {
      if (settled) return;
      if (Date.now() - start > timeoutMs) {
        settled = true;
        reject(new Error("Flask failed to start within timeout"));
        return;
      }

      const req = http.get(`http://localhost:${FLASK_PORT}/api/v1/health`, (res) => {
        if (settled) { res.resume(); return; }
        if (res.statusCode === 200) {
          settled = true;
          res.resume();
          resolve();
        } else {
          res.resume();
          setTimeout(check, 500);
        }
      });

      req.on("error", () => {
        if (!settled) setTimeout(check, 500);
      });

      req.setTimeout(5000, () => {
        req.destroy();
        if (!settled) setTimeout(check, 500);
      });
    };

    setTimeout(check, 1000);
  });
}
