/**
 * Server-side access to the evidence API.
 *
 * Every call happens on the server. The browser never holds the organization
 * identifier or talks to the backend directly, so a shared screenshot or an open
 * devtools panel cannot leak one practice's identifiers to another.
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5055";
const ORGANIZATION_ID = process.env.DEMO_ORGANIZATION_ID ?? "";

export type Derived = {
  status: string;
  severity: number;
  requires_staff_action: boolean;
  reason: string;
  next_step: string;
  promise_mismatch: boolean;
  mismatch_details: string[];
  evidence_refs: Record<string, string>;
};

export type CallSummary = {
  /** What the agent told the caller it had arranged, if it claimed anything. */
  agent_promised: string | null;
  call_id: string;
  dial_id: string;
  scenario_id: string | null;
  lifecycle: string;
  started_at: string | null;
  ended_at: string | null;
  connected_seconds: number | null;
  agent_classified_intent: string | null;
  derived: Derived;
};

export type Statement = {
  kind: string;
  source: string;
  disposition: string | null;
  evidence_text: string | null;
  sequence_no: number;
  observed_at: string | null;
};

export type Execution = {
  id: string;
  kind: string;
  outcome: string;
  request_payload: Record<string, unknown> | null;
  response_payload: Record<string, unknown> | null;
  attempts: { attempt_no: number; latency_ms: number; result: string }[] | null;
  downstream_ref: string | null;
  duplicate_of_id: string | null;
  requested_at: string | null;
  completed_at: string | null;
};

export type CallDetail = {
  call: {
    id: string;
    dial_id: string;
    vogent_agent_id: string | null;
    versioned_prompt_id: string | null;
    scenario_id: string | null;
    evaluation_run_id: string | null;
    lifecycle: string;
    started_at: string | null;
    ended_at: string | null;
    connected_seconds: number | null;
    system_result_type: string | null;
  };
  intent: { agent_classified: string | null; true_intent: string | null };
  agent_statements: Statement[];
  action_executions: Execution[];
  downstream: {
    appointments: { id: string; status: string; action_execution_id: string }[];
    transfer_sessions: {
      id: string;
      status: string;
      failure_reason: string | null;
      action_execution_id: string;
    }[];
    callback_requests: {
      id: string;
      status: string;
      priority: string;
      action_execution_id: string;
    }[];
  };
  staff_actions: { id: string; kind: string; actor: string | null; created_at: string | null }[];
  derived: Derived | null;
  transcript: { authoritative: boolean; note: string; segments: { speaker: string; text: string }[] };
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    headers: { "X-Organization-Id": ORGANIZATION_ID },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function listCalls(onlyAttention: boolean): Promise<CallSummary[]> {
  const query = onlyAttention ? "?requires_staff_action=true&limit=200" : "?limit=200";
  const body = await get<{ calls: CallSummary[] }>(`/api/calls${query}`);
  return body.calls;
}

export async function getCall(callId: string): Promise<CallDetail> {
  return get<CallDetail>(`/api/calls/${callId}`);
}

export async function completeCallback(
  callId: string,
  callbackId: string,
  actor: string,
): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/api/calls/${callId}/staff-actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Organization-Id": ORGANIZATION_ID },
    body: JSON.stringify({ kind: "callback_completed", target_callback_id: callbackId, actor }),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`marking the callback complete failed (${response.status})`);
  }
}
