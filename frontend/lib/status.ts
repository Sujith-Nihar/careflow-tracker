/**
 * How a derived status is shown to staff.
 *
 * Severity maps to the reserved status palette. Colour never carries the meaning on
 * its own: every badge ships a dot, a word, and a plain-language label, because two
 * of the four status hues sit below 3:1 on a light surface.
 */

export type Tone = "good" | "warning" | "serious" | "critical" | "neutral";

export const STATUS_LABEL: Record<string, string> = {
  completed_scheduled: "Appointment booked",
  completed_transferred: "Reached triage nurse",
  closed_by_staff: "Closed by staff",
  callback_pending: "Callback owed",
  scheduling_incomplete: "Booking not made",
  callback_failed: "Callback not created",
  routing_gap: "Not routed to triage",
  escalation_failed: "Nobody is coming",
  no_action_recorded: "Nothing happened",
  needs_review: "Needs review",
  in_progress: "Call in progress",
};

/** One short sentence a staff member can act on without reading the detail page. */
export const STATUS_MEANING: Record<string, string> = {
  completed_scheduled: "The scheduler confirmed an appointment.",
  completed_transferred: "The triage line answered and took the caller.",
  closed_by_staff: "A staff member completed the callback.",
  callback_pending: "The transfer failed. A callback is queued and unanswered.",
  scheduling_incomplete: "Scheduling was attempted but no appointment exists.",
  callback_failed: "A callback was attempted and the queue refused it.",
  routing_gap: "A post-operative concern never reached triage.",
  escalation_failed: "Neither the transfer nor the callback worked. Nothing is queued.",
  no_action_recorded: "The call ended with nothing attempted.",
  needs_review: "The evidence does not match a known pattern.",
  in_progress: "The call has not finished.",
};

export function toneForSeverity(severity: number): Tone {
  if (severity >= 4) return "critical";
  if (severity === 3) return "critical";
  if (severity === 2) return "serious";
  if (severity === 1) return "warning";
  return "good";
}

export function severityWord(severity: number): string {
  return (
    { 0: "settled", 1: "routine", 2: "urgent", 3: "high", 4: "critical" }[severity] ??
    `severity ${severity}`
  );
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status.replace(/_/g, " ");
}

export function intentLabel(intent: string | null): string {
  if (!intent) return "Not classified";
  return { routine_scheduling: "Routine scheduling", post_operative_concern: "Post-operative concern", other: "Other" }[intent] ?? intent.replace(/_/g, " ");
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
