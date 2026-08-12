/**
 * CopilotChat
 * ============
 * Terminal-style EO Decision Copilot chat interface.
 *
 * Design rationale (pre-code critique)
 * --------------------------------------
 * **Generic approach**: Bubble-style chat (iMessage grammar). Every UI kit
 * ships a bubble component. It takes 20 minutes to build and communicates
 * exactly the wrong thing: "this is a conversation between peers."
 *
 * **Why we don't do that**: Emergency managers are not chatting with a friend.
 * They are querying an instrument. Terminal-style interfaces (Linear command
 * palette, Vercel deployment log, GitHub Actions console) share a visual
 * grammar: edge-to-edge, monospace input, no floating shapes, dense
 * information per pixel. That grammar says "this is precise, this is fast,
 * this is for professionals." Bubbles say "casual conversation." The stakes
 * of a disaster response decision make bubbles feel actively wrong.
 *
 * **Loading state**: Three sequential pulsing dots, not a spinner. A spinner
 * is the correct signal for "I am fetching data over a network." Three dots
 * is the universal signal for "something is composing a response." The LLM
 * is composing, not fetching. The signal must match the behaviour.
 *
 * **Map action log**: Permanent audit entry in the chat feed, not a toast.
 * A toast disappears. In a decision-support context the record of "what
 * the map did and why" is part of the evidence trail — it belongs in the
 * conversation log, not floating above it for 3 seconds and vanishing.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import type { MapAction, ChatMessage } from '../types/copilot';
import { useCopilotSuggestions } from '../hooks/useCopilotSuggestions';
import { sendCopilotMessage } from '../services/api';
import './CopilotChat.css';

// ── Module display names (for system messages) ────────────────────────────────

const DISPLAY_NAMES: Record<string, string> = {
  flood:      'Flood',
  wildfire:   'Wildfire',
  landslide:  'Landslide',
  cyclone:    'Cyclone',
  earthquake: 'Earthquake',
};

// ── Props ─────────────────────────────────────────────────────────────────────

interface CopilotChatProps {
  /** Active event identifier — null when no event is selected. */
  eventId:       string | null;
  /** Active disaster module type. */
  disasterType:  string;
  /** Currently selected zone name or id in the map UI. */
  activeZoneId:  string | null;
  /** Called when the LLM response includes a map control command. */
  onMapCommand:  (action: MapAction) => void;
}

// ── ID factory ────────────────────────────────────────────────────────────────

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

// ── Timestamp formatter ───────────────────────────────────────────────────────

function formatTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ── Sub-components ────────────────────────────────────────────────────────────

/** Satellite SVG icon for the empty state. */
function SatelliteIcon() {
  return (
    <svg
      className="copilot__empty-icon"
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2" />
    </svg>
  );
}

/** Send / Enter arrow icon. */
function SendIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12h14M12 5l7 7-7 7" />
    </svg>
  );
}

