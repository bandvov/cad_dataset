# frontend

Three-panel CAD copilot UI, with a titlebar/project switcher above it:
feature tree (left) / 3D viewport (center) / chat (right). Talks only to
`llm-service` -- it never calls the geometry service directly, matching
the architecture from the earlier discussion (the frontend is a
product-layer client, not a geometry-service consumer).

```
+---------------------------------------------------------------------+
| CAD COPILOT          [ Mounting bracket ▾ ]                          |  <- titlebar
+------------------+-----------------------------------+------------------+
|  FEATURE TREE     |                          ↓STEP ↓STL ↓GLB          |  CHAT             |
|  ▱ sketch_1        |          [ 3D VIEWPORT ]            |  You: a bracket…  |
|  ↑ extrude_1       |          blueprint grid              |  Assistant: Done. |
|  ◟ fillet_1        |          orbit camera                 |                   |
|                    |                                     |  [ type… ]  Send  |
|  STATS             |                                     |                   |
|  volume / faces    |                                     |                   |
+------------------+-----------------------------------+------------------+
     290px                       flex: 1                       380px
```

## Design choices (not defaults)

Built for the actual subject -- a drafting/engineering tool, not a generic
chat app -- rather than reaching for template defaults:

- **Palette**: warm charcoal (`#14161a`) background, one accent -- a
  desaturated steel-cyan (`#4fb8c4`) evoking pencil-on-blueprint tracing,
  not a neon "AI" glow or a SaaS brand blue. Amber/brick-red reserved for
  warnings/errors, used sparingly.
- **Type**: IBM Plex Mono for anything numeric/technical (feature params,
  stats, the viewport HUD readout) -- a face designed for technical
  contexts, not just "a monospace font." IBM Plex Sans for chat prose.
- **Sharp corners throughout**, hairline 1px borders between panels --
  drafting-table surfaces, not floating SaaS cards with shadows and
  border-radius.
- **Signature element**: the 3D viewport's blueprint-style ground grid and
  monospace HUD corner readout (bounding-box dimensions) -- one deliberate
  technical touch, everything else quiet.

Full token list in `src/styles.css` (top of file).

## Verification status

No network in the sandbox this was authored in, so `npm install` against
the real registry was never run and the app was never loaded in a browser.
What WAS verified:
- Every `.jsx`/`.js` file transforms cleanly through `esbuild` (real JSX
  parsing, not just an AST check).
- A full bundle-resolution pass (`esbuild --bundle`, external-ing
  `react`/`three`) confirms every **local** import path resolves correctly
  -- `App.jsx` finding `./components/*`, `./api`, `./styles.css`, etc.
  This catches the class of bug that per-file syntax checking can't.

What's NOT verified: `three`'s addon import paths
(`three/addons/controls/OrbitControls.js`, `three/addons/loaders/GLTFLoader.js`
-- the current officially-recommended alias) against your exact installed
`three` version. The older `three/examples/jsm/...` path also still works
in current three.js releases as of this writing, so that's the fallback if
`addons` doesn't resolve for some reason -- check
`node_modules/three/examples/jsm/` either way to confirm what your
installed version actually ships. Actual rendering correctness (does the
model look right, does OrbitControls feel right) obviously needs a real
browser -- this was written carefully against three.js's documented
patterns, not executed.

## Running

**Local dev** (fastest iteration, needs Node + your own llm-service running):
```bash
npm install
cp .env.example .env   # or set VITE_LLM_SERVICE_URL directly
npm run dev
```

**Docker, whole application** (preferred): the root `docker-compose.yml`
runs everything together -- see the root `README.md`.
```bash
cd ..
cp .env.example .env
docker compose up --build
```

**Docker, this service only**, joined to an already-running llm-service:
```bash
cp .env.example .env
docker compose up --build
```

**Important**: `VITE_LLM_SERVICE_URL` is baked in at **build** time (Vite
inlines `import.meta.env.*` into the bundle), not read at container start.
Changing it means rebuilding the image, not just restarting the container
-- see the Dockerfile comment. It also needs to be a URL your **browser**
can reach, not a Docker-internal service name (`http://llm-service:8000`
resolves for other containers, not for someone's browser tab) -- use the
host-mapped port or your real domain.

## What's in v1

- **Project switcher** (titlebar): list, switch between, create, and
  delete parts. Backed by endpoints that already existed
  (`llm-service`'s `list_projects`/`create_project`/`delete_project`) but
  previously had no UI -- the frontend only ever worked with one
  auto-created/restored project. `ProjectBar.jsx`; switching reuses the
  same restore logic as page-reload (`App.jsx`'s `loadProject()`), so
  "switch project" and "reload the page" behave identically.
- **Download** (viewport top-right): STEP/STL/GLB, via the same
  `/v1/projects/{id}/render` endpoint the viewport itself already used for
  page-reload restore -- this was backend-complete before but had no
  button anywhere. `Viewer3D.jsx`'s `ExportBar`.
- **Structured editing (Phase 2 item 4)**: click an editable feature in
  the tree to expand a small form and change a dimension directly --
  bypasses the model entirely, validates via `llm-service`'s
  `POST /v1/projects/{id}/apply` (geometry-service check, no LLM call),
  and versions the result exactly like a prompted edit. Scoped to simple
  scalar params (`Extrude.amount`, `Fillet.radius`, pattern counts, a
  single-primitive `Sketch`'s width/height/radius, etc.) -- see
  `src/lib/featureEdit.js`'s `getEditableFields()` for the exact set.
  `Loft`/`Sweep`/`Mirror` stay read-only: their parameters are structural
  (source lists, planes), not a single number a form field represents
  cleanly.
- **Persisted, versioned projects** with undo/redo, surviving a page
  reload (see `App.jsx`'s restore-on-mount and `llm-service/app/store.py`).

## What's intentionally out of scope for v1

- **No conversation/session persistence beyond version history.** Refresh
  restores the current part and a reconstructed history of prompts/edits,
  but not e.g. mid-typing draft text.
