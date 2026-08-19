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
});
