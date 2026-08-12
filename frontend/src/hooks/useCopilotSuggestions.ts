/**
 * useCopilotSuggestions
 * =====================
 * Fetches prompt suggestion chips for the active disaster module.
 * Cancels in-flight requests when disasterType changes so a fast
 * module switcher never shows stale suggestions from the previous type.
 *
 * Generic approach critique:
 * A naive useEffect + setState fetches the new type and *also* applies
 * the result of any pending request from the previous type — producing
 * a flash of wrong suggestions. AbortController solves this: the cleanup
 * function fires before the next effect runs, cancelling the stale request
 * before its `.then()` can touch state.
 */

import { useEffect, useState } from 'react';
import { getCopilotSuggestions } from '../services/api';

const DEFAULT_SUGGESTIONS = [
  'Which district should receive rescue boats first?',
  'How many hospitals have lost road access?',
  'Draft an emergency alert for the highest priority zone.',
];

interface UseCopilotSuggestionsResult {
  suggestions: string[];
  loading: boolean;
}

export function useCopilotSuggestions(
  disasterType: string,
): UseCopilotSuggestionsResult {
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_SUGGESTIONS);
  const [loading, setLoading]         = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    getCopilotSuggestions(disasterType)
      .then((result) => {
        if (!cancelled) {
          setSuggestions(result.suggestions);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSuggestions(DEFAULT_SUGGESTIONS);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [disasterType]);

  return { suggestions, loading };
}
