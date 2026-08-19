import { validateSpec } from "./api";

export type SpecKind = "strategy" | "screen";

export interface SpecAttempt {
  attempt: number; // 1-based, 1..MAX_ATTEMPTS
  model: "sonnet" | "opus";
  draft: string;
  ok: boolean;
  errors: string[];
}

export interface GenerateValidatedSpecArgs {
  kind: SpecKind;
  specId: string;
  description: string;
  existingYaml?: string;
  /** Called once per attempt as it finishes validating, in order (attempt
   * 1 first) — drives the attempt-strip UI. */
  onAttempt: (attempt: SpecAttempt) => void;
  /** Called with live streamed text for whichever attempt is currently in
   * flight — lets the editor show each draft filling in in real time
   * rather than only revealing a finished attempt, matching the repo's
   * existing bias toward auditable, visible reasoning. */
  onChunk?: (attempt: number, text: string) => void;
}

export interface GenerateValidatedSpecResult {
  /** The LAST draft produced, valid or not — on total failure this is the
   * draft closest to correct, not a blank template. */
  finalText: string;
  ok: boolean;
  attempts: SpecAttempt[];
}

const MAX_ATTEMPTS = 3;

/** Shared generate -> validate -> retry loop, used by both Strategy Lab
 * and the screener panel (Feature B). Ladder: attempt 1 = Sonnet fresh;
 * attempt 2 = Sonnet `--resume` with just the validation error (the
 * resumed session already has full schema/example grounding from attempt
 * 1); attempt 3 = Opus fresh — not resumed, mixing `--resume` with a model
 * change has unverified semantics — with the full error history and the
 * last draft. Stops the moment a draft validates; never throws for a spec
 * that fails all 3 attempts, since the caller still wants the last draft. */
export async function generateValidatedSpec({
  kind, specId, description, existingYaml, onAttempt, onChunk,
}: GenerateValidatedSpecArgs): Promise<GenerateValidatedSpecResult> {
  const attempts: SpecAttempt[] = [];
  const errorHistory: string[] = [];
  let resumeSessionId: string | undefined;
  let lastDraft = "";

  for (let i = 1; i <= MAX_ATTEMPTS; i++) {
    const model: "sonnet" | "opus" = i < MAX_ATTEMPTS ? "sonnet" : "opus";
    const retryError = errorHistory.length ? errorHistory.join("\n\n") : undefined;

    const { text, sessionId } = await window.electronAPI.generateSpecYaml(
      kind, specId, description,
      i === 1 ? existingYaml : lastDraft,
      (chunk) => onChunk?.(i, chunk),
      { model, retryError, resumeSessionId: i === 2 ? resumeSessionId : undefined },
    );
    lastDraft = text;
    if (i === 1 && sessionId) resumeSessionId = sessionId;

    const validation = await validateSpec(kind, text, specId);
    const attempt: SpecAttempt = {
      attempt: i,
      model,
      draft: validation.cleaned_text ?? text,
      ok: validation.ok,
      errors: validation.errors ?? [],
    };
    attempts.push(attempt);
    onAttempt(attempt);

    if (validation.ok) {
      return { finalText: attempt.draft, ok: true, attempts };
    }
    errorHistory.push(`Attempt ${i} (${model}):\n${attempt.errors.join("\n")}`);
  }

  return { finalText: lastDraft, ok: false, attempts };
}
