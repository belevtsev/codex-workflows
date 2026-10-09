# Local export and inspection

Use the installed renderer's actual path and version. On macOS common candidates are `drawio`, `draw.io`, or `/Applications/draw.io.app/Contents/MacOS/draw.io`. Check the available binary once. Version 30 or newer supports Mermaid input; consult [Mermaid authoring](mermaid-authoring.md) before using version-dependent flags. Do not install a renderer or change execution permissions merely to bypass a failed command; follow the current harness permissions and the task's authorized setup scope.

Create a clean preview PNG without `--embed-diagram` (`-e`). A width around 2000 pixels is a useful initial preview size; adjust for the actual viewer rather than assuming another model's hard image limit. For example, substituting the resolved executable:

```sh
drawio -x -f png --width 2000 -o diagram.png diagram.drawio
```

Read the preview with the available image viewer. Fix concrete layout or content problems, rerender, and inspect the changed result. A readable preview and valid XML do not establish architectural correctness; verify the relationships against their sources.

Export all requested formats once the result meets the task. To retain editable XML in a final PNG/SVG/PDF, use the renderer's embedding option and an informative name such as `diagram.drawio.png`. Some renderer builds have produced truncated IEND chunks in embedded PNG exports; `scripts/repair_png.py` handles that known artifact. Use the repair helper for an affected export and validate the actual image, rather than assuming every current renderer has the defect. Preserve the separate `.drawio` source regardless.

If the native CLI fails because of a missing display, process isolation, or Electron startup, inspect the specific failure once and choose a permitted available route. Do not retry the same failure repeatedly. A browser viewer or the editable XML may be a useful fallback; constructing a browser URL can encode the entire diagram, so do not transmit private diagram content to an external service without the user's authorization. Use local outputs when possible. Report an unrendered source as unrendered, and incomplete exports as incomplete.

For generated diagrams, [toolbox](toolbox.md) documents conversion and self-contained viewer helpers. Retain source and exports in the user's requested output location. No feedback loop is required solely to finish an authorized export.
