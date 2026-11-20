---
name: startup
description: Launch ARISEKit and open its landing page. Use when the user asks to start or open this repository's app. Model runs are separate requests.
---

Read and follow the repository-root [STARTUP.md](../../../STARTUP.md), the
canonical launch procedure for Claude Code and Codex.

Treat `startup`, `$startup`, `/startup`, and "Start the app" as launch-only
requests. Reuse a verified viewer from this checkout or start it with the project
Python environment. Check readiness in the terminal and open the landing page
once in the system's default external browser; use the in-app browser only when
explicitly requested. Share the verified local viewer URL.

Launch without subscription consent. The prepared walkthrough requires no model
calls or copied prompts. End the turn after the viewer is ready and the URL
is shared.

Preserve project data, environments, and credentials. Ask before
installing missing dependencies. Startup does not authorize pipeline stages,
provider calls, or authentication changes. Use the stage skills for later
coding-agent handoffs.
