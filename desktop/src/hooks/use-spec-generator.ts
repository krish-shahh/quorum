import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import { generateValidatedSpec, type SpecKind, type SpecAttempt } from "@/lib/codegen";
import type { ToolEvent } from "@/components/GenerationProgress";

const ID_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;

/** Shared React orchestration around codegen.ts's generate -> validate ->
 * retry loop (StrategyLab and ScreenerPanel are otherwise near-identical
 * here). Owns the description input, in-flight/attempt/tool-event state,
 * and id validation; the caller still owns the YAML text itself (passed
 * in as `setYamlText`) since that's shared with manual editing/save. */
export function useSpecGenerator(kind: SpecKind) {
  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [attempts, setAttempts] = useState<SpecAttempt[]>([]);
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [expandedAttempt, setExpandedAttempt] = useState<number | null>(null);
  const streamingAttemptRef = useRef(0);

  function isValidId(id: string): boolean {
    return ID_PATTERN.test(id);
  }

  async function generate(
    specId: string,
    existingYaml: string | undefined,
    setYamlText: Dispatch<SetStateAction<string>>,
  ) {
    if (!description.trim() || !isValidId(specId)) return;
    setGenerating(true);
    setAttempts([]);
    setToolEvents([]);
    setExpandedAttempt(null);
    setYamlText("");
    streamingAttemptRef.current = 0;
    try {
      const result = await generateValidatedSpec({
        kind,
        specId,
        description: description.trim(),
        existingYaml,
        onAttempt: (attempt) => setAttempts((prev) => [...prev, attempt]),
        onChunk: (attempt, chunk) => {
          // A new attempt starting replaces the editor's content instead of
          // appending to the previous attempt's draft.
          if (attempt !== streamingAttemptRef.current) {
            streamingAttemptRef.current = attempt;
            setYamlText(chunk);
          } else {
            setYamlText((prev) => prev + chunk);
          }
        },
        onToolUse: (attempt, name, input) =>
          setToolEvents((prev) => [...prev, { attempt, name, input }]),
      });
      setYamlText(result.finalText);
    } finally {
      setGenerating(false);
    }
  }

  return {
    description, setDescription,
    generating,
    attempts,
    toolEvents,
    expandedAttempt, setExpandedAttempt,
    isValidId,
    generate,
  };
}
