# Local Assistant for Gemini CLI - Development Context

This project provides a secure, private bridge between the cloud-based Gemini CLI and the user's local machine. It allows Gemini to perform complex tasks (searching, refactoring, summarization) locally, ensuring sensitive data remains on the host while delegating "execution" to a local AI model (via Ollama).

## Architecture: "Cloud Brain, Local Hands"

- **Frontend:** Gemini CLI running in **Interactive Mode**.
- **Integration:** Runs as a child process via **Stdio** transport.
- **Discovery Layer:** Automatically inspects the local model (Ollama) to detect native context limits.
- **Execution Engine:** Iterative loop with a **Context Guard** that truncates large outputs to prevent memory overflow.
- **Security Layer:** 
    - **Inherited Sandbox:** Relies on the Gemini CLI's `sandbox-exec` wrapper (`gemini -s`).
    - **Self-Check:** The assistant refuses to start unless it detects it is running within a macOS sandbox via `libsandbox`.
- **Backend Models:**
    - **Local (User Choice):** Default is `qwen3-coder:30b` via Ollama.
    - **Cloud Brain (Gemini):** High-level reasoning and orchestrator.

### Model Ecosystem

| Model | Role | Type | Trigger |
| :--- | :--- | :--- | :--- |
| **Local (User Choice)** | **Local Agent** | Local | Tool: `ask_local_assistant` |
| **Gemini (Cloud)** | **Brain** | Cloud API | Default Reasoning / Orchestrator |

## Building and Running

### Prerequisites
- **macOS**: Required for `libsandbox` security.
- **Ollama**: Must be installed and running.
- **Gemini CLI**: The host application.

### Installation
Run the provided installer to set up the environment and register the extension:
```bash
./install_extension.sh
```
This script:
1.  Checks for Ollama.
2.  Prompts for a default local model.
3.  Creates a virtual environment in `~/.gemini-local-assistant`.
4.  Generates a `run_safe` wrapper script.
5.  Registers the server with Gemini CLI.

### Running
The server is started automatically by Gemini CLI when needed.
**CRITICAL:** Gemini CLI must be launched with the `-s` (sandbox) flag for the Local Assistant to function.
```bash
gemini -s "your prompt here"
```

### Testing
Tests are located in the `test/` directory and use `pytest`.
```bash
pip install -r requirements-dev.txt
pytest
```
Tests cover:
- Sandbox detection (`libsandbox.1.dylib`).
- Partial file reading (offset/limit for text, pages for PDF).
- Tool execution logic.
- The iterative agent loop (using mocked Ollama responses).

## Development Conventions

### Tools
Tools are defined using the `@mcp.tool()` decorator in `mcp_server.py`. Primary tools include:
- **`ask_local_assistant`:** The main iterative reasoning agent. Supports `use_plan`, `num_ctx`, and `max_turns`.
- **`run_shell_command`:** Executes `zsh` commands (batch support).
- **`read_file`:** Reads files with `offset/limit/pages` (batch support).
- **`write_file`:** Direct file access within the working directory.
- **`get_model_info`:** Retrieves local model metadata.
- **`request_clarification`:** Pauses execution to ask the user a question.
- **`list_local_models`:** Lists available Ollama models.

### Code Structure
- `mcp_server.py`: The entry point and definition of all MCP tools.
- `ask_local_assistant`: The primary tool used by Gemini. it implements two modes:
    - **Direct Execution:** Single-turn or simple iterative tasks.
    - **Planning Mode (`use_plan=True`):** A two-phase workflow (Planning -> Execution) that uses a Markdown checklist at `.gemini/local_plan.md`.

### Adding Tools
If a tool is intended to be used *internally* by the local agent, it must be added to the `tools` list within the `ask_local_assistant` function.

### Security and Privacy
- **Sandboxing:** The server checks for the macOS sandbox at startup and refuses to run without it.
- **Local-Only:** File reading and shell execution are performed locally. The agent is instructed to only return the specific requested information to Gemini (Cloud) to minimize data exposure.
- **Anonymization:** The agent is prompted to anonymize PII unless specifically requested otherwise.

## Future Roadmap

- [ ] **Robust Planning:** Improve vague task handling via discovery turns.
- [ ] **Intelligent Summarization Pass:** Optional flag for summarizing massive files.
- [ ] **Local RAG:** Integrate Vector DB for project-wide semantic search.
- [ ] **Safe Mode (Read-Only):** A dedicated tool with zero write/execute permissions.
- [ ] **Dynamic Model Routing:** Support task-specific model selection.
- [ ] **Subagent Integration:** Refactor into a formal Subagent for cleaner delegation.
- [ ] **Asynchronous Execution:** Support parallel background processing for long local tasks.
- [ ] **Standalone CLI Mode:** Develop a terminal-based frontend for independent, local-only use.
