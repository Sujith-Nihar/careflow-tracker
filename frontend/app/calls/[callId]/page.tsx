import Link from "next/link";
import { Badge } from "@/components/Badge";
import { getCall, type CallDetail, type Execution } from "@/lib/api";
import {
  intentLabel,
  severityWord,
  statusLabel,
  STATUS_MEANING,
  toneForSeverity,
} from "@/lib/status";
import { markCallbackCompleted } from "./actions";

export const dynamic = "force-dynamic";

const ACTION_LABEL: Record<string, string> = {
  schedule_appointment: "Book an appointment",
  transfer_triage: "Transfer to the triage nurse",
  create_callback: "Request a callback",
  report_disposition: "Agent's own account of the call",
};

const OUTCOME: Record<string, { text: string; tone: "good" | "warning" | "critical" | "neutral" }> = {
  succeeded: { text: "worked", tone: "good" },
  failed: { text: "failed", tone: "critical" },
  unverified: { text: "could not be confirmed", tone: "warning" },
  rejected: { text: "refused: details unreadable", tone: "warning" },
  not_applicable: { text: "not needed", tone: "neutral" },
  requested: { text: "still running", tone: "neutral" },
};

const SAID: Record<string, { text: string; icon: string }> = {
  promised_transfer: { text: "Told the caller they were being transferred", icon: "!" },
  promised_callback: { text: "Told the caller someone would call them back", icon: "!" },
  promised_appointment: { text: "Told the caller an appointment was made", icon: "!" },
  disclosed_transfer_failed: { text: "Told the caller the transfer did not complete", icon: "✓" },
  disclosed_callback_failed: { text: "Told the caller no callback could be arranged", icon: "✓" },
  disclosed_scheduling_failed: { text: "Told the caller the booking was not confirmed", icon: "✓" },
};

function recorded(detail: CallDetail): { text: string; tone: "good" | "critical" | "warning" }[] {
  const out: { text: string; tone: "good" | "critical" | "warning" }[] = [];
  for (const t of detail.downstream.transfer_sessions) {
    out.push(
      t.status === "connected"
        ? { text: "The triage line answered.", tone: "good" }
        : { text: `The triage line did not answer (${t.failure_reason ?? t.status}).`, tone: "critical" },
    );
  }
  for (const c of detail.downstream.callback_requests) {
    const priority = c.priority === "urgent" ? "An urgent" : "A normal-priority";
    out.push(
      c.status === "completed"
        ? { text: `${priority} callback was completed by staff.`, tone: "good" }
        : { text: `${priority} callback request is waiting in the queue.`, tone: "warning" },
    );
  }
  for (const a of detail.downstream.appointments) {
    out.push(
      a.status === "booked"
        ? { text: "An appointment exists in the scheduler.", tone: "good" }
        : { text: "No appointment exists.", tone: "critical" },
    );
  }
  const failed = detail.action_executions.filter(
    (e) =>
      e.kind !== "report_disposition" &&
      !e.duplicate_of_id &&
      ["failed", "rejected"].includes(e.outcome),
  );
  for (const e of failed) {
    out.push({
      text: `${ACTION_LABEL[e.kind] ?? e.kind}: ${OUTCOME[e.outcome]?.text ?? e.outcome}.`,
      tone: "critical",
    });
  }
  if (out.length === 0) {
    out.push({ text: "Nothing was attempted and nothing exists.", tone: "critical" });
  }
  return out;
}

function toneVar(tone: string): string {
  return { good: "var(--good)", warning: "var(--warning)", serious: "var(--serious)", critical: "var(--critical)" }[tone] ?? "var(--line-strong)";
}

