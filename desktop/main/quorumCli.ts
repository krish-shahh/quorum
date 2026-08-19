import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";

const PROJECT_ROOT = path.resolve(__dirname, "../../..");
const STRATEGIES_DIR = path.join(PROJECT_ROOT, "strategies");

// strategy_id becomes a filename (strategies/<id>.yaml) written from
// renderer-supplied input over IPC — validate strictly server-side (not
// just in the UI) so a compromised/buggy renderer can't path-traverse
// out of strategies/.
const STRATEGY_ID_RE = /^[a-z][a-z0-9_]{1,63}$/;

/** Filename stems under strategies/*.yaml — what a strategy_id argument
 * to `quorum backtest`/`shadow-sleeve` accepts. */
export function listStrategies(): string[] {
  try {
    return fs.readdirSync(STRATEGIES_DIR)
      .filter((f) => f.endsWith(".yaml"))
      .map((f) => f.slice(0, -".yaml".length))
      .sort();
  } catch {
    return [];
  }
}

export function readStrategyFile(strategyId: string): string | null {
  if (!STRATEGY_ID_RE.test(strategyId)) return null;
  try {
    return fs.readFileSync(path.join(STRATEGIES_DIR, `${strategyId}.yaml`), "utf-8");
  } catch {
    return null;
  }
}

/** Write (create or overwrite) strategies/<strategyId>.yaml. Only ever
 * writes the raw YAML text the Research-tab editor holds — schema
 * validation happens naturally the moment the user backtests it
 * (load_strategy raises with a clear error), so there's no separate
 * validation path to keep in sync with schema.py's closed grammar. */
export function saveStrategy(strategyId: string, yamlContent: string): { ok: boolean; error?: string } {
  if (!STRATEGY_ID_RE.test(strategyId)) {
    return { ok: false, error: "strategy_id must be lowercase letters, digits, underscores (start with a letter)." };
  }
  try {
    fs.mkdirSync(STRATEGIES_DIR, { recursive: true });
    fs.writeFileSync(path.join(STRATEGIES_DIR, `${strategyId}.yaml`), yamlContent, "utf-8");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

/** Spawn `python -m cli.main <args>` (same invocation shape as flask.ts's
 * `python -m quorum.api`), streaming combined stdout+stderr to `onChunk`
 * and resolving with the full output once the process exits. Used for
 * read-only testing tooling (backtest, shadow-sleeve) triggered from the
 * Research tab — never anything that places live/paper trades. */
export function runQuorumCommand(
  args: string[],
  onChunk: (text: string) => void,
): Promise<{ output: string; exitCode: number | null }> {
  return new Promise((resolve) => {
    const pythonPath = process.env.PYTHON_PATH || "python";
    const proc = spawn(pythonPath, ["-m", "cli.main", ...args], {
      cwd: PROJECT_ROOT,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", NO_COLOR: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });

    let output = "";
    const onData = (data: Buffer) => {
      const text = data.toString();
      output += text;
      onChunk(text);
    };
    proc.stdout?.on("data", onData);
    proc.stderr?.on("data", onData);

    proc.on("close", (exitCode) => resolve({ output, exitCode }));
  });
}
