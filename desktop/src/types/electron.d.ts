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
      generateStrategyYaml(
        strategyId: string,
        description: string,
        existingYaml: string | undefined,
        onChunk: (text: string) => void
      ): Promise<{ text: string; sessionId: string | null }>;
      listStrategies(): Promise<string[]>;
      readStrategyFile(strategyId: string): Promise<string | null>;
      saveStrategy(strategyId: string, yamlContent: string): Promise<{ ok: boolean; error?: string }>;
      runQuorumCommand(
        args: string[],
        onChunk: (text: string) => void
      ): Promise<{ output: string; exitCode: number | null }>;
    };
  }
}
