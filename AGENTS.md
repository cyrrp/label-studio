# Label Studio — fork notes (Windows)

## Branch layout
- **`custom`** — our fork branch, based on stable release tag **1.23.2**.
  New upstream releases are merged INTO this branch (`git merge <tag>`),
  never rebase it onto develop/nightly.
- `wip/custom-on-develop` — frozen backup of the same changes on develop,
  kept for reference; delete once `custom` is confirmed good.
- Our code lives in `web/libs/editor/src/custom/` (CustomInterface dispatcher
  + wizard component) plus ~15 lines of upstream patches:
  `components/App/App.jsx` (import), `mixins/Visibility.js` (wizard-aware
  driver-tag check), `stores/Annotation/Annotation.js` (guardedHotkey wraps),
  `data_manager/serializers.py` + `tasks/serializers.py` (`updated_by`
  returns full user data — forward-compat with the develop-era removal of
  global user fetching).

## Environment
- `uv` manages the Python venv (`.venv`), pinned to **Python 3.12** via `.python-version`
  (uv defaults to 3.14 — `numpy==2.2.6` has no wheel for it and fails to build).
  Re-pin if `.venv` is recreated: `uv python pin 3.12 && uv sync --frozen`
  (1.23.x has no upstream uv.lock — we generated one; it's committed on `custom`)
- `bun` for the frontend workspace in `web/` — but 1.23.x is **yarn-era**:
  `yarn.lock` is the canonical lockfile (bun migrates it on `bun install`)
- `make` is GNU Make 4.4.1 (ezwinports binary) dropped into `PortableGit/mingw64/bin`
- No Docker — run everything locally
- If package downloads time out: `UV_HTTP_TIMEOUT=300 uv sync --frozen`
- **`PYTHONUTF8=1` is required** for all `manage.py` commands on this Windows
  locale — `check_for_the_latest_version` prints a `→` char that crashes on
  cp1251 (UnicodeEncodeError at settings import).
- Never run `uv sync`/`uv run --frozen` while runserver is up — uv kills
  `.venv` DLLs the server holds (Access denied / broken cryptography).
  Use `uv run --no-sync` for manage.py while the server runs.

## Run backend (SQLite)
```bash
PYTHONUTF8=1 DJANGO_DB=sqlite LOG_DIR=tmp DEBUG=true DJANGO_SETTINGS_MODULE=core.settings.label_studio \
  uv run --frozen python label_studio/manage.py runserver 127.0.0.1:8080   # :8080
```
Django shell: same env + `shell -c "..."`.
SQLite DB lives outside the repo: `%LOCALAPPDATA%\label-studio\label-studio\`

## Frontend build (1.23.x — nx + webpack, NOT vite)
```bash
cd web && bun install            # migrates yarn.lock -> bun.lock
mv web/bun.lock web/bun.lock.bak # nx 21 cannot parse bun.lock v2; it falls back to yarn.lock
bunx nx run editor:build:production       # -> web/dist/libs/editor (bundles custom/ too)
bunx nx run labelstudio:build:production  # -> web/dist/apps/labelstudio
```
Filenames are unhashed (`main.js`, `main.css`) and `/react-app/` serves
straight from `web/dist` — `collectstatic` is only needed for Django admin etc.
`{% manifest_asset %}` falls back to `/react-app/<name>` — a stale
`core/static_build/js/manifest.json` (e.g. left over from a develop checkout)
MUST be deleted or it injects non-existent hashed names -> white screen.

## Deploying frontend changes
```bash
cd web && bunx nx run editor:build:production && bunx nx run labelstudio:build:production
# react-app assets are served directly from web/dist — usually no restart needed,
# but hard-reload the browser (service worker may precache).
```

## Tests
```bash
cd web && bun test libs/editor/src/custom/__tests__/   # run files one by one
```
`web/bunfig.toml` + `web/test/bun/preload.ts` are OUR minimal harness
(jsdom, `mock`/`spyOn`/`mockModule` globals, `APP_SETTINGS`, css/asset stubs)
— the heavy upstream preload only exists on develop; don't copy it.

## Porting notes for future release merges
- `Annotation.setupHotKeys` on 1.23.2 has 4 `addKey` call sites; develop added
  a 5th (randomizable child hotkeys) — wrap it in `guardedHotkey(node)` too
  when it lands in a merged release.
- `data_manager/serializers.get_updated_by` must keep returning full user
  data (see FIT-1658 upstream fix for `get_annotators` — same crash pattern).
- `tags/Custom.jsx` stub guards with `!Registry.models.custominterface` —
  keep our `import "../../custom"` AFTER it in `App.jsx`.

## Task assignment pattern used in this repo's demo
Tasks carry `data.assigned_to` (`ann1..ann4`). Per-annotator Data Manager
views filter on column `filter:tasks:data.assigned_to` (operator `equal`,
type `String`). Labeling from a filtered view routes through the `dm_queue`
path which serves only that view's tasks — honor-based workload splitting
in OSS (no real per-user assignment, that's Enterprise).
