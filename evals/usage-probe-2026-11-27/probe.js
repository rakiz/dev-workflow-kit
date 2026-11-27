// A1-A5 probe: logs raw event shapes to probe.jsonl in the sandbox config dir.
import { appendFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "probe.jsonl");
const log = (o) => { try { appendFileSync(OUT, JSON.stringify(o) + "\n"); } catch (e) {} };
export const Probe = async () => ({
  event: async ({ event }) => {
    const p = event.properties || {};
    if (event.type === "message.updated") {
      const i = p.info || {};
      log({ t: "message.updated", id: i.id, role: i.role, sessionID: i.sessionID, parentID: i.parentID,
            modelID: i.modelID, providerID: i.providerID, mode: i.mode, agent: i.agent,
            cost: i.cost, tokens: i.tokens, completed: i.time?.completed, created: i.time?.created,
            finish: i.finish, keys: Object.keys(i) });
    } else {
      log({ t: event.type, keys: Object.keys(p), sessionID: p.sessionID ?? p.info?.id ?? null,
            session_parentID: p.info?.parentID ?? null });
    }
  },
  "chat.message": async (input, output) => {
    log({ t: "chat.message", agent: input.agent ?? null, model: input.model ?? null, variant: input.variant ?? null,
          msgRole: output.message?.role, msgAgent: output.message?.agent, msgModel: output.message?.model });
  },
});
export default Probe;
