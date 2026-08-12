/**
 * Copilot domain types.
 *
 * Kept separate from src/types/index.ts so the copilot feature can be
 * added/removed without touching the core disaster-intelligence types.
 */

/** A single map control command extracted from an LLM reply. */
export interface MapAction {
  action: 'ZOOM' | 'HIGHLIGHT';
  /** Zone name for ZOOM actions (e.g. "Thrissur"). */
  target?: string;
  /** Infrastructure layer for HIGHLIGHT actions: 'hospitals' | 'roads' | 'bridges'. */
  layer?: string;
}

/** One turn in the copilot conversation feed. */
export interface ChatMessage {
  /** nanoid or Date.now().toString() — used as React key and for in-place updates. */
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  timestamp: Date;
  /** Set on assistant messages that triggered a map action. */
  mapAction?: MapAction;
  /** True while the LLM is still generating — renders the pulsing dots. */
  isLoading?: boolean;
}

/** GET /api/chat/suggestions response. */
export interface CopilotSuggestions {
  suggestions: string[];
  disaster_type: string;
}
