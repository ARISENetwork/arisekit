# Startup

Read `AGENTS.md` and `CLAUDE.md`. `startup`, `$startup`, `/startup`, and “Start the
app” authorize launch only, not provider calls, pipeline stages, or credential
changes. Preserve projects and existing environments.

## Environment

Run the following from `toolkits/noharmkit`. Check Python 3.11 or newer, uv, Node.js 22 or newer, and npm. Explain missing prerequisites.
Reuse installed dependencies; ask before installing. For a fresh environment:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e ../.. -r requirements.txt
npm ci --prefix app
```

`-e ../..` installs the shared `arisekit` package from the ARISEKit repository root. An environment
that reports `No module named 'arisekit'` predates this; rerun the `uv pip install` line once.

## Viewer

1. Check `lsof -iTCP:9000 -sTCP:LISTEN`. Reuse only a verified viewer from this checkout serving the intended projects root. Do not stop an unrelated process; use `--port` if needed.
2. Start `.venv/bin/python tools/noharm.py view` from the root in the background with captured logs. It binds to `127.0.0.1` and serves `projects/`.
3. Verify the process is alive and a bounded HTTP request succeeds. Inspect logs on failure. Browser automation and screenshots are separate testing tasks.
4. Open the landing URL once in the default external browser, using `open "http://localhost:9000/"` on macOS. Use the in-app browser only if requested.
5. Share the verified local viewer URL.
6. Point to **NOHARMKit**, then **Walkthrough**, **Create a new project**, or **Resume an existing project**. End once ready; do not keep the coding chat listening.

## Workflow

The prepared walkthrough needs no key or model call. For real projects, stage
buttons prepare coding-agent prompts; **Refresh** loads saved results and
**Continue** navigates. Resolve project, cases, models, trials, route, and spend
before live stages, preserving prior authorization. See the
[runbook](docs/runbook-e2e-mvp.md).
