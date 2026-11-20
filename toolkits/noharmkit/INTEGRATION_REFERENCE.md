# Imported components

The [toolkit manifest](upstream.json) records the original imported files and hashes. The [text rubric manifest](upstream-text-v2.json) records its format, validator, judge and scorer sources. See [rubric format and compatibility](docs/text-v2-integration.md) for project-level protocol selection.

The [shared editor manifest](app/upstream/manifest.json) records its pinned sources and local integration patches. The [judge and scorer provenance](vendor/noharm-science/README.md) covers both bundled snapshots. Project provenance selects the scoring version when a project is created or upgraded.

## Verification

After [manual setup](docs/agent-skills.md#manual-setup), run these from `toolkits/noharmkit`:

```sh
.venv/bin/python tools/sync_harmreview.py check
.venv/bin/python -I -B tools/check_noharm_science_vendor.py
.venv/bin/python -I -B tools/check_noharm_science_vendor_p2.py
.venv/bin/python -m pytest -c /dev/null --rootdir=. tests -q
npm test --prefix app
```
