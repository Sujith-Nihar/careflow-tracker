-- CareFlow Tracker schema. See docs/DATA_MODEL.md for the reasoning.
--
-- Two ideas shape this schema:
--   1. Evidence is append-mostly. An action execution is inserted when the request
--      arrives and updated once with its outcome. Downstream records are inserted
--      only when a simulated system actually accepted the action.
--   2. A failed action leaves no downstream row. The failure lives on the execution.
--      That is what keeps "fallback attempted" distinct from "fallback created".
--
-- Nothing here stores a staff-visible status as an input. Status is derived.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- --------------------------------------------------------------------------
-- Organizations and the agents that belong to them
-- --------------------------------------------------------------------------
CREATE TABLE organizations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                text NOT NULL UNIQUE,
    name                text NOT NULL,
    function_token_hash text NOT NULL,
    webhook_token_hash  text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Defence in depth: a request whose token resolves to one organization but whose
-- dial belongs to an agent registered to another is rejected.
CREATE TABLE agent_registrations (
    vogent_agent_id text PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Calls: one row per Vogent dial
-- --------------------------------------------------------------------------
CREATE TABLE calls (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    dial_id                 text NOT NULL UNIQUE,
    vogent_agent_id         text,
    versioned_prompt_id     text,
    scenario_id             text,
    evaluation_run_id       uuid,
    lifecycle               text NOT NULL DEFAULT 'registered'
                            CHECK (lifecycle IN ('registered','in_progress','ended','ended_unconfirmed')),
    started_at              timestamptz,
    ended_at                timestamptz,
    connected_seconds       integer CHECK (connected_seconds IS NULL OR connected_seconds >= 0),
    system_result_type      text,
    -- The agent's own categorisation. A claim, never evidence.
    agent_classified_intent text CHECK (agent_classified_intent IS NULL OR agent_classified_intent
                            IN ('routine_scheduling','post_operative_concern','other')),
    -- Scenario truth, populated for evaluation calls only. Never read by derivation.
    true_intent             text,
    transcript              jsonb,
    derived_status_cache    jsonb,
    derived_inputs_hash     text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, dial_id)
);
CREATE INDEX calls_org_created_idx ON calls (organization_id, created_at DESC);
CREATE INDEX calls_run_idx ON calls (evaluation_run_id) WHERE evaluation_run_id IS NOT NULL;

-- --------------------------------------------------------------------------
-- What the agent told the caller
-- --------------------------------------------------------------------------
CREATE TABLE agent_statements (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id         uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN (
                        'promised_transfer','promised_callback','promised_appointment',
                        'disclosed_transfer_failed','disclosed_callback_failed','reported_disposition')),
    source          text NOT NULL CHECK (source IN ('transcript_rule','function_param')),
    disposition     text CHECK (disposition IS NULL OR disposition IN (
                        'scheduled','transferred','callback_pending','escalation_failed',
                        'unresolved','resolved')),
    evidence_text   text CHECK (evidence_text IS NULL OR length(evidence_text) <= 1000),
    sequence_no     integer NOT NULL DEFAULT 0,
    rules_version   integer,
    observed_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_statements_call_idx ON agent_statements (call_id, sequence_no);

-- --------------------------------------------------------------------------
-- Action executions: the uniform record of every tool call
-- --------------------------------------------------------------------------
CREATE TABLE action_executions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id             uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind                text NOT NULL CHECK (kind IN (
                            'schedule_appointment','transfer_triage','create_callback','report_disposition')),
    -- sha256(dial_id, function name, canonical params). The duplicate guard.
    idempotency_key     text NOT NULL UNIQUE,
    request_payload     jsonb NOT NULL,
    response_payload    jsonb,
    transcript_snapshot jsonb,
    attempts            jsonb NOT NULL DEFAULT '[]'::jsonb,
    outcome             text NOT NULL DEFAULT 'requested'
                        CHECK (outcome IN ('requested','succeeded','failed','unverified','rejected')),
    downstream_ref      text,
    duplicate_of_id     uuid REFERENCES action_executions(id) ON DELETE SET NULL,
    request_id          text,
    requested_at        timestamptz NOT NULL DEFAULT now(),
    completed_at        timestamptz,
    CONSTRAINT completed_executions_have_an_outcome
        CHECK (completed_at IS NULL OR outcome <> 'requested')
);
CREATE INDEX action_executions_call_idx ON action_executions (call_id, requested_at);