/** Chevron icon for suggestion chips. */
function ChipArrow() {
  return (
    <svg
      className="copilot__chip-arrow"
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

/** Three sequentially pulsing dots — the LLM "thinking" indicator. */
function PulsingDots() {
  return (
    <span className="copilot__dots" aria-label="Thinking…" role="status">
      <span className="copilot__dot" />
      <span className="copilot__dot" />
      <span className="copilot__dot" />
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CopilotChat({
  eventId,
  disasterType,
  activeZoneId,
  onMapCommand,
}: CopilotChatProps) {
  const [messages,      setMessages]      = useState<ChatMessage[]>(() => {
    // Restore conversation from sessionStorage on mount
    try {
      const raw = sessionStorage.getItem(`copilot-history-${disasterType}`);
      if (raw) {
        const parsed = JSON.parse(raw) as Array<ChatMessage & { timestamp: string }>;
        // Re-hydrate Date objects (JSON serialises them as strings)
        return parsed.map((m) => ({ ...m, timestamp: new Date(m.timestamp) }));
      }
    } catch { /* storage unavailable or quota exceeded — start fresh */ }
    return [];
  });
  const [input,         setInput]         = useState('');
  const [hasSpoken,     setHasSpoken]     = useState(() => {
    // If restored messages include a user message, mark as spoken
    try {
      const raw = sessionStorage.getItem(`copilot-history-${disasterType}`);
      if (raw) {
        const parsed = JSON.parse(raw) as ChatMessage[];
        return parsed.some((m) => m.role === 'user');
      }
    } catch { /* ignore */ }
    return false;
  });
  const scrollAnchorRef                   = useRef<HTMLDivElement>(null);
  const inputRef                          = useRef<HTMLInputElement>(null);
  const prevDisasterRef                   = useRef<string>(disasterType);

  const { suggestions, loading: suggestionsLoading } = useCopilotSuggestions(disasterType);

  // ── Persist messages to sessionStorage on every update ─────────────────────────
  useEffect(() => {
    if (messages.length === 0) return;
    try {
      sessionStorage.setItem(
        `copilot-history-${disasterType}`,
        JSON.stringify(messages.filter((m) => !m.isLoading)), // never persist loading placeholders
      );
    } catch { /* quota exceeded or private browsing — silently skip */ }
  }, [messages, disasterType]);

  // ── Disaster-type switch: clear messages, inject system message ──────────────
  useEffect(() => {
    if (prevDisasterRef.current === disasterType) return;
    prevDisasterRef.current = disasterType;

    const displayName = DISPLAY_NAMES[disasterType] ?? disasterType;
    const sysMsg: ChatMessage = {
      id:        makeId(),
      role:      'system',
      text:      `Switched to ${displayName} module. Ask me anything about this event.`,
      timestamp: new Date(),
    };
    setMessages([sysMsg]);
    setHasSpoken(false);
  }, [disasterType]);

  // ── Auto-scroll to bottom on new messages ───────────────────────────────────
  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  // ── Send message ─────────────────────────────────────────────────────────────
  const handleSend = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !eventId) return;

      setInput('');
      setHasSpoken(true);

      // 1. Append user message immediately
      const userMsg: ChatMessage = {
        id:        makeId(),
        role:      'user',
        text:      trimmed,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);

      // 2. Append loading placeholder
      const loadingId = makeId();
      const loadingMsg: ChatMessage = {
        id:        loadingId,
        role:      'assistant',
        text:      '',
        timestamp: new Date(),
        isLoading: true,
      };
      setMessages((prev) => [...prev, loadingMsg]);

      // 3. Call API
      const { reply, map_action } = await sendCopilotMessage({
        message:       trimmed,
        event_id:      eventId,
        disaster_type: disasterType,
        active_zone:   activeZoneId,
      });

      // 4. Replace loading message with real response (in-place by id)
      const assistantMsg: ChatMessage = {
        id:        loadingId,       // same id → React keeps the element, just updates
        role:      'assistant',
        text:      reply,
        timestamp: new Date(),
        isLoading: false,
        mapAction: map_action ?? undefined,
      };
      setMessages((prev) => prev.map((m) => (m.id === loadingId ? assistantMsg : m)));

      // 5. Fire map command 50ms after message renders so user sees text first
      if (map_action) {
        setTimeout(() => onMapCommand(map_action), 50);
      }
    },
    [eventId, disasterType, activeZoneId, onMapCommand],
  );

  // ── Keyboard: Enter to send ──────────────────────────────────────────────────
  function handleKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend(input);
    }
  }

  // ── Chip click: fill input and send immediately ──────────────────────────────
  function handleChipClick(suggestion: string) {
    void handleSend(suggestion);
  }

  // ── Derived ──────────────────────────────────────────────────────────────────
  const inputHasContent = input.trim().length > 0;
  const isDisabled      = !eventId;

  // Only show messages (not the empty state) when there are non-system messages
  const hasRealMessages = useMemo(
    () => messages.some((m) => m.role !== 'system'),
    [messages],
  );

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="copilot" aria-label="EO Decision Copilot">

      {/* ── Feed ─────────────────────────────────────────────────────────────── */}
      <div className="copilot__feed" role="log" aria-live="polite" aria-label="Conversation">

        {/* No event selected */}
        {isDisabled && (
          <div className="copilot__no-event">
            <p className="copilot__no-event-text">
              Select a disaster event to start the conversation.
            </p>
          </div>
        )}

        {/* Empty state with suggestions — shown before first user message */}
        {!isDisabled && !hasRealMessages && (
          <div className="copilot__empty">
            <SatelliteIcon />
            <p className="copilot__empty-label">
              Ask me anything about this disaster event.
            </p>
            {!suggestionsLoading && suggestions.length > 0 && (
              <div
                className={`copilot__suggestions ${hasSpoken ? 'copilot__suggestions--hidden' : ''}`}
              >
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="copilot__chip"
                    onClick={() => handleChipClick(s)}
                    disabled={isDisabled}
                  >
                    <ChipArrow />
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Conversation messages */}
        {messages.length > 0 && (
          <div className="copilot__messages">
            {messages.map((msg) => {
              // ── System message ─────────────────────────────────────────────
              if (msg.role === 'system') {
                return (
                  <div key={msg.id} className="copilot__msg--system">
                    <span className="copilot__msg-system-text">{msg.text}</span>
                  </div>
                );
              }

              // ── User message ───────────────────────────────────────────────
              if (msg.role === 'user') {
                return (
                  <div key={msg.id} className="copilot__msg--user">
                    <div className="copilot__msg-user-text">{msg.text}</div>
                    <div className="copilot__msg-time">{formatTime(msg.timestamp)}</div>
                  </div>
                );
              }

              // ── Assistant message ──────────────────────────────────────────
              return (
                <div key={msg.id} className="copilot__msg--assistant">
                  <div className="copilot__msg-assistant-text">
                    {msg.isLoading ? <PulsingDots /> : msg.text}
                  </div>
                  {!msg.isLoading && (
                    <>
                      <div className="copilot__msg-time">{formatTime(msg.timestamp)}</div>
                      {msg.mapAction && (
                        <div className="copilot__map-action-log">
                          {'↗ Map updated · '}
                          {msg.mapAction.target ?? msg.mapAction.layer ?? msg.mapAction.action}
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Auto-scroll anchor */}
        <div ref={scrollAnchorRef} className="copilot__scroll-anchor" aria-hidden="true" />
      </div>

      {/* ── Input Area ─────────────────────────────────────────────────────── */}
      <div className={`copilot__input-area${isDisabled ? ' copilot__input-area--disabled' : ''}`}>
        <div className="copilot__input-wrap">
          <input
            ref={inputRef}
            className="copilot__input"
            type="text"
            placeholder="Ask about this disaster event..."
            value={input}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isDisabled}
            aria-label="Copilot input"
            autoComplete="off"
            spellCheck={false}
            maxLength={500}
          />
        </div>
        <button
          type="button"
          className={`copilot__send${inputHasContent ? ' copilot__send--visible' : ''}`}
          onClick={() => void handleSend(input)}
          aria-label="Send message"
          tabIndex={inputHasContent ? 0 : -1}
        >
          <SendIcon />
        </button>
      </div>
    </div>
  );
}
