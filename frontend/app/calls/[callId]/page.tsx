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
  schedule_appointment: "Tried to book an appointment",
  transfer_triage: "Tried to put the caller through to the nurse",
  create_callback: "Tried to arrange a callback",
  report_disposition: "Agent's own summary of the call",
};

const OUTCOME: Record<string, { text: string; tone: "good" | "warning" | "critical" | "neutral" }> = {
  succeeded: { text: "it worked", tone: "good" },
  failed: { text: "it failed", tone: "critical" },
  unverified: { text: "no answer either way", tone: "warning" },
  rejected: { text: "details were unreadable", tone: "warning" },
  not_applicable: { text: "not needed", tone: "neutral" },
  requested: { text: "still running", tone: "neutral" },
};

/** How the agent summarised the call, in the words a person would use. */
const DISPOSITION_TEXT: Record<string, string> = {
  scheduled: "booked",
  transferred: "put through to the nurse",
  callback_pending: "a callback is waiting",
  escalation_failed: "nobody could be reached",
  unresolved: "not resolved",
  resolved: "sorted",
};

const SAID: Record<string, { text: string; icon: string }> = {
  promised_transfer: { text: "\u201cI\u2019m putting you through to the nurse\u201d", icon: "!" },
  promised_callback: { text: "\u201cSomeone will call you back\u201d", icon: "!" },
  promised_appointment: { text: "\u201cYour appointment is booked\u201d", icon: "!" },
  disclosed_transfer_failed: { text: "Admitted the transfer did not go through", icon: "✓" },
  disclosed_callback_failed: { text: "Admitted no callback could be arranged", icon: "✓" },
  disclosed_scheduling_failed: { text: "Admitted the booking was not confirmed", icon: "✓" },
};

/** How each attempt went, in words rather than result codes. */
const ATTEMPT_RESULT: Record<string, string> = {
  connected: "connected",
  no_answer: "no answer",
  busy: "busy",
  timeout: "timed out",
  accepted_unconfirmed: "accepted but unconfirmed",
  booked: "booked",
  created: "created",
  rejected: "refused",
  unavailable: "unavailable",
};

/** Failure codes belong in logs. On screen they become a phrase. */
const WHY_NO_TRANSFER: Record<string, string> = {
  no_answer: "nobody picked up",
  busy: "the line was busy",
  no_confirmation: "the line never confirmed the caller was connected",
  transfer_timeout: "the line did not respond in time",
};

function recorded(detail: CallDetail): { text: string; tone: "good" | "critical" | "warning" }[] {
  const out: { text: string; tone: "good" | "critical" | "warning" }[] = [];
  for (const t of detail.downstream.transfer_sessions) {
    out.push(
      t.status === "connected"
        ? { text: "The nurse's line picked up.", tone: "good" }
        : {
            text: `The caller never reached the nurse: ${
              WHY_NO_TRANSFER[t.failure_reason ?? ""] ?? "the line did not connect"
            }.`,
            tone: "critical",
          },
    );
  }
  for (const c of detail.downstream.callback_requests) {
    const priority = c.priority === "urgent" ? "An urgent" : "A normal-priority";
    out.push(
      c.status === "completed"
        ? { text: `${priority} callback was made by a staff member.`, tone: "good" }
        : { text: `${priority} callback is sitting in the queue, not yet made.`, tone: "warning" },
    );
  }
  for (const a of detail.downstream.appointments) {
    out.push(
      a.status === "booked"
        ? { text: "An appointment exists in the diary.", tone: "good" }
        : { text: "There is no appointment.", tone: "critical" },
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
      text: `${ACTION_LABEL[e.kind] ?? e.kind} \u2014 ${OUTCOME[e.outcome]?.text ?? e.outcome}.`,
      tone: "critical",
    });
  }
  if (out.length === 0) {
    out.push({ text: "The agent never tried to do anything.", tone: "critical" });
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
        ← Back to calls
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
            {detail.call.agent_version && (
              <span className="version-tag">
                {detail.call.agent_version.toUpperCase()} agent
              </span>
            )}
            {d?.promise_mismatch && (
              <Badge tone="critical" alarm>
                agent said otherwise
              </Badge>
            )}
          </div>
        </div>

        {d?.requires_staff_action && (
          <div className="hero-next">
            <span className="hero-next-label">What you should do</span>
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

      <h2>What the agent said, against what really happened</h2>
      <div className="compare stagger">
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">What the agent told the caller</span>
          </div>
          <div className="panel-body">
            {spoken.length === 0 && !disposition ? (
              <p className="muted" style={{ margin: 0 }}>
                The agent did not claim anything had been arranged.
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
                {disposition?.disposition && (
                  <li>
                    <span className="claim-icon muted">›</span>
                    <span>
                      Signed the call off as{" "}
                      <strong>{DISPOSITION_TEXT[disposition.disposition] ?? disposition.disposition}</strong>
                    </span>
                  </li>
                )}
              </ul>
            )}
            <p className="panel-note">
              Taken from the recording. This tells you what the caller was told. It is not proof
              that anything happened.
            </p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">What actually happened</span>
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
              Taken from the diary, the nurse's line and the callback queue. This is what decides
              whether the call is finished.
            </p>
          </div>
        </section>
      </div>

      <h2>Everything the agent tried, in order</h2>
      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>What it tried</th>
                <th>How it went</th>
                <th>Attempts</th>
                <th>Reference</th>
                <th>At</th>
              </tr>
            </thead>
            <tbody>
              {detail.action_executions.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    The agent never tried to do anything on this call.
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
                        .map(
                          (a) =>
                            `try ${a.attempt_no}: ${
                              ATTEMPT_RESULT[a.result] ?? a.result.replace(/_/g, " ")
                            }, ${a.latency_ms}ms`,
                        )
                        .join(" · ") || "—"}
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

      <h2>Reference numbers</h2>
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
                <td>
                  {detail.call.agent_version && (
                    <span className="version-tag">{detail.call.agent_version.toUpperCase()}</span>
                  )}{" "}
                  <span className="mono">{detail.call.versioned_prompt_id ?? "—"}</span>
                </td>
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
                <th>How the call ended</th>
                <td className="mono">{detail.call.system_result_type ?? "—"}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <h2>What was said on the call</h2>
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">Recording</span>
          <Badge tone="neutral">not proof of anything</Badge>
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
            <summary>Technical detail: what was sent and what came back</summary>
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
