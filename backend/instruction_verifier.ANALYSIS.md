# Verifier Prompt Analysis

## Why this doc exists

A recent ~1m45s "create a GitHub account" tutorial run looped on the gate.
The verifier returned `unsure` on three legitimate-looking screens
(step_002 / step_009 / step_017), and the session kept replanning.
This doc captures the prompt verbatim, the failure cases, the root cause
read, and 2–3 candidate revisions for the user to pick from before any
prompt change ships.

## ⚠ Verify the running backend first

`backend/instruction_verifier.py:92–95` (commit `62ed59ed`) already
treats `unsure` as `ok=True`:

```python
if verdict == "unsure":
    # Pass through — a precondition gate shouldn't replan on doubt;
    # only a confident "no" (a named blocker) interrupts the walk.
    return VerifierVerdict(ok=True, reason=f"unsure: {evidence}")
```

But the session log shows `unsure` verdicts triggering re-plans. Two
possibilities:

1. **The dev server is stale** (predates `62ed59ed`). Restart
   `./scripts/run-dev.sh` before doing anything else; that alone may
   eliminate the loop.
2. **The model is returning `"no"`, not `"unsure"`**, and the reasoning
   shown in the UI is the `"no"`-branch evidence. Capture a fresh log
   after restart to confirm which branch fires.

There is also a stale unit test on this exact code path:
`backend/tests/test_instruction_verifier.py::ParseVerdictTests::test_unsure_verdict_rejects`
still asserts `unsure → ok=False`. It was not updated when `62ed59ed`
flipped the semantics. Pre-existing on `HEAD`; not in scope for this
PR but worth knowing.

## Current prompt (verbatim)

**System** (`VERIFIER_SYSTEM_PROMPT`, `instruction_verifier.py:25–42`):

> You are a safety check for a tutorial overlay. The user is about to
> attempt the next instruction. Your only job is to detect when the
> screen is CLEARLY INCONSISTENT with that instruction — for example:
> an unrelated application is in focus, an error dialog is blocking
> the UI, the user is on a sign-in wall when the instruction assumes
> they are signed in, or the previous step obviously failed.
>
> Default to 'yes'. Only answer 'no' when you can point to a SPECIFIC
> blocking element (name it or quote its text). If the screen merely
> lacks the exact element named in the instruction, that is NOT a
> blocker — the instruction's element may be one click or scroll
> away. Answer 'unsure' only when something looks off but you cannot
> name a concrete blocker.
>
> Respond strictly as JSON with two fields: verdict (one of 'yes',
> 'no', 'unsure') and evidence (one short sentence naming the
> blocking element for 'no', or what looks plausible for 'yes'). Do
> not include any text outside the JSON object.

**User template** (`build_request`, `instruction_verifier.py:51–62`):

> Next instruction the user will attempt: {instruction}
>
> Look at the screenshot. Is there a SPECIFIC blocker that makes
> this instruction impossible to attempt right now — wrong app in
> focus, modal error, sign-in wall, prior step visibly failed?
> Name the blocking element if so. Otherwise answer 'yes' — the
> target element doesn't need to be visible on screen; the user
> may need to click, scroll, or navigate to reach it.
>
> Respond with JSON: {"verdict": "yes"|"no"|"unsure", "evidence": "..."}

## False-rejection cases from this session

> **Caveat:** transcript reasoning quotes below were reconstructed from
> the session summary, not the raw `[verifier] raw_response` log lines.
> Re-confirm verbatim against the live log after the next run.

### step_002 — "Click the 'Sign up' button to start creating an account"
- Verdict: `unsure`
- Reasoning (paraphrased): "I can't see an element literally labeled
  'Sign up' in the visible viewport."
- Actual screen: GitHub homepage, "Sign up" link present in the
  top-right nav (just visually small).

### step_009 — "Enter your email address"
- Verdict: `unsure`
- Reasoning (paraphrased): "Email field not visible; only the password
  step is rendered."
- Actual screen: A multi-step signup card mid-transition; email field
  was a click/scroll away.

