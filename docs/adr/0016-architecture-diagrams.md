# 0016 — Architecture diagrams from the scan

Date: 2026-11-19

## Status

Accepted

## Context

A new repository gets CI, guards, and a design note, and still has no picture
of how the pieces fit. People ask for one during onboarding. Mermaid's C4 and
architecture-beta diagram types are still beta, and a diagram that fails to
parse must not stop init. Existing installs already have a config and must
keep working until someone applies again with the feature on.

## Decision

1. New configs set `features.architecture_diagrams` to true and include a
   `diagrams` block (`engine` mermaid, three views, `max_nodes` 9,
   `ci_validate` false). A config that omits the key stays valid and does
   not gain diagrams.
2. A stdlib emitter turns `detect.py` output into Mermaid `flowchart` and,
   when a server framework was detected, one `sequenceDiagram`. Output is
   deterministic, capped at 9 nodes a view, and uses one `classDef` accent
   on the focal flowchart node. Blocks live in `docs/architecture/overview.md`
   between markers. Re-apply replaces the blocks and keeps the surrounding
   text. A file with no markers is not overwritten.
3. Emitter, scan, and write failures are warnings. Init, apply, and the other
   doctor checks keep going. Doctor itself warns on a missing file or a
   drifted block and never fails the scorecard for diagrams.
4. `diagrams.ci_validate` opts into a workflow that renders with
   `beautiful-mermaid` 1.1.3. mermaid-cli is documented as the strict
   alternative and reuses Chrome for Testing `157.0.8103.38` with
   `PUPPETEER_SKIP_DOWNLOAD`. It is not the default.
5. A presentation pass that writes HTML and SVG under
   `docs/architecture/presentation/` is documented for the init skill. It
   uses `cathrynlavery/diagram-design` at a pinned commit.
   `catherynlavery/diagram-design` is an impostor and is not used. CI does
   not regenerate that directory. D2 is named as an alternative and is not
   generated.

## Consequences

- New inits write `docs/architecture/overview.md` plus copies of the checker
  and the scanner under `.sdlc/scripts/` so the weekly doctor can redraw
  without the plugin.
- Existing installs do not change until the feature is set and apply runs.
- The Lighthouse floors and the Chrome pin are unchanged. The pin is only
  cited for the optional mermaid-cli path.
