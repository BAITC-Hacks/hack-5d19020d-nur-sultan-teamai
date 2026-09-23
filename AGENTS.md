<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.

---

## Hackathon project context

- Repo: `BAITC-Hacks/hack-5d19020d-nur-sultan-teamai`
- Local path: this directory only. Do not write product code into the parent `Hackhathon` folder.
- The human handles `git push`. Do **not** commit or push unless explicitly asked.
- Prefer small, shippable increments over large refactors.
- Keep secrets out of the repo: use `.env` / GitHub Actions secrets, never commit API keys.
- Local hackathon runs: put keys in repo-root `.env` (and/or `demo/.env`). Both are gitignored.
  Packages auto-load them on import (`wind_demo.config` / `wind_agent.config`). Copy
  `.env.example` → `.env` once; do not paste real keys into README or commits.

## Working agreements

- After the stack is chosen, document exact commands below and keep them accurate.
- Before finishing a task: run the relevant install/build/lint/test commands when they exist.
- Prefer editing existing files over creating speculative scaffolding.
- Do not install marketing / Vis-à-Vis product skills into this repo.
- UI work: use the `impeccable` skill when designing or polishing frontend.

## Commands (fill in when stack exists)

```bash
# install
.\scripts\setup.ps1

# dev
.\scripts\start.ps1 -OpenBrowser

# lint / typecheck
.\scripts\run.ps1 release-check

# test
.\scripts\run.ps1 release-check

# build
.\scripts\run.ps1 run-all --profile mvp
```

## Directory map (update as the project grows)

```text
.
├── AGENTS.md
├── README.md
├── .agents/skills/          # gh-fix-ci, gh-address-comments, git-commit-writer, pr-description-writer
├── .cursor/                 # Cursor MCP + impeccable skill
└── .code-review-graph/      # local graph DB (gitignored)
```

## Forbidden

- Committing `.env`, credentials, or private keys
- Force-pushing to `main`
- Rewriting unrelated history or mass-formatting the whole repo
- Copying the Vis-à-Vis product brief or marketing skill pack into this project