export default async function CallDetailPage({ params }: { params: Promise<{ callId: string }> }) {
  const { callId } = await params;
  let detail: CallDetail;
  try {
    detail = await getCall(callId);
  } catch (e) {
    return (
      <div className="panel">
        <div className="empty">
          <div className="empty-title">This call could not be loaded</div>
          <p className="empty-note">{e instanceof Error ? e.message : String(e)}</p>
          <p style={{ marginTop: 14 }}>
            <Link href="/calls">Back to the list</Link>
          </p>
        </div>
      </div>
    );
  }

  const d = detail.derived;
  const tone = d ? toneForSeverity(d.severity) : "neutral";
  const openCallback = detail.downstream.callback_requests.find((c) => c.status === "created");
  const spoken = detail.agent_statements.filter((s) => s.kind in SAID);
  const disposition = detail.agent_statements.find((s) => s.kind === "reported_disposition");

  return (
    <>
      <Link className="back" href="/calls">
        ← Calls needing attention
      </Link>

      <div className="page-head">
        <h1>{intentLabel(detail.intent.agent_classified)}</h1>
        <p className="lede">
          {d ? STATUS_MEANING[d.status] ?? statusLabel(d.status) : "No status derived."}
        </p>
      </div>

      <div className="hero" style={{ ["--hero-accent" as string]: toneVar(tone) }}>
        <div className="hero-row">
          <p className="hero-reason">{d?.reason ?? "No status derived for this call."}</p>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {d && <Badge tone={tone}>{severityWord(d.severity)}</Badge>}
            {d && <Badge tone="neutral">{statusLabel(d.status)}</Badge>}
            {d?.promise_mismatch && (
              <Badge tone="critical" alarm>
                agent said otherwise
              </Badge>
            )}
          </div>
        </div>

        {d?.requires_staff_action && (
          <div className="hero-next">
            <span className="hero-next-label">Do this next</span>
            <span>{d.next_step}</span>
          </div>
        )}

        {d?.mismatch_details?.length ? (
          <ul className="claim-list" style={{ marginTop: 12 }}>
            {d.mismatch_details.map((m) => (
              <li key={m}>
                <span className="claim-icon" style={{ color: "var(--critical)" }}>
                  !
                </span>
                <span>{m}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {openCallback && (
          <form action={markCallbackCompleted} style={{ marginTop: 16 }}>
            <input type="hidden" name="callId" value={detail.call.id} />
            <input type="hidden" name="callbackId" value={openCallback.id} />
            <input type="hidden" name="actor" value="front-desk" />
            <button className="btn btn-primary" type="submit">
              I have called this patient back
            </button>
          </form>
        )}
      </div>

      <h2>What was said, and what was done</h2>
      <div className="compare stagger">
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">The agent told the caller</span>
          </div>
          <div className="panel-body">
            {spoken.length === 0 && !disposition ? (
              <p className="muted" style={{ margin: 0 }}>
                Nothing that asserted an outcome.
              </p>
            ) : (
              <ul className="claim-list">
                {spoken.map((s, i) => (
                  <li key={`${s.kind}-${s.sequence_no}-${i}`}>
                    <span
                      className="claim-icon"
                      style={{
                        color: s.kind.startsWith("promised_") ? "var(--warning)" : "var(--good)",
                      }}
                    >
                      {SAID[s.kind].icon}
                    </span>
                    <span>{SAID[s.kind].text}</span>
                  </li>
                ))}
                {disposition && (
                  <li>
                    <span className="claim-icon muted">›</span>
                    <span>
                      Reported the call as <strong>{disposition.disposition}</strong>
                    </span>
                  </li>
                )}
              </ul>
            )}
            <p className="panel-note">
              Taken from the recording. Evidence of what was said, never of what was done.
            </p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">The systems recorded</span>
          </div>
          <div className="panel-body">
            <ul className="claim-list">
              {recorded(detail).map((line) => (
                <li key={line.text}>
                  <span className="claim-icon" style={{ color: toneVar(line.tone) }}>
                    {line.tone === "good" ? "✓" : line.tone === "warning" ? "•" : "✕"}
                  </span>
                  <span>{line.text}</span>
                </li>
              ))}
            </ul>
            <p className="panel-note">
              From the function results and the state of the scheduler, triage line and callback
              queue. This is what decides the status.
            </p>
          </div>
        </section>
      </div>

      <h2>Every action, in order</h2>
      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Result</th>
                <th>Attempts</th>
                <th>Reference</th>
                <th>Requested</th>
              </tr>
            </thead>
            <tbody>
              {detail.action_executions.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No action was ever attempted on this call.
                  </td>
                </tr>
              )}
              {detail.action_executions.map((e: Execution) => {
                const outcome = OUTCOME[e.outcome] ?? { text: e.outcome, tone: "neutral" as const };
                return (
                  <tr key={e.id}>
                    <td>
                      <span className="cell-strong">{ACTION_LABEL[e.kind] ?? e.kind}</span>
                      {e.duplicate_of_id && (
                        <div className="cell-sub">
                          <Badge tone="neutral">repeat delivery</Badge>
                        </div>
                      )}
                    </td>
                    <td>
                      <Badge tone={outcome.tone}>{outcome.text}</Badge>
                    </td>
                    <td className="muted num">
                      {(e.attempts ?? [])
                        .map((a) => `#${a.attempt_no} ${a.result} ${a.latency_ms}ms`)
                        .join(", ") || "—"}
                    </td>
                    <td className="mono">{e.downstream_ref ?? "—"}</td>
                    <td className="muted num">
                      {e.requested_at ? new Date(e.requested_at).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <h2>Trace</h2>
      <div className="panel">
        <div className="panel-body">
          <table className="kv">
            <tbody>
              <tr>
                <th>Call</th>
                <td className="mono">{detail.call.id}</td>
              </tr>
              <tr>
                <th>Vogent dial</th>
                <td className="mono">{detail.call.dial_id}</td>
              </tr>
              <tr>
                <th>Agent version</th>
                <td className="mono">{detail.call.versioned_prompt_id ?? "—"}</td>
              </tr>
              <tr>
                <th>Scenario</th>
                <td className="mono">{detail.call.scenario_id ?? "—"}</td>
              </tr>
              <tr>
                <th>Evaluation run</th>
                <td className="mono">{detail.call.evaluation_run_id ?? "—"}</td>
              </tr>
              <tr>
                <th>How it ended</th>
                <td className="mono">{detail.call.system_result_type ?? "—"}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <h2>Transcript</h2>
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">Recording</span>
          <Badge tone="neutral">not authoritative</Badge>
        </div>
        <div className="panel-body">
          <pre>
            {detail.transcript.segments
              .filter((s) => (s.text ?? "").trim())
              .map((s) => `${s.speaker.padEnd(5)} ${s.text}`)
              .join("\n") || "No transcript was captured."}
          </pre>
          <p className="panel-note">{detail.transcript.note}</p>
          <details>
            <summary>Function requests and responses</summary>
            <pre>
              {JSON.stringify(
                detail.action_executions.map((e) => ({
                  kind: e.kind,
                  outcome: e.outcome,
                  request: e.request_payload,
                  response: e.response_payload,
                })),
                null,
                2,
              )}
            </pre>
          </details>
        </div>
      </div>
    </>
  );
}
