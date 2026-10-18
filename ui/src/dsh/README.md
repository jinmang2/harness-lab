# Vendored from DeepSeek Harness (MIT)

Files here are copied unchanged from https://github.com/deepseek-ai/deepseek-harness
(`packages/client/*`, version 0.1.5-rc.3) under the MIT License in `LICENSE`:

- `design-platform.css`, `base.css`, `scrollbar.css`, `corner-shape.css`, `gradient-shadow-text.css` — ui-theme tokens
- `icons.tsx`, `icon-props.ts` — ui-primitives icon set (import path of props renamed)
- `css/*.module.css` — component styles from ui-layout, ui-sidebar, ui-workspace, ui-conversation,
  ui-chat, ui-tool, ui-primitives, ui-trajectory, ui-settings-*, ui-agent-preset, ui-model-selection,
  ui-approval, ui-sidebar-right, ui-sidebar-files, ui-sidebar-documentpreview, ui-theme, locale

Added later from the same repository at 0.2.1-alpha.5, also unchanged:

- `css/SubagentHeaderLineage.module.css`, `css/SubagentReadOnlyComposer.module.css` — ui-subagent
- `css/ToolDetails.module.css` — ui-tool

The DeepSeek logo and wordmark are not copied. Components that use these styles are our own
(`../components`), written to produce the same DOM structure as DSH Web.
