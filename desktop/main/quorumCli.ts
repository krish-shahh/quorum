import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";

const PROJECT_ROOT = path.resolve(__dirname, "../../..");

export type SpecKind = "strategy" | "screen";

const SPEC_DIRS: Record<SpecKind, string> = {
  strategy: path.join(PROJECT_ROOT, "strategies"),
  screen: path.join(PROJECT_ROOT, "screens"),
};

// A spec_id becomes a filename (strategies|screens/<id>.yaml) written from
// renderer-supplied input over IPC — validate strictly server-side (not
// just in the UI) so a compromised/buggy renderer can't path-traverse out
// of strategies/ or screens/. Same pattern for both kinds since both id
// grammars are identical (StrategySpec.strategy_id / ScreenSpec.screen_id).
const SPEC_ID_RE = /^[a-z][a-z0-9_]{1,63}$/;

/** Filename stems under strategies/*.yaml or screens/*.yaml — what a
 * spec_id argument to `quorum backtest`/`shadow-sleeve`/`screen` accepts. */
export function listStrategies(kind: SpecKind = "strategy"): string[] {
  try {
    return fs.readdirSync(SPEC_DIRS[kind])
      .filter((f) => f.endsWith(".yaml"))
      .map((f) => f.slice(0, -".yaml".length))
      .sort();
  } catch {
    return [];
  }
}

export function readStrategyFile(specId: string, kind: SpecKind = "strategy"): string | null {
  if (!SPEC_ID_RE.test(specId)) return null;
  try {
    return fs.readFileSync(path.join(SPEC_DIRS[kind], `${specId}.yaml`), "utf-8");
  } catch {
    return null;
  }
}

/** Write (create or overwrite) strategies/<specId>.yaml or screens/<specId>.
 * yaml. Only ever writes the raw YAML text the Research-tab editor holds —
 * schema validation happens naturally the moment the user backtests/runs
 * it (load_strategy/load_screen raises with a clear error), so there's no
 * separate validation path to keep in sync with either closed grammar. */
export function saveStrategy(
  specId: string,
  yamlContent: string,
  kind: SpecKind = "strategy",
): { ok: boolean; error?: string } {
  if (!SPEC_ID_RE.test(specId)) {
    return { ok: false, error: `${kind}_id must be lowercase letters, digits, underscores (start with a letter).` };
  }
  try {
    const dir = SPEC_DIRS[kind];
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${specId}.yaml`), yamlContent, "utf-8");
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
