import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  flaskPort: 5050,
  platform: process.platform,

  /** Ask the live Claude Code bridge one question (read-only MCP tools
   * only, haiku — see main/claude.ts). Streams text chunks to onChunk as
   * they arrive and resolves with the full answer plus the session_id it
   * ran under. Pass that session_id back as `resumeSessionId` on a
   * follow-up within the SAME thread to continue one real conversation
   * (and its cheaper cached context) instead of a fresh session; omit it
   * to start a new, unrelated thread. */
  askClaude: (
    question: string,
    context: string | undefined,
    onChunk: (text: string) => void,
    resumeSessionId?: string
  ): Promise<{ text: string; sessionId: string | null }> => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const channel = `claude:chunk:${requestId}`;
    const listener = (_event: unknown, chunk: string) => onChunk(chunk);
    ipcRenderer.on(channel, listener);
    return ipcRenderer
      .invoke("claude:ask", requestId, question, context, resumeSessionId)
      .finally(() => ipcRenderer.removeListener(channel, listener));
  },

  /** Generate a strategy YAML from a natural-language description (sonnet,
   * read-only — see main/claude.ts's generateStrategyYaml). Streams raw
   * text to onChunk and resolves with the full YAML text. */
  generateStrategyYaml: (
    strategyId: string,
    description: string,
    existingYaml: string | undefined,
    onChunk: (text: string) => void
  ): Promise<{ text: string; sessionId: string | null }> => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const channel = `claude:chunk:${requestId}`;
    const listener = (_event: unknown, chunk: string) => onChunk(chunk);
    ipcRenderer.on(channel, listener);
    return ipcRenderer
      .invoke("claude:generate-strategy", requestId, strategyId, description, existingYaml)
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
