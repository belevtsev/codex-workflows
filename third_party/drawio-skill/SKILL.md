---
name: drawio-skill
description: Create or edit Draw.io diagrams with custom layout, shapes, or requested PNG/SVG/PDF exports, retaining an editable source and inspecting the rendered result.
license: MIT
metadata:
  author: Agents365-ai
  upstream-version: "1.28.0"
  homepage: https://github.com/Agents365-ai/drawio-skill
  compatibility: Native draw.io CLI; Graphviz is optional for computed layout.
---

# Editable Draw.io diagrams

Use this workflow for a requested Draw.io artifact or an export needing its shapes and layout. A small diagram intended for Markdown can use Mermaid directly. Follow a user-specified format and output location; do not introduce another application just because it is listed here.

Identify the question the diagram answers, its entities, relationship direction, and level of detail. For code or infrastructure, ground semantic claims in source evidence; an import graph is not proof of runtime ownership or traffic. Separate observed, proposed, and unknown behavior.

Select only the resources needed:

| Need | Reference |
| --- | --- |
| Find a generator, importer, converter, or viewer | [Toolbox](references/toolbox.md) |
| Hand-author custom XML and geometry | [XML authoring](references/xml-authoring.md) |
| Standard Mermaid-to-Draw.io conversion with a compatible CLI | [Mermaid authoring](references/mermaid-authoring.md) |
| Large graph layout and routing | [Autolayout](references/autolayout.md) |
| Requested style or remembered local preset | [Style presets](references/style-presets.md) |
| Runtime infrastructure rather than declared files | [Live infrastructure](references/live-infra.md), within the authorized read scope |
| CLI export, preview inspection, or renderer failure | [Export workflow](references/export-workflow.md) |

For an existing diagram, preserve meaningful IDs, groups, and relationships while making the requested edit. For a new one, choose direct authoring or a relevant generator; prefer computed layout when manual placement would obscure a large graph. Validate its structure with `scripts/validate.py`, then export and inspect a preview when the renderer is available. Check arrow direction, missing/dangling connections, clipped labels, overlap, grouping, and readability at the intended size.

Correct defects found during inspection and deliver the requested formats with the editable source. Ask for design feedback when a material design choice is unresolved or the user requested staged review; final export of an already requested artifact does not require another approval. Do not repeatedly rerender unchanged output. If a renderer or format is unavailable, deliver the usable source and clearly identify the missing export or visual verification.
