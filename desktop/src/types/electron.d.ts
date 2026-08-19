export {};

declare global {
  interface Window {
    electronAPI: {
      flaskPort: number;
      platform: string;
      askClaude(
        question: string,
        context: string | undefined,
        onChunk: (text: string) => void,
        resumeSessionId?: string
      ): Promise<{ text: string; sessionId: string | null }>;
      generateSpecYaml(
        kind: "strategy",
        specId: string,
        description: string,
        existingYaml: string | undefined,
        onChunk: (text: string) => void,
        opts?: { resumeSessionId?: string; retryError?: string; model?: string }
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
