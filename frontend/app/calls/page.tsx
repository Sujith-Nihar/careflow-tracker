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

/** What the agent claimed, as one short phrase, or nothing if it claimed nothing. */
function claimSummary(call: CallSummary): string | null {
  if (call.derived.promise_mismatch) return "Something the records do not show";
  return null;
}

type Tile = { label: string; value: number; note: string; accent: string };

function tiles(calls: CallSummary[]): Tile[] {
  const attention = calls.filter((c) => c.derived.requires_staff_action);
  return [
    {
      label: "Needs a human",
      value: attention.length,
      note: "derived from recorded evidence",
      accent: "var(--accent)",
    },
    {
      label: "Nobody is coming",
      value: calls.filter((c) => c.derived.status === "escalation_failed").length,
      note: "no transfer, no callback",
      accent: "var(--critical)",
    },
    {
      label: "Callbacks owed",
      value: calls.filter((c) => c.derived.status === "callback_pending").length,
      note: "queued and unanswered",
      accent: "var(--serious)",
    },
    {
      label: "Agent said otherwise",
      value: calls.filter((c) => c.derived.promise_mismatch).length,
      note: "claim contradicts the records",
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
          Ordered by what the recorded evidence shows, never by what the agent said it did.
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
            <div className="empty-title">Nothing is waiting on a human</div>
            <p className="empty-note">
              That means no call has evidence of an unfinished action. It does not mean every
              caller was helped: a call where nothing was recorded would appear here too.
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Caller wanted</th>
                  <th>What the records show</th>
                  <th>Do this next</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => {
                  const tone = toneForSeverity(call.derived.severity);
                  const claim = claimSummary(call);
                  return (
                    <tr key={call.call_id}>
                      <td>
                        <Badge tone={tone}>{severityWord(call.derived.severity)}</Badge>
                      </td>
                      <td>
                        <div className="cell-strong">
                          {intentLabel(call.agent_classified_intent)}
                        </div>
                        {call.scenario_id && (
                          <div className="cell-sub mono">{call.scenario_id}</div>
                        )}
                      </td>
                      <td>
                        <Link href={`/calls/${call.call_id}`} className="cell-strong">
                          {statusLabel(call.derived.status)}
                        </Link>
                        {claim && (
                          <div className="cell-sub">
                            <Badge tone="critical" alarm>
                              agent said otherwise
                            </Badge>
                          </div>
                        )}
                      </td>
                      <td>
                        {call.derived.requires_staff_action ? (
                          call.derived.next_step
                        ) : (
                          <span className="muted">Nothing outstanding</span>
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
