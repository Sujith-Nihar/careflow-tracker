import Link from "next/link";
import { Badge } from "@/components/Badge";
import { listCalls, type CallSummary } from "@/lib/api";
import {
  intentLabel,
  relativeTime,
  severityWord,
  statusLabel,
  toneForSeverity,
} from "@/lib/status";

export const dynamic = "force-dynamic";

/** True when the agent's claim is contradicted by the records. */
function claimIsFalse(call: CallSummary): boolean {
  return call.derived.promise_mismatch;
}

type Tile = { label: string; value: number; note: string; accent: string };

function tiles(calls: CallSummary[]): Tile[] {
  const attention = calls.filter((c) => c.derived.requires_staff_action);
  return [
    {
      label: "Waiting on someone",
      value: attention.length,
      note: "based on what the systems recorded",
      accent: "var(--accent)",
    },
    {
      label: "No one reached them",
      value: calls.filter((c) => c.derived.status === "escalation_failed").length,
      note: "no transfer and no callback",
      accent: "var(--critical)",
    },
    {
      label: "Callbacks to make",
      value: calls.filter((c) => c.derived.status === "callback_pending").length,
      note: "waiting for someone to ring",
      accent: "var(--serious)",
    },
    {
      label: "Agent told them wrong",
      value: calls.filter((c) => c.derived.promise_mismatch).length,
      note: "promised something that never happened",
      accent: "var(--warning)",
    },
  ];
}

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

  if (error) {
    return (
      <div className="panel">
        <div className="empty">
          <div className="empty-title">The evidence API is not reachable</div>
          <p className="empty-note">
            {error}. Start it with <code className="mono">make api</code>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>{showAll ? "All calls" : "Calls needing attention"}</h1>
        <p className="lede">
          Sorted by what the systems actually recorded, not by what the agent told the caller.
        </p>
      </div>

      <div className="tiles">
        {tiles(calls).map((tile) => (
          <div className="tile" key={tile.label} style={{ ["--tile-accent" as string]: tile.accent }}>
            <div className="tile-label">{tile.label}</div>
            <div className="tile-value">{tile.value}</div>
            <div className="tile-note">{tile.note}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">
            {calls.length} call{calls.length === 1 ? "" : "s"}
          </span>
          <nav className="seg" aria-label="Filter calls">
            <Link href="/calls" aria-current={!showAll ? "true" : undefined}>
              Needs attention
            </Link>
            <Link href="/calls?all=1" aria-current={showAll ? "true" : undefined}>
              All
            </Link>
          </nav>
        </div>

        {calls.length === 0 ? (
          <div className="empty">
            <div className="empty-title">Nothing is waiting on anyone</div>
            <p className="empty-note">
              No call has an unfinished action on record. That is not the same as every caller
              being helped: a call where the agent did nothing at all would show up here too.
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>How urgent</th>
                  <th>What the caller wanted</th>
                  <th>What the agent promised</th>
                  <th>What actually happened</th>
                  <th>What you should do</th>
                  <th>When</th>
                  <th>
                    <span className="sr-only">Open the call</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => {
                  const tone = toneForSeverity(call.derived.severity);
                  const claim = claimIsFalse(call);
                  return (
                    <tr key={call.call_id}>
                      <td>
                        <Badge tone={tone}>{severityWord(call.derived.severity)}</Badge>
                      </td>
                      <td>
                        <div className="cell-strong">
                          {intentLabel(call.observed_intent ?? call.agent_classified_intent)}
                        </div>
                        <div className="cell-sub">
                          {call.agent_version && (
                            <span className="version-tag">{call.agent_version.toUpperCase()}</span>
                          )}
                          {call.scenario_id && <span className="mono">{call.scenario_id}</span>}
                        </div>
                      </td>
                      <td>
                        {call.agent_promised ? (
                          <span className="cell-strong">{call.agent_promised}</span>
                        ) : (
                          <span className="muted">Did not promise anything</span>
                        )}
                        {claim && (
                          <div className="cell-sub">
                            <Badge tone="critical" alarm>
                              this did not happen
                            </Badge>
                          </div>
                        )}
                      </td>
                      <td>
                        <Link href={`/calls/${call.call_id}`} className="cell-strong">
                          {statusLabel(call.derived.status)}
                        </Link>
                      </td>
                      <td>
                        {call.derived.requires_staff_action ? (
                          call.derived.next_step
                        ) : (
                          <span className="muted">Nothing to do</span>
                        )}
                      </td>
                      <td className="num muted">
                        {relativeTime(call.ended_at ?? call.started_at)}
                        <div className="cell-sub">
                          {call.connected_seconds != null
                            ? `${call.connected_seconds}s call`
                            : call.lifecycle === "in_progress"
                              ? "in progress"
                              : "duration not recorded"}
                        </div>
                      </td>
                      <td className="row-open">
                        <Link href={`/calls/${call.call_id}`} className="open-link">
                          View evidence
                          <span aria-hidden="true"> →</span>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
