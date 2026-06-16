import OpenAI from "openai";

let client: OpenAI | null = null;

// Secondary vision model for the optional AI cross-validation path. Anthropic
// stays the source of truth; this only runs when org settings enable it.
export const OPENAI_VISION_MODEL =
  process.env.OPENAI_VISION_MODEL ?? "gpt-4.1";

export function openaiConfigured(): boolean {
  return Boolean(process.env.OPENAI_API_KEY);
}

export function getOpenAI(): OpenAI {
  if (!client) {
    if (!process.env.OPENAI_API_KEY) {
      throw new Error("OPENAI_API_KEY is not set");
    }
    client = new OpenAI();
  }
  return client;
}
