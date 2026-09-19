# Update for the practice manager

Written for the practice manager who reported the problem. Plain language, no jargon.

---

**What was going wrong**

Your instinct was right. Some calls were being marked resolved because the assistant
*said* it had transferred someone or arranged a callback, not because anything actually
happened. We reproduced it: on a test call, a caller reporting a bleeding surgical wound
was told "I'm connecting you to the triage nurse now" and nothing was attempted at all.
No transfer, no callback, no record of either.

**What we changed**

Two things, and the second matters more than the first.

The assistant now only tells a caller something happened after the system confirms it
did. If the triage line does not answer, it says so plainly rather than claiming a
transfer.

More importantly, we stopped trusting the assistant to decide whether to escalate.
When a transfer does not connect, our system creates the urgent callback itself, based
on what actually happened on the line. Even if the assistant word things badly, the
callback still exists.

**What staff can trust now**

- The list of calls needing attention is built from what the systems actually did, never
  from what the assistant said. A call only shows as handled if there is a real
  appointment, a real answered transfer, or a completed callback behind it.
- When a call needs someone, the screen says why and what to do next, in one sentence.
- If the assistant told a caller something that does not match the records, the call is
  flagged and stays on the list. It cannot be hidden by a confident-sounding summary.
- A call where nothing was recorded is treated as needing attention, not as finished.
  Silence is never taken as success.

**What staff should not trust yet**

- **The transcript is not proof.** It shows what was said. Use the "what the systems
  recorded" panel to decide anything.
- **The wording is not guaranteed.** In our testing the assistant occasionally failed to
  mention one of two problems, even when it handled the call correctly. The actions were
  always right; the explanation sometimes was not. Read the evidence, not the summary.
- **This is a test environment.** The scheduler, the triage line and the callback queue
  are simulations. Nothing here is connected to your real systems or your real patients.

**What is still manual**

- Someone has to actually make the callbacks. The system queues them and tells you who is
  owed one; it does not call anyone.
- Marking a callback done is a manual click, and it records only a job title, not a named
  person, because there is no login yet.
- Nobody is alerted when an urgent callback goes unanswered. Someone has to look at the list.

**What we would do next, in order**

1. **Alert on the worst cases.** A caller with a post-operative concern and no nurse
   contact should page someone, not wait to be noticed on a screen.
2. **Track how long urgent callbacks wait.** Right now we can tell you one is owed, but
   not that it has been owed for three hours.
3. **Add logins.** So "who closed this call" is a real answer.
4. **Widen the testing.** We tested four situations thoroughly. Real callers do many more
   things, and the assistant should be tested against those before it handles them.

**One thing worth saying plainly**

Our small test set is not a measure of how often this happened on your real calls. It
shows the failure is real and that it is now caught. It does not tell you how many of
yesterday's callers were affected. If that matters, the same evidence trail can answer it
from your actual call records.
