import Link from "next/link";
import { listCalls, type CallSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Plain-language labels. Staff should never have to learn our internal vocabulary. */
const STATUS_LABEL: Record<string, string> = {
  completed_scheduled: "Appointment booked",
  completed_transferred: "Reached triage nurse",
  callback_pending: "Callback owed",
  escalation_failed: "Nobody is coming",
  scheduling_incomplete: "Booking not made",
  callback_failed: "Callback not created",
  routing_gap: "Not routed to triage",
  no_action_recorded: "Nothing happened",
  closed_by_staff: "Closed by staff",
  needs_review: "Needs review",
  in_progress: "Call in progress",
};

export default async function CallsPage({
  searchParams,
}: {
  searchParams: Promise<{ all?: string }>;
}) {
  const params = await searchParams;
  const showAll = params.all === "1";

  let calls: CallSummary[] = [];
  let error: string | null = null;
  try {
    calls = await listCalls(!showAll);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <>
      <h1>{showAll ? "All calls" : "Calls needing attention"}</h1>
      <p className="sub">
        Ordered by how urgent the evidence says they are, not by what the agent said.{" "}
        <Link href={showAll ? "/calls" : "/calls?all=1"}>
          {showAll ? "Show only calls needing attention" : "Show all calls"}
        </Link>
      </p>

      {error && (
        <div className="panel">
          <strong>The evidence API could not be reached.</strong>
          <p className="muted">{error}</p>
          <p className="muted">Start it with <span className="mono">make api</span>.</p>
        </div>
      )}

      {!error && calls.length === 0 && (
        <div className="panel">
          <strong>No calls need attention.</strong>
          <p className="muted">
            That means no call has evidence of an unfinished action, not that every caller was
            helped. A call with nothing recorded would appear here.
          </p>
        </div>
      )}

      {calls.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Caller wanted</th>
              <th>What actually happened</th>
              <th>Do this next</th>
              <th>Scenario</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((call) => (
              <tr key={call.call_id}>
                <td className="muted">
                  {call.ended_at
                    ? new Date(call.ended_at).toLocaleString()
                    : call.lifecycle === "in_progress"
                      ? "still in progress"
                      : "time not recorded"}
                </td>
                <td>{call.agent_classified_intent?.replace(/_/g, " ") ?? "unknown"}</td>
                <td>
                  <Link href={`/calls/${call.call_id}`}>
                    {STATUS_LABEL[call.derived.status] ?? call.derived.status}
                  </Link>{" "}
                  <span className={`tag sev-${call.derived.severity}`}>
                    severity {call.derived.severity}
                  </span>
                  {call.derived.promise_mismatch && (
                    <>
                      {" "}
                      <span className="tag mismatch">agent said otherwise</span>
                    </>
                  )}
                </td>
                <td>{call.derived.requires_staff_action ? call.derived.next_step : "—"}</td>
                <td className="mono muted">{call.scenario_id ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
