export {};

declare global {
  interface Window {
    electronAPI: {
      flaskPort: number;
      platform: string;
      askClaude(
        question: string,
        context: string | undefined,
        onChunk: (text: string) => void
      ): Promise<string>;
    };
  }
}
