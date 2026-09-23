# Team instructions (trial push)

Repo: `BAITC-Hacks/hack-5d19020d-nur-sultan-teamai`

## Who does what

- Agent (Cursor/Codex) writes the code in this folder.
- Human runs `git push` when asked, or asks the agent to push.

## Local setup

1. Open this folder as the Cursor workspace root.
2. Copy `.env.example` → `.env` and fill API keys after redeeming hackathon credits.
3. Restart Cursor so MCP `code-review-graph` loads from `.cursor/mcp.json`.
4. Do **not** commit `.env`.

## Agent tooling already in the repo

- `AGENTS.md` / `.cursorrules` — use code-review-graph before broad file scans
- `.cursor/skills/impeccable` — UI work
- `.agents/skills/` — `gh-fix-ci`, `gh-address-comments`, `git-commit-writer`, `pr-description-writer`

## Secrets reminder

| Hackathon benefit | Where to activate | What goes in `.env` |
|-------------------|-------------------|---------------------|
| ChatGPT / Codex Pro 5x | ChatGPT / Codex account | nothing |
| OpenAI API credits | platform.openai.com | `OPENAI_API_KEY` |
| NVIDIA API tokens | build.nvidia.com | `NVIDIA_API_KEY` |

## Next

Pick one agentic problem for the demo; then we scaffold the agent (tools + loop) without installing heavy frameworks unless needed.
