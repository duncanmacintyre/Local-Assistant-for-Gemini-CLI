# Local Assistant for Gemini CLI

**A secure, private bridge between Gemini (Cloud) and your local machine.**

This extension allows the Gemini CLI to safely interact with your local files and execute commands by delegating sensitive tasks to a local AI model (via Ollama). It runs entirely within the Gemini CLI's native sandbox.

It is designed for use on macOS and is not compatible with other operating systems.

Privacy is never guaranteed. Sensitive data could be sent to the cloud if it is included in the local assistant's responses to Gemini.

## 🚀 Why use this?
*   **Cost:** Offloads heavy processing (like reading long logs) to your local machine.
*   **Speed:** Local operations may run faster than cloud analysis.
*   **Privacy:** Summarize sensitive PDFs or analyze private code without uploading files to the cloud.
*   **Security:** Runs inside a strict macOS sandbox (`seatbelt`). It cannot touch files outside the current directory.
*   **Power:** Gives Gemini "hands" to run shell commands (`grep`, `find`, `ls`) and read files iteratively.

## 🛠️ Prerequisites
1.  **macOS:** Required for the security sandbox (`libsandbox`).
2.  **[Gemini CLI](https://github.com/google/gemini-cli):** The host application.
3.  **[Ollama](https://ollama.com/):** To run the local AI model.

## 📦 Installation

1.  **Start Ollama** and pull a capable model (we recommend `qwen3-coder:30b` if you have at least 32 GB of RAM):
    ```bash
    ollama pull qwen3-coder:30b
    ```

2.  **Run the Installer:**
    ```bash
    ./install_extension.sh
    ```
    *This script sets up a virtual environment, registers the extension with Gemini, and lets you select your default local model.*

## 💡 Usage

**You must use the `-s` (sandbox) flag when starting Gemini CLI.**
The Local Assistant will refuse to start if sandboxing is disabled.

### Example 1: Summarize a Private PDF
The PDF never leaves your machine. The local model reads it and sends only the summary to the cloud.
```bash
gemini -s "Use the local assistant to summarize the key points in 'contract_draft.pdf' and save the summary to 'summary.md"
```

### Example 2: Codebase Investigation
The local agent can search and read multiple files to answer complex questions.
```bash
gemini -s "Ask the local assistant to find where 'API_KEY' is used in this folder and check if it's hardcoded."
```

### Example 3: Local Refactoring
```bash
gemini -s "Tell the local assistant to better organize the functions in 'utils.py'."
```

### Example 4: Deep Work (Planning Mode)
For complex tasks (e.g., "Refactor the entire module" or "Investigate this bug across 5 files"), the assistant can enter **Planning Mode**.
*   **Phase 1:** It creates a checklist in `.gemini/local_plan.md`.
*   **Phase 2:** It executes the plan step-by-step, updating the checklist as it goes.
*   *Trigger:* This mode is automatically selected by Gemini when you ask for "complex" or "multi-step" tasks, or you can explicitly ask:
    ```bash
    gemini -s "Use the local assistant in planning mode to refactor the test suite."
    ```

## ✨ Key Features
*   **Turn Limit Control:** Gemini can control the agent's iterative depth via `max_turns` (default: 20 direct, 40 planning), allowing it to scale effort based on task complexity.
*   **Recursive Codebase Search:** Uses `grep`, `rg`, and `find` to explore projects of any size.
*   **Intelligent Planning:** For complex tasks, the assistant generates a Markdown checklist and executes it step-by-step.
*   **Batch Operations:** Tools like `read_file` and `run_shell_command` support multiple paths/commands in a single turn, significantly reducing latency.
*   **Context Guard:** Automatically detects large outputs and truncates them with segmentation instructions (offset/limit/pages), preventing local model context overflow.
*   **Model Discovery:** Automatically detects your local model's native context limit and optimizes reasoning accordingly.
*   **Interactive Clarification:** If a task is ambiguous, the assistant can pause and ask the user for missing information via Gemini.
*   **PDF Support:** Native PDF reading and page-by-page extraction.
*   **Resource Management & Cancellation:** Fully asynchronous execution allows for immediate interruption of local model inference and shell commands when a task is cancelled in Gemini CLI (Esc), ensuring no orphaned processes or GPU/CPU leakage.

## 🏗️ Architecture

This project implements the **"Cloud Brain, Local Hands"** pattern:

1.  **Gemini (Cloud)** is the "manager". It understands your intent and high-level goals.
2.  When it encounters a suitable task, Gemini calls the `ask_local_assistant` tool.
3.  The **Local Assistant** (running on your Mac) accepts the sub-task. It enters a **"Think-Act-Observe"** loop:
    *   It *plans* using your local model (e.g., Qwen/Llama).
    *   It *acts* by running shell commands or reading files.
    *   It *observes* the output and refines its plan.
4.  Once finished, it returns the final answer to Gemini.

## 🗺️ Roadmap

This section outlines upcoming features planned for the Local Assistant, prioritizing enhancements for robustness, intelligence, and user experience.

### 1. Robust Planning: Better Vague Task Handling
*   **Problem:** The assistant can struggle to formulate a concrete plan when given broad or vague instructions (e.g., "Audit the code"), leading to failures during the planning phase.
*   **Action:** Improve the planning logic for vague tasks. This may involve a mandatory "discovery turn" to explore the codebase before committing to a plan, or more structured "Thinking" prompts to help the model decompose abstract goals.

### 2. Intelligent Summarization Pass
*   **Problem:** For extremely large files (massive logs or long legal documents), simply truncating or reading page-by-page can be slow for getting a high-level overview.
*   **Action:** Add an optional `summarize` flag to tools. If enabled, the local agent will perform a quick local summarization pass (using the local model) before returning the text to Gemini.

### 3. Local RAG: Semantic Search and Project Indexing
*   **Problem:** The assistant's current search capabilities are limited to basic text matching (`grep`, `find`), which is inefficient for understanding complex codebases or answering semantic queries.
*   **Action:** Integrate a local Vector Database (e.g., ChromaDB, FAISS) for project-wide indexing. This will enable a new `semantic_search` tool for the local agent, allowing for more intelligent and context-aware code exploration.

### 4. Privacy-Conscious Web Search
*   **Problem:** The assistant currently lacks real-time information access from the web, limiting its ability to consult external documentation or current data.
*   **Action:** Introduce an opt-in `live_search` tool. This feature will allow the local agent to perform web searches (e.g., via Perplexity) without compromising local file privacy by only sending specific queries.

### 5. Dynamic Model Ecosystem
*   **Problem:** A single, monolithic local model is used for all tasks, which may not be optimal for performance, cost, or specialized capabilities.
*   **Action:** Implement dynamic model routing. The assistant will be able to select the most appropriate local model based on the task at hand (e.g., a coding-specific model for code generation, a general-purpose model for summarization).

### 6. Safe Mode (Read-Only)
*   **Problem:** Even with sandboxing, a powerful agent might accidentally overwrite a file or run a destructive command during complex investigations.
*   **Action:** Expose a dedicated `ask_local_assistant_readonly` tool. This version will strictly lack `write_file` and `run_shell_command` capabilities, allowing users to perform "pure" analysis and summarization with zero risk of side effects.

### 7. Subagent Integration
*   **Problem:** The assistant is currently implemented as a standard MCP tool, which doesn't leverage Gemini CLI's native "Subagent" architecture for cleaner delegation and domain-specific personas.
*   **Action:** Refactor the assistant into a formal Subagent. This involves creating an agent definition (`.gemini/agents/local-assistant.md`) that encapsulates the planning and execution logic, making delegation more seamless and idiomatic.

### 8. Asynchronous / Parallel Execution
*   **Problem:** The "Cloud Brain" (Gemini) currently waits for the "Local Hands" to finish before continuing, preventing simultaneous work (e.g., Gemini researching while the local agent refactors).
*   **Action:** Explore an asynchronous worker model. This would likely involve a standalone CLI script that Gemini can start as a background process, with a mechanism (like log polling or a status tool) to monitor progress and collect results without blocking the main conversation.

### 9. Standalone CLI Mode
*   **Problem:** The local assistant is currently tied to the Gemini CLI ecosystem, requiring a Cloud-based "Brain" for orchestration and limiting its use to Gemini users.
*   **Action:** Develop a standalone terminal frontend. This would allow the local assistant to be used as an independent, 100% private autonomous agent. It would manage its own "Manager" loop locally via Ollama, making it a powerful tool for users in air-gapped or cloud-restricted environments.

## 🔧 Troubleshooting

| Error Message | Cause & Fix |
| :--- | :--- |
| `CRITICAL ERROR: Local Assistant MUST be run within a Gemini CLI sandbox` | You forgot the `-s` flag. Run `gemini -s ...` |
| `No local models found in Ollama` | Ollama isn't running or you haven't pulled a model. Run `ollama serve` and `ollama pull <model>`. |
| `Error reading file...` | The file might not exist, or the sandbox prevented access (you can only access files in the current directory). |

## 🗑️ Uninstall

To completely remove the Local Assistant:

1.  **Unregister from Gemini CLI:**
    ```bash
    gemini mcp remove --scope user local-assistant
    ```

2.  **Delete the installation directory:**
    (Replace `~/.gemini-local-assistant` if you chose a different path during installation)
    ```bash
    rm -rf ~/.gemini-local-assistant
    ```

## 📜 License
MIT

Software developed with Gemini 3.0 Pro in Gemini CLI.
