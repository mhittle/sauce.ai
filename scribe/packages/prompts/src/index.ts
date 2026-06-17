// Versioned prompt templates (PRD §4). Bump the version string whenever the
// prompt text changes; takeoffs persist the version they were extracted with
// so eval regressions can be traced to a prompt change.

export * from "./classify.js";
export * from "./extract.js";
export * from "./regions.js";
export * from "./crawler.js";

// Model tiers (PRD §4): Sonnet-tier for classification + extraction vision,
// Haiku-tier for cheap crawler filtering.
export const SONNET_MODEL = "claude-sonnet-4-6";
export const HAIKU_MODEL = "claude-haiku-4-5";
