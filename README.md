# work_manager_automation (Brique 2)

Personal, private automation layer around [work_manager](https://github.com/) (Brique 1):
scans a job tracker (Craft), drives `work_manager`'s MCP server to
create/export applications, and generates a personalized cover-letter draft
with a local LLM. Never touches cloud LLMs - personal/sensitive data stays
local (LM Studio, running on the same machine).

## Status

- **Craft integration**: implemented and validated against the real tracker.
  `fetch_new_offers()`/`mark_started()`/`mark_applied()` all confirmed
  against the live API - see `craft/tracker.py`'s docstring for the data
  model (one collection item per company, offers as nested checklist
  blocks, not a per-item property).
- **LM generation**: implemented (`llm.py`) - a single scoped call to a
  local LLM via LM Studio's OpenAI-compatible API, model/prompt/params
  chosen after extensive manual comparison (see
  `docs/implementation_plan.md`). No RAG - the corpus is small enough to
  stuff into the prompt whole; revisit if/when the corpus grows.
- **MCP server** (`mcp_server.py`): exposes `list_untouched_offers` /
  `start_application` / `finalize_application` to an interactive agent
  (e.g. LM Studio Bionic) - deliberately excludes work_manager's
  preset-admin tools and Craft's raw block-editing API.
- **Not done yet**: CV generation (untested so far - all testing was LM
  only), and actually wiring an agent (Bionic) to the MCP server for a real
  interactive session. See `docs/implementation_plan.md` for the full
  sequence and what's left.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requires:
- The `work_manager_mcp` binary built and available (defaults to
  `~/workManager/work_manager_mcp`, override with `WM_MCP_BINARY`).
- LM Studio running locally with its server started (Developer tab -
  Start Server) and a model loaded - defaults to
  `qwen/qwen3.6-35b-a3b` at `http://localhost:1234/v1`.
- A text-based work_manager preset for the LM (not the default `.pages`
  one, which this pipeline would corrupt by writing plain text into it) -
  `default_automation_preset` in `config.py` expects one named
  `"automation"` unless overridden.

Env vars (e.g. in a local `.env`, never committed - see `.gitignore`):

- `CRAFT_API_TOKEN` - Bearer token from the Craft connection's Connections tab.
- `CRAFT_API_BASE` - your Craft connection link
  (`https://connect.craft.do/links/<your-link>/api/v1`).
- `CRAFT_TRACKER_DOCUMENT_ID` / `CRAFT_TRACKER_COLLECTION_ID` - ids of your
  tracker document and its collection.
- `LLM_API_BASE` / `LLM_MODEL` - default to LM Studio's local server and
  the validated model.
- `LLM_SYSTEM_PROMPT_PATH` - defaults to `prompts/lm_system_prompt.md`.
- `LLM_TEMPERATURE` / `LLM_REASONING_EFFORT` / `LLM_TIMEOUT_SECONDS` -
  default to what was validated; `LLM_REASONING_EFFORT` unset means "let
  the server use its own default", not a specific value.
- `WM_CORPUS_PATH` - defaults to `~/workManager/allExperiences.yaml`.
- `WM_DEFAULT_AUTOMATION_PRESET` - defaults to `"automation"`.

There's a Bruno collection at `bruno/craft-api/` for exploring the Craft
API by hand if you need to (01-09).

## Usage

### CLI (manual, one call at a time)

```bash
python -m wm_automation.cli poll   # read-only: list untouched offers
python -m wm_automation.cli prepare --company "Acme" --title "SWE Intern" \
  --url "https://..." --description "..." --motivation "..."
# review/edit the generated LM draft it points you to, then:
python -m wm_automation.cli finalize --id CA-XX...
```

`prepare` records the offer in `~/.wm_automation/offers.json` keyed by
application id (so `finalize` can look it up to report back to Craft), and
tries to check "Commencé la candidature ?" in Craft if the offer came from
`poll`/Craft; `finalize` tries "Postulé ?" the same way. Both are
best-effort - a manually-entered offer (no Craft ids) just skips this.

### MCP server (for an interactive agent, e.g. LM Studio Bionic)

```bash
.venv/bin/wm-automation-mcp
```

Point an MCP-capable host at this binary's path (it doesn't need to share
this venv). It exposes three tools - `list_untouched_offers`,
`start_application` (asks for the person's motivation, generates the LM
draft, never exports), `finalize_application` - and nothing else; no
preset administration, no raw Craft block access.

# Note on AI usage
This repo was written with the help of AI Agents, notably to kickstart the mcp.py and boilerplate code, and to write documentation. However, design decisions, tests and experiments are my own

## Next steps

See `docs/implementation_plan.md` for the tracked sequence. In short: CV
generation, then wiring an agent to the MCP server above for the real
interactive session - plus two non-blocking parallel tasks (corpus
enrichment, example cover letters for style calibration).
