export {};

declare global {
  interface Window {
    electronAPI: {
      /** Set when preload.ts's own setup threw (see main/preload.ts); the
       * one signal for "is the bridge broken", instead of guessing from
       * whether an individual method happens to be present. Null when
       * preload initialized cleanly. */
      bridgeError: string | null;
      flaskPort: number;
      platform: string;
      askClaude(
        question: string,
        context: string | undefined,
        onChunk: (text: string) => void,
        resumeSessionId?: string
      ): Promise<{ text: string; sessionId: string | null }>;
      generateSpecYaml(
        kind: "strategy" | "screen",
        specId: string,
        description: string,
        existingYaml: string | undefined,
        onChunk: (text: string) => void,
        opts?: { resumeSessionId?: string; retryError?: string; model?: string },
        onToolUse?: (name: string, input: Record<string, unknown>) => void
      ): Promise<{ text: string; sessionId: string | null }>;
      listStrategies(kind?: "strategy" | "screen"): Promise<string[]>;
      readStrategyFile(specId: string, kind?: "strategy" | "screen"): Promise<string | null>;
      saveStrategy(
        specId: string,
        yamlContent: string,
        kind?: "strategy" | "screen"
      ): Promise<{ ok: boolean; error?: string }>;
      runQuorumCommand(
        args: string[],
        onChunk: (text: string) => void
      ): Promise<{ output: string; exitCode: number | null }>;
    };
  }
}
