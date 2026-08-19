import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  flaskPort: 5050,
  platform: process.platform,

  /** Ask the live Claude Code bridge one question (read-only MCP tools
   * only — see main/claude.ts). Streams text chunks to onChunk as they
   * arrive and resolves with the full answer. */
  askClaude: (
    question: string,
    context: string | undefined,
    onChunk: (text: string) => void
  ): Promise<string> => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const channel = `claude:chunk:${requestId}`;
    const listener = (_event: unknown, chunk: string) => onChunk(chunk);
    ipcRenderer.on(channel, listener);
    return ipcRenderer
      .invoke("claude:ask", requestId, question, context)
      .finally(() => ipcRenderer.removeListener(channel, listener));
  },

  /** Strategy_id stems available under strategies/*.yaml. */
  listStrategies: (): Promise<string[]> => ipcRenderer.invoke("quorum:list-strategies"),

  /** Raw YAML of an existing strategy file, or null if it doesn't exist. */
  readStrategyFile: (strategyId: string): Promise<string | null> =>
    ipcRenderer.invoke("quorum:read-strategy", strategyId),

  /** Create or overwrite strategies/<strategyId>.yaml with raw YAML text. */
  saveStrategy: (strategyId: string, yamlContent: string): Promise<{ ok: boolean; error?: string }> =>
    ipcRenderer.invoke("quorum:save-strategy", strategyId, yamlContent),

  /** Run a quorum CLI command (e.g. ["backtest", "regime_gate", "--start", "2023-01-01"]).
   * Only ever used for read-only testing tooling from the Research tab —
   * never anything that places a trade. Streams raw stdout/stderr to
   * onChunk and resolves with the full combined output + exit code. */
  runQuorumCommand: (
    args: string[],
    onChunk: (text: string) => void
  ): Promise<{ output: string; exitCode: number | null }> => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const channel = `quorum:chunk:${requestId}`;
    const listener = (_event: unknown, chunk: string) => onChunk(chunk);
    ipcRenderer.on(channel, listener);
    return ipcRenderer
      .invoke("quorum:run", requestId, args)
      .finally(() => ipcRenderer.removeListener(channel, listener));
  },
});
