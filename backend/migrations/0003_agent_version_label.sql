-- Which flow version produced a call, as a stable label.
--
-- `versioned_prompt_id` already records the exact version, but that id changes every
-- time a flow is republished, so a label derived from "whatever is current" would
-- silently mislabel older calls. The runner knows which version it dialled, so it
-- records the label at registration and it stays true forever.
ALTER TABLE calls ADD COLUMN IF NOT EXISTS agent_version text;

COMMENT ON COLUMN calls.agent_version IS
    'Flow version label (v1/v2) recorded when the dial was registered. The exact '
    'version is versioned_prompt_id; this is the human-readable, stable one.';
