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
  completed_transferred: "Transferred to the nurse",
  closed_by_staff: "Staff called the patient",
  callback_pending: "Callback waiting",
  scheduling_incomplete: "Booking did not happen",
  callback_failed: "Callback could not be created",
  routing_gap: "Never sent to the nurse",
  escalation_failed: "No one reached the patient",
  no_action_recorded: "Nothing was done",
  needs_review: "Unclear, needs a look",
  in_progress: "Call still going",
};

/** One short sentence a staff member can act on without reading the detail page. */
export const STATUS_MEANING: Record<string, string> = {
  completed_scheduled: "The scheduler confirmed an appointment for this caller.",
  completed_transferred: "The triage nurse picked up and took the caller.",
  closed_by_staff: "A staff member rang this patient back and closed the call.",
  callback_pending: "The transfer did not go through, so a callback is waiting for someone to make.",
  scheduling_incomplete: "The agent tried to book, but there is no appointment.",
  callback_failed: "The agent tried to arrange a callback, and it was not created.",
  routing_gap: "This caller had a surgery concern and was never put through to the nurse.",
  escalation_failed: "The transfer failed and no callback was created. Nobody is going to contact this patient.",
  no_action_recorded: "The call ended without the agent doing anything at all.",
  needs_review: "The records do not match anything we recognise. Read the call.",
  in_progress: "This call has not finished yet.",
};

export function toneForSeverity(severity: number): Tone {
  if (severity >= 4) return "critical";
  if (severity === 3) return "critical";
  if (severity === 2) return "serious";
  if (severity === 1) return "warning";
  return "good";
}

/** Plain urgency words, not a number staff would have to learn a scale for. */
export function severityWord(severity: number): string {
  return (
    { 0: "Done", 1: "When you can", 2: "Today", 3: "Soon", 4: "Now" }[severity] ??
    `Level ${severity}`
  );
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status.replace(/_/g, " ");
}

export function intentLabel(intent: string | null): string {
  if (!intent) return "Not recorded";
  return (
    {
      routine_scheduling: "Booking an appointment",
      post_operative_concern: "Concern after surgery",
      other: "Something else",
    }[intent] ?? intent.replace(/_/g, " ")
  );
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
