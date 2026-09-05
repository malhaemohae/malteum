import type { ApiEvent } from './api';
import type { LiveSession } from './workspace-model';

export function hasStoredUtterance(events: ApiEvent[]) {
  return events.some(event => event.kind === 'utterance' && typeof (event.utterance as { text?: unknown } | undefined)?.text === 'string' && Boolean((event.utterance as { text: string }).text.trim()));
}

// ready, progress, partial and judgement events do not mean a final utterance
// is visible. Use the unfiltered transcript, not the selected speaker tab.
export function waitingForTraceUtterance(session: LiveSession) {
  return session.mode === 'trace' && session.status !== 'ended' && session.traceHasUtterances !== false && !session.transcript.some(row => row.text.trim());
}
