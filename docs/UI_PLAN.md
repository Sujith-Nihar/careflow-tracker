# Staff Investigation UI Plan

Owner of: the Next.js application scope. Two screens. No charts. Server-side data fetching from the
Flask evidence API; the browser never holds a backend secret.

## Questions the UI must answer in under a minute

Which calls still need a human? What did the agent promise? What actually happened? Why does the call
have this status? What should I do next?

## Screen 1 — `/calls` (attention list)

Default filter `requires_staff_action = true`, sorted by severity desc, then most recent. Toggle to
show all. Columns: time · caller intent · agent promised (from statements) · actual result (from
executions/downstream) · status · next step · scenario (if evaluation call). A red "promise mismatch"
badge when set. Row click → detail.

## Screen 2 — `/calls/[call_id]` (evidence view)

Sections in this order, each labelled with its evidence source:

1. **Summary strip**: status, severity, requires staff action, `reason`, `next_step`.
2. **Promise vs. evidence** — two columns: *Agent said* (statements with timestamps) | *System did*
   (executions with outcome, downstream rows with IDs). Mismatch highlighted.
3. **Timeline**: statements, executions (requested → completed), webhooks, staff actions, interleaved by time.
4. **Actions for staff**: "Mark callback completed" (POST `staff_actions`, then re-fetch), "Mark reviewed".
5. **Technical evidence**: dial ID, versioned prompt ID, agent ID, execution IDs, transfer/callback/
   appointment IDs, function request/response JSON (collapsible).
6. **Transcript**: labelled "Non-authoritative. Shows what was said, not what happened."
7. **Evaluation**: scenario, run, metrics table, when the call came from a run.

## Technical scope

Next.js 15 (App Router), TypeScript, server components fetching `BACKEND_URL` (server-only env var) with
`X-Organization-Id` from a server-side constant for the demo organization. Plain CSS. No component
library. No client state beyond the two buttons. Loading and error states are text.

## Deferred

Organization switcher, authentication, search, pagination beyond `limit`, accessibility audit, mobile layout.
