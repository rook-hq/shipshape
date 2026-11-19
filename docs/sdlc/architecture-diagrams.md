# Architecture diagrams

Shipshape can draw a first picture of a repository from the scan `detect.py`
already makes. The picture is Mermaid, in C4 style, using plain `flowchart`
and `sequenceDiagram` syntax. It is not a design tool, and it does not decide
how the software should be built.

New setups turn this on (`features.architecture_diagrams` defaults to true).
An existing `.sdlc/config.json` that does not have the key is left alone until
someone sets the key and applies again.

## What gets written

`docs/architecture/overview.md` holds three views when the scan supports them:

- **System context.** The project, a person, and a GitHub or package-registry
  box when the scan saw one.
- **Container view.** The main language, other languages, detected frameworks,
  and the test runner.
- **Request flow.** One sequence diagram, only when the scan sees a server
  framework (Express, Next.js, FastAPI, Flask, or Django). A React-only
  repository does not get a made-up request path.

Each view has at most `diagrams.max_nodes` nodes (default 9, and never more
than 9). Extra nodes become one "Other parts" node. One accent class
(`classDef accent`) marks the focal node of each flowchart. The same scan
produces the same bytes.

Generated blocks sit between markers:

```text
<!-- shipshape:architecture:system_context:start -->
...
<!-- shipshape:architecture:system_context:end -->
```

A later apply replaces those blocks and keeps text outside them. A file that
already exists and has none of the markers is left untouched. If drawing
fails, init still finishes and the plan carries a warning.

The health check also copies `scripts/architecture.py` and `scripts/detect.py`
to `.sdlc/scripts/` so doctor can redraw the blocks without the plugin
installed. Those two files follow the normal "ask before overwrite" rule.

## Config

```json
"features": { "architecture_diagrams": true },
"diagrams": {
  "engine": "mermaid",
  "views": ["system_context", "container", "request_flow"],
  "max_nodes": 9,
  "ci_validate": false
}
```

`diagrams.engine` must be `mermaid`. D2 is not an engine value. `views` must
be unique names from the three above. `max_nodes` is an integer from 1 to 9.
`ci_validate` is a boolean and stays false unless someone asks. It requires
`features.architecture_diagrams` to be true. A config with no `diagrams`
block is still valid.

## Doctor

When the feature is on, doctor warns if `docs/architecture/overview.md` is
missing or a generated block differs from a fresh scan. The check is WARN,
never FAIL. When the feature is off, the check passes and says so.

## Optional CI check

Set `diagrams.ci_validate` to true and apply. The workflow
`.github/workflows/architecture-diagrams.yml` installs `beautiful-mermaid`
at the exact version `1.1.3` and renders each Mermaid block to SVG. That
proves the diagram parses. It does not publish the SVG, and it does not
touch `docs/architecture/presentation/`.

`beautiful-mermaid` rejects a leading `---` frontmatter block and the
`architecture-beta` diagram type. The emitter does not use those, and it
does not use `C4Context`.

The strict alternative is mermaid-cli (`@mermaid-js/mermaid-cli`). It needs
a browser. Reuse the pinned Chrome for Testing build `157.0.8103.38` (the
same pin as `.github/workflows/lighthouse.yml`) and set
`PUPPETEER_SKIP_DOWNLOAD=1` so Puppeteer does not download a second browser.
Point `PUPPETEER_EXECUTABLE_PATH` at that Chrome binary. Shipshape does not
run mermaid-cli unless you add that yourself. The Lighthouse job and its
floors stay as they are.

## Optional presentation pass

After init, a person can ask for a designed picture. That pass is not part
of init and CI never regenerates it. Use the diagram-design skill from
exactly `https://github.com/cathrynlavery/diagram-design` at commit
`d74d8c2d0c78a9e1efd43137f6a9a51182a8b5f0`. The owner is `cathrynlavery`.

`catherynlavery/diagram-design` is an impostor fork and must never be used.

Write the HTML and SVG under `docs/architecture/presentation/`. Leave the
generated Mermaid blocks in `docs/architecture/overview.md` in place.

D2 (https://d2lang.com) is a documented alternative only. Shipshape does not
generate D2 and does not install it.
