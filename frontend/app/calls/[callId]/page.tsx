import Link from "next/link";
import { getCall, type CallDetail, type Execution } from "@/lib/api";
import { markCallbackCompleted } from "./actions";

export const dynamic = "force-dynamic";

const ACTION_LABEL: Record<string, string> = {
  schedule_appointment: "Book an appointment",
  transfer_triage: "Transfer to the triage nurse",
  create_callback: "Request a callback",
  report_disposition: "Agent's own account of the call",
};

const OUTCOME_LABEL: Record<string, string> = {
  succeeded: "worked",
  failed: "failed",
  unverified: "could not be confirmed",
  rejected: "refused: details unreadable",
  not_applicable: "not needed",
  requested: "still running",
};

const SAID_LABEL: Record<string, string> = {
  promised_transfer: "Told the caller they were being transferred",
  promised_callback: "Told the caller someone would call them back",
  promised_appointment: "Told the caller an appointment was made",
  disclosed_transfer_failed: "Told the caller the transfer did not complete",
  disclosed_callback_failed: "Told the caller no callback could be arranged",
  disclosed_scheduling_failed: "Told the caller the booking was not confirmed",
  reported_disposition: "Reported the call as",
};

function whatHappened(detail: CallDetail): string[] {
  const lines: string[] = [];
  for (const t of detail.downstream.transfer_sessions) {
    lines.push(
      t.status === "connected"
        ? "The triage line answered."
        : `The triage line did not answer (${t.failure_reason ?? t.status}).`,
    );
  }
  for (const c of detail.downstream.callback_requests) {
    lines.push(
      c.status === "completed"
        ? `${c.priority === "urgent" ? "An urgent" : "A normal-priority"} callback was completed by staff.`
        : `${c.priority === "urgent" ? "An urgent" : "A normal-priority"} callback request is waiting in the queue.`,
    );
  }
  for (const a of detail.downstream.appointments) {
    lines.push(a.status === "booked" ? "An appointment exists in the scheduler." : "No appointment exists.");
  }
  const attempted = detail.action_executions.filter(
    (e) => e.kind !== "report_disposition" && !e.duplicate_of_id,
  );
  for (const e of attempted) {
    if (["failed", "unverified", "rejected"].includes(e.outcome)) {
      lines.push(`${ACTION_LABEL[e.kind] ?? e.kind}: ${OUTCOME_LABEL[e.outcome] ?? e.outcome}.`);
    }
  }
  if (lines.length === 0) lines.push("Nothing was attempted and nothing exists.");
  return lines;
}