-- --------------------------------------------------------------------------
-- Simulated downstream systems. A row here means the action really happened.
-- --------------------------------------------------------------------------
CREATE TABLE appointments (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    action_execution_id uuid NOT NULL UNIQUE REFERENCES action_executions(id) ON DELETE CASCADE,
    patient_ref         text NOT NULL,
    slot                timestamptz NOT NULL,
    status              text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','cancelled')),
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- One row per attempt on the triage line, like a call-detail record.
CREATE TABLE transfer_sessions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    action_execution_id uuid NOT NULL REFERENCES action_executions(id) ON DELETE CASCADE,
    destination         text NOT NULL DEFAULT 'triage_line',
    status              text NOT NULL CHECK (status IN ('connected','failed','unverified')),
    failure_reason      text,
    attempt_no          integer NOT NULL DEFAULT 1,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX transfer_sessions_execution_idx ON transfer_sessions (action_execution_id);

-- A failed creation deliberately leaves no row here.
CREATE TABLE callback_requests (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    action_execution_id uuid NOT NULL UNIQUE REFERENCES action_executions(id) ON DELETE CASCADE,
    patient_ref         text NOT NULL,
    priority            text NOT NULL CHECK (priority IN ('urgent','normal')),
    reason_code         text NOT NULL,
    status              text NOT NULL DEFAULT 'created' CHECK (status IN ('created','completed')),
    completed_by        text,
    completed_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT completed_callbacks_record_who
        CHECK (status <> 'completed' OR (completed_by IS NOT NULL AND completed_at IS NOT NULL))
);

-- --------------------------------------------------------------------------
-- Raw vendor traffic, append-only
-- --------------------------------------------------------------------------
CREATE TABLE vogent_events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
    dial_id         text,
    event_type      text NOT NULL,
    dedupe_key      text NOT NULL UNIQUE,
    payload         jsonb NOT NULL,
    rejected_reason text,
    received_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX vogent_events_dial_idx ON vogent_events (dial_id, received_at);

-- --------------------------------------------------------------------------
-- Evaluation support
-- --------------------------------------------------------------------------
-- Registered by the runner before a call starts, so simulator behaviour never
-- depends on the model relaying a scenario name correctly.
CREATE TABLE fault_profiles (
    dial_id           text PRIMARY KEY,
    organization_id   uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scenario_id       text NOT NULL,
    scenario_version  integer NOT NULL DEFAULT 1,
    evaluation_run_id uuid,
    true_intent       text,
    profile           jsonb NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evaluation_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    suite               text NOT NULL,
    strategy            text NOT NULL CHECK (strategy IN ('naive_voice','optimized','replay')),
    versioned_prompt_id text,
    backend_git_sha     text,
    status              text NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','failed')),
    error               text,
    cost_label          text CHECK (cost_label IS NULL OR cost_label IN ('ACTUAL_BILLED','CALCULATED_ESTIMATE')),
    rate_usd_per_second numeric(10,6),
    rate_source         text,
    job_id              text,
    started_at          timestamptz NOT NULL DEFAULT now(),
    ended_at            timestamptz,
    wall_seconds        numeric(10,3)
);

CREATE TABLE evaluation_cases (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id            uuid NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    organization_id   uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scenario_id       text NOT NULL,
    scenario_version  integer NOT NULL DEFAULT 1,
    mode              text NOT NULL CHECK (mode IN ('voice','replay','structural')),
    dial_id           text,
    call_id           uuid REFERENCES calls(id) ON DELETE SET NULL,
    passed            boolean,
    metrics           jsonb NOT NULL DEFAULT '{}'::jsonb,
    wall_seconds      numeric(10,3),
    connected_seconds integer,
    cost_usd          numeric(10,6),
    artifact_path     text,
    cache_key         text,
    started_at        timestamptz,
    ended_at          timestamptz,
    UNIQUE (run_id, scenario_id)
);

-- --------------------------------------------------------------------------
-- Human actions, so "who closed this" is answerable
-- --------------------------------------------------------------------------
CREATE TABLE staff_actions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id            uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    organization_id    uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    actor              text NOT NULL,
    kind               text NOT NULL CHECK (kind IN ('callback_completed','reviewed')),
    target_callback_id uuid REFERENCES callback_requests(id) ON DELETE SET NULL,
    note               text CHECK (note IS NULL OR length(note) <= 1000),
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX staff_actions_call_idx ON staff_actions (call_id, created_at);