### step_017 — "Verify your email by clicking the link GitHub sent you"
- Verdict: `unsure`
- Reasoning (paraphrased): "No email client is visible."
- Actual screen: Still on the GitHub "check your email" confirmation
  page — the instruction is forward-looking (user has to switch apps),
  which the prompt does not handle.

## Root cause read

The prompt instructs **two** things that pull in opposite directions:

1. "If the screen merely lacks the exact element named in the
   instruction, that is NOT a blocker" — correct framing.
2. "Answer `unsure` only when something looks off but you cannot name
   a concrete blocker" — gives the model a graceful escape hatch.

In practice the model takes the escape hatch when the *target element*
is missing, because "missing target" *feels* off even though rule (1)
explicitly says it isn't a blocker. The "NOT a blocker" sentence is
doing too little work — it's one negation in a paragraph that
otherwise primes the model to look for problems.

The code-side mitigation (`unsure → ok=True`) saves us, but only if it
actually runs. And even when it runs, the `evidence` text leaks into
the user-visible reason ("unsure: I can't see a 'Sign up' button"),
which is wrong and confusing.

Secondary issue: **forward-looking instructions** (step_017: switch to
your email client) aren't modeled. The prompt assumes every
instruction acts on the *current* screen. A "switch apps" instruction
has no blocker on the current screen by definition; the verifier
should pass these through trivially.

## Candidate prompt revisions

Pick one for a follow-up PR. Each keeps the JSON contract intact.

### Option A — Closed list of blocker categories (minimum change)
Restrict `"no"` to a fixed taxonomy. Anything outside the list ⇒ `"yes"`.

```
You are a precondition check. Answer "no" ONLY if one of these is
true on the visible screen:
  (1) WRONG_APP — a different application is in focus and the
      instruction is clearly app-specific.
  (2) MODAL_BLOCK — an error dialog, permission prompt, or modal
      is intercepting input.
  (3) AUTH_WALL — a sign-in or paywall is shown and the instruction
      assumes the user is past it.
  (4) PRIOR_STEP_FAILED — visible error text from the previous
      action (e.g. "invalid input", red toast).

Anything else — including "the target element isn't on screen",
"I need to scroll", "I need to switch apps" — is "yes".

Respond JSON: {"verdict": "yes"|"no", "evidence": "<CATEGORY>: <one
sentence>"}. Do not output "unsure".
```

Trade-off: removes `unsure` entirely, which is the simplest fix but
takes away the fail-safe.

### Option B — Forward-looking-aware (keeps `unsure`)
Add an explicit clause for switch-apps / wait-for-state instructions,
and tighten the "missing target" exemption.

```
Read the instruction. If it asks the user to switch applications,
wait for something off-screen, or otherwise act outside the current
screen, answer "yes" immediately.

Otherwise inspect the screen. Answer "no" ONLY when you can quote
the text of a specific blocker (modal title, error message, sign-in
button text, the focused app's name). The target element of the
instruction does NOT need to be visible — scrolling and navigation
are the user's job, not yours.

Reserve "unsure" for the case where you literally cannot tell what
app or page this is (e.g. a blank or corrupted screenshot). Missing
target ≠ unsure.
```

Trade-off: keeps `unsure` as a true uncertainty signal, not a hedge.

### Option C — Invert the framing (most aggressive)
Ask the model to default to `"yes"` and require it to *justify*
saying anything else, by quoting on-screen text.

```
Output "yes" unless you can quote literal on-screen text that
proves the next instruction cannot be attempted right now. The
quoted text must be one of: a modal/dialog title, an error message,
a sign-in button label, or the title of a different application in
focus.

If you cannot quote such text, output "yes". The target element of
the instruction does not need to be visible; missing target is
"yes".

Format: {"verdict":"yes"|"no","evidence":"<quoted text>"}.
```

Trade-off: most defensive against false negatives, but the model may
fabricate quoted text. Worth A/B against B.

## Recommendation

Start with **B** — minimal blast radius, keeps `unsure` honest, and
explicitly fixes the step_017 (switch-app) failure mode. If B still
loops, escalate to **A** (kill `unsure`).