export default async function CallDetailPage({
  params,
}: {
  params: Promise<{ callId: string }>;
}) {
  const { callId } = await params;
  let detail: CallDetail;
  try {
    detail = await getCall(callId);
  } catch (e) {
    return (
      <div className="panel">
        <strong>This call could not be loaded.</strong>
        <p className="muted">{e instanceof Error ? e.message : String(e)}</p>
        <p><Link href="/calls">Back to the list</Link></p>
      </div>
    );
  }

  const d = detail.derived;
  const openCallback = detail.downstream.callback_requests.find((c) => c.status === "created");
  const promises = detail.agent_statements.filter((s) => s.kind.startsWith("promised_"));
  const disclosures = detail.agent_statements.filter((s) => s.kind.startsWith("disclosed_"));
  const disposition = detail.agent_statements.find((s) => s.kind === "reported_disposition");

  return (
    <>
      <p className="sub"><Link href="/calls">← Calls needing attention</Link></p>
      <h1>{detail.intent.agent_classified?.replace(/_/g, " ") ?? "Call"}</h1>
      <p className="sub">
        {detail.call.ended_at
          ? new Date(detail.call.ended_at).toLocaleString()
          : detail.call.lifecycle === "in_progress"
            ? "still in progress"
            : "end time not recorded"}
        {detail.call.connected_seconds != null && ` · ${detail.call.connected_seconds}s on the call`}
      </p>

      <div className="panel">
        <div>
          <strong>{d?.reason ?? "No status derived."}</strong>{" "}
          {d && <span className={`tag sev-${d.severity}`}>severity {d.severity}</span>}
          {d?.promise_mismatch && <> <span className="tag mismatch">agent said otherwise</span></>}
        </div>
        {d?.requires_staff_action && (
          <p style={{ margin: "10px 0 0" }}>
            <strong>Do this next:</strong> {d.next_step}
          </p>
        )}
        {d?.mismatch_details?.length ? (
          <ul style={{ margin: "10px 0 0" }}>
            {d.mismatch_details.map((m) => <li key={m}>{m}</li>)}
          </ul>
        ) : null}
      </div>

      {openCallback && (
        <form action={markCallbackCompleted} style={{ marginTop: 16 }}>
          <input type="hidden" name="callId" value={detail.call.id} />
          <input type="hidden" name="callbackId" value={openCallback.id} />
          <input type="hidden" name="actor" value="front-desk" />
          <button type="submit">I have called this patient back</button>
        </form>
      )}

      <h2>What the agent said, and what actually happened</h2>
      <div className="grid2">
        <div className="panel">
          <strong>The agent told the caller</strong>
          {promises.length === 0 && disclosures.length === 0 && !disposition && (
            <p className="muted">Nothing that asserted an outcome.</p>
          )}
          <ul>
            {promises.map((s) => (
              <li key={s.sequence_no + s.kind}>{SAID_LABEL[s.kind] ?? s.kind}</li>
            ))}
            {disclosures.map((s) => (
              <li key={s.sequence_no + s.kind} className="muted">{SAID_LABEL[s.kind] ?? s.kind}</li>
            ))}
            {disposition && (
              <li>
                {SAID_LABEL.reported_disposition} <strong>{disposition.disposition}</strong>
              </li>
            )}
          </ul>
          <p className="muted" style={{ fontSize: 13 }}>
            From the call recording. Evidence of what was said, never of what was done.
          </p>
        </div>

        <div className="panel">
          <strong>The systems recorded</strong>
          <ul>
            {whatHappened(detail).map((line) => <li key={line}>{line}</li>)}
          </ul>
          <p className="muted" style={{ fontSize: 13 }}>
            From the function results and the state of the scheduler, triage line and callback queue.
            This is what decides the status.
          </p>
        </div>
      </div>

      <h2>Every action, in order</h2>
      <table>
        <thead>
          <tr><th>Action</th><th>Result</th><th>Attempts</th><th>Reference</th><th>Requested</th></tr>
        </thead>
        <tbody>
          {detail.action_executions.length === 0 && (
            <tr><td colSpan={5} className="muted">No action was ever attempted on this call.</td></tr>
          )}
          {detail.action_executions.map((e: Execution) => (
            <tr key={e.id}>
              <td>
                {ACTION_LABEL[e.kind] ?? e.kind}
                {e.duplicate_of_id && <> <span className="tag">repeat delivery</span></>}
              </td>
              <td>{OUTCOME_LABEL[e.outcome] ?? e.outcome}</td>
              <td className="muted">
                {(e.attempts ?? []).map((a) => `#${a.attempt_no} ${a.result} ${a.latency_ms}ms`).join(", ") || "—"}
              </td>
              <td className="mono muted">{e.downstream_ref ?? "—"}</td>
              <td className="muted">{e.requested_at ? new Date(e.requested_at).toLocaleTimeString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Trace</h2>
      <table>
        <tbody>
          <tr><th>Call</th><td className="mono">{detail.call.id}</td></tr>
          <tr><th>Vogent dial</th><td className="mono">{detail.call.dial_id}</td></tr>
          <tr><th>Agent version</th><td className="mono">{detail.call.versioned_prompt_id ?? "—"}</td></tr>
          <tr><th>Scenario</th><td className="mono">{detail.call.scenario_id ?? "—"}</td></tr>
          <tr><th>Evaluation run</th><td className="mono">{detail.call.evaluation_run_id ?? "—"}</td></tr>
          <tr><th>How the call ended</th><td className="mono">{detail.call.system_result_type ?? "—"}</td></tr>
        </tbody>
      </table>

      <h2>Transcript</h2>
      <p className="muted" style={{ marginTop: 0 }}>{detail.transcript.note}</p>
      <pre>
        {detail.transcript.segments
          .filter((s) => (s.text ?? "").trim())
          .map((s) => `${s.speaker}: ${s.text}`)
          .join("\n") || "No transcript was captured."}
      </pre>

      <h2>Function payloads</h2>
      <details>
        <summary className="muted">Show the exact requests and responses</summary>
        <pre>{JSON.stringify(detail.action_executions.map((e) => ({
          kind: e.kind, outcome: e.outcome, request: e.request_payload, response: e.response_payload,
        })), null, 2)}</pre>
      </details>
    </>
  );
}
