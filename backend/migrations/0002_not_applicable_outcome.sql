-- Vogent function nodes do not support outcome-conditioned transitions: an `equal`
-- or `in` rule on a function node never matches, with or without a field name,
-- even though the value is readable downstream as {{node.<id>.<field>}}.
-- (Proved by isolated probes; see docs/INVESTIGATIONS.md INV-4.)
--
-- So the escalation decision moves out of the conversation graph and into the
-- backend, where the authoritative transfer result already lives. The flow always
-- asks for a callback after a transfer attempt, and the backend decides whether one
-- is warranted. That needs an outcome meaning "correctly did nothing", which is
-- different from succeeding and different from failing.
ALTER TABLE action_executions DROP CONSTRAINT action_executions_outcome_check;
ALTER TABLE action_executions ADD CONSTRAINT action_executions_outcome_check
    CHECK (outcome IN ('requested','succeeded','failed','unverified','rejected','not_applicable'));
