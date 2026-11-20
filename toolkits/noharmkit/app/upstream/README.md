# Rubric editor source

The rubric editor comes from two pinned sources. Toolkit users need no upstream
access; the owner approved publishing these selected files. Git history records
earlier pins.

| Source | What it supplies | Local folder | Manifest | Integration patch |
|---|---|---|---|---|
| [noharm-science](https://github.com/davidwumdphd/noharm-science) `harmreview/` | The current rubric editor (text rubric), its guide, its tutorial and example case, and the components and libraries they import | `app/harmreview/` | [noharm-science.json](noharm-science.json) | [noharm-science.patch](noharm-science.patch) |
| [ARISENetwork/noharm-kit](https://github.com/ARISENetwork/noharm-kit) (read-only archive) | The legacy answer-table editor and its shared files, plus `app/globals.css` | `app/` | [manifest.json](manifest.json) | [toolkit.patch](toolkit.patch) |

noharm-science is the editor's home. The noharm-kit archive is
the final source of the legacy answer-table format, which noharm-science dropped.
`text-v2.patch` is a historical record of the hand-copied text rubric editor that
the noharm-science source replaced.

The sync reads only allowlisted committed UI blobs, excluding datasets,
endpoints, configuration, and pages. Upstream `harmreview/` paths keep their
names in each patch. For noharm-science, the sync points `@/` imports at
`app/harmreview/` before the patch applies, so synced files never shadow the
toolkit's own modules.

## Integration

- Shared editor behavior belongs upstream first. Toolkit routing, storage, review provenance, history, source-hash conflicts, and same-origin checks stay outside the allowlists.
- `components/TextV2RubricEditor.tsx` (toolkit-owned) wraps the synced editor and supplies a `TextV2EditorHost` (`components/RubricEditorHost.tsx`): project storage instead of `/api/rubric`, validation pinned to the project's judge contract (`lib/text-v2-eligibility.ts`), version, review and failure tags, the save target and synthetic notices, and the save label. Portable exports pass file storage through the same host.
- `noharm-science.patch` adds that host prop and nothing else of substance: load, save and Reset through the host when present, host validation, autosave only while the host allows saving, the leave guard, header tags and notices, an initial record for static rendering, and a guard against overlapping saves. It also keeps the Task and Solution labels, opens dropdown menus and the guide inside the editor popup, points the editor's Tutorial button at the toolkit's route, and retitles the tutorial's first step for the toolkit (upstream's reads "Welcome to Stage 2"), and names the Task and Solution panels in its next two steps.
- Autosave: like upstream, edits save 0.8 s after they pause, so the first edit creates the reviewer's `reviewed-REVIEWER` copy. Reset loads the rubric that copy was based on (`/api/runs/table?original=1`), and autosave then replaces the copy.
- Portable-export exception: a portable review file saves by keeping a case in the tab or downloading the file, so its host sets `saveLabel`. The editor then shows that Save button and does not autosave; Reset still restores the packet's rubric.
- Tutorial: `/noharm/rubric-tutorial` renders the synced `RubricTutorial` on its synthetic UTI case; nothing in it is saved. The landing page links to it. Upstream's in-place copy editing (`/tutorial?edit`, `api/tutorial-copy`) is not synced.
- Validation exception: `lib/rubric-text-v2.ts` stays toolkit-owned. It matches each project's pinned Python scorer, including the older rule for historical pins, so the synced `app/harmreview/lib/rubric-text-v2.ts` supplies only the editor's helpers and help text.
- Styling: `app/globals.css` defines the editor's tip and backdrop tokens and its dark palette, which follows the system dark mode only while an editor is on screen; the legacy editor stays light.
- Legacy editor: portable exports use `AnswerTableEditorView` with file storage; the storage seam came from reference commit `c086e25597720fe7a46515b781056b5a6c0ba81e`. The standard scorer excludes upstream's experimental unmatched-statement reading rules. Tags do not change scoring; legacy untagged records and conditions without `match` remain compatible (`any` default). Existing records are not rewritten.
- Host save-safeguard exception: both editors publish dirty, saving, save-availability and error state through an optional local React context, with an explicit asynchronous save result. The popup owns leave confirmation and navigation; standalone editors keep their unload warning. Failed saves keep dirty state, including transport errors. Each save binds its edit revision; newer edits stay unsaved, cannot trigger an overlapping save, and keep save-and-continue from leaving. Preview-only editors cannot save. This wiring changes no rubric controls, validators, scoring or clinical acceptance rules.

## Checks

Offline drift check for both sources; no upstream checkout or credentials needed:

```sh
.venv/bin/python tools/sync_harmreview.py check
```

`npm --prefix app run check` includes it. Maintainers can verify reconstruction:

```sh
.venv/bin/python tools/sync_harmreview.py verify --source noharm-science --repo ../noharm-science
.venv/bin/python tools/sync_harmreview.py verify --source noharm-kit --repo ../noharm-kit
```

## Updates

Keep the editor on the latest noharm-science. Review the new commits under
`harmreview/`, then import and check:

```sh
.venv/bin/python tools/sync_harmreview.py update --source noharm-science --repo ../noharm-science --ref COMMIT
git diff -- app tools/sync_harmreview.py
npm --prefix app run check
npm --prefix app test
.venv/bin/python -m pytest tests/test_harmreview_sync.py -q
```

Local drift, missing files, or patch conflicts stop writes. Working-tree edits
are ignored; there is no force overwrite. When upstream adds a module the
editor imports, review it, add its exact path to `EDITOR_FILES`, and pass
`--include PATH`. Existing unpinned files are never replaced.

If the patch conflicts, resolve it by hand: write the upstream files at the new
commit into `app/harmreview/`, reapply the integration changes, set the
manifest's `sourceCommit`, then rebuild the patch and hashes and prove them:

```sh
.venv/bin/python tools/sync_harmreview.py record --source noharm-science --repo ../noharm-science
.venv/bin/python tools/sync_harmreview.py verify --source noharm-science --repo ../noharm-science
```

Review the recorded patch before committing: it must hold only integration
changes. Never bless editor changes by recording them. Clinical-format changes
need separate approval. Exercise the editor (Rubrics popup, `/noharm/review`,
light and dark, save and leave guard) before committing a sync.
