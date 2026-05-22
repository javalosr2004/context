# Video → Action-Word Parsing (Parked Idea)

Status: parked — not pursued, kept for future reference.

## Sketch

Pipeline considered for a new Docker-hosted service (local for testing):

1. **Input**: video (screen recording or tutorial clip).
2. **Action-word extraction**: parse transcript / on-screen text for imperative
   phrases that signal UI actions — e.g. "click here", "scroll down until",
   "select the dropdown", "type your name".
   - The vocabulary of action phrases is open-ended. Two options to build it:
     - **Hand-curated seed list** of imperative verbs + UI nouns.
     - **Discovered**: run TF-IDF (or similar) over a tutorial corpus to surface
       phrases that are disproportionately common in instructional content vs.
       generic speech.
3. **Sliding window over probable action areas**: once a timestamp + verb is
   located, scan a temporal window of frames around it to find the on-screen
   region the action refers to (cursor motion, hover, highlight, click flash).

## Why parked

User scratched the plan mid-thought. Re-evaluate before building — open
questions include: transcript source (ASR vs. captions), how to bind a verb
phrase to a spatial region without already having the action detector, and
whether this duplicates work the existing capture/replay path will cover.
