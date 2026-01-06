# README.md

## Overview
This project turns recorded workflows into interactive, on-screen tutorials.

Instead of watching a video or reading a PDF and translating instructions into actions, the user gets a live overlay that guides them step-by-step inside the real application they are using. A creator records a task as clicks, keystrokes, and screenshots. The system replays it as a guided walkthrough that tracks progress and asks for confirmation when the screen does not match the expected step.

The goal is “teaching while doing.” Automation is optional later. The MVP focuses on universal recording and an overlay player that helps users complete tasks like setting up Git, navigating internal tools, or completing multi-step web flows.

## MVP Scope
- Record: clicks, keystrokes, active window metadata, screenshots at key moments
- Save: a portable recording folder (events log + frames)
- Play: overlay walkthrough with step text, thumbnails, and a highlighted target area
- Confirm: user can confirm the current screen is correct before advancing

## Non-Goals (for now)
- Full cross-app automation
- Perfect generalization across redesigned UIs
- PII/secure-field scrubbing (planned later)

## High-Level Architecture
- **Capture Service**: records input events and screenshots and writes an append-only event log
- **Desktop App (Overlay + Player)**: starts/stops recording, edits steps, and renders an always-on-top overlay during playback

## Principles
- Human-in-the-loop guidance first
- Deterministic logs and replayability
- Layered design with clear boundaries
- Prefer simple, testable code over cleverness
