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

## 🏗️ Architecture

This project implements the **"Cloud Brain, Local Hands"** pattern:

1.  **Gemini (Cloud)** is the "manager". It understands your intent and high-level goals.
2.  When it encounters a suitable task, Gemini calls the `ask_local_assistant` tool.
3.  The **Local Assistant** (running on your Mac) accepts the sub-task. It enters a **"Think-Act-Observe"** loop:
    *   It *plans* using your local model (e.g., Qwen/Llama).
    *   It *acts* by running shell commands or reading files.
    *   It *observes* the output and refines its plan.
4.  Once finished, it returns the final answer to Gemini.

## ✨ Future Features

This section outlines upcoming features planned for the Local Assistant, prioritizing enhancements for robustness, intelligence, and user experience.

### 1. Robust Planning: Better Vague Task Handling
*   **Problem:** The assistant can struggle to formulate a concrete plan when given broad or vague instructions (e.g., "Audit the code"), leading to failures during the planning phase.
*   **Action:** Improve the planning logic for vague tasks. This may involve a mandatory "discovery turn" to explore the codebase before committing to a plan, or more structured "Thinking" prompts to help the model decompose abstract goals.

### 2. Streamlined Execution: Faster Turnaround
*   **Problem:** The iterative "Think-Act-Observe" loop can feel slow due to the overhead of plan management and sequential tool calls.
*   **Action:** Speed up planning and execution by streamlining tool interactions. This includes reducing round-trips for plan updates (e.g., using an in-memory state that only persists periodically), batching operations like `read_file` for multiple paths, and supporting parallel tool execution.

### 3. Technical Robustness: Handling Large Files
*   **Problem:** Current file reading mechanisms can fail or lose context with very large text files or PDFs, exceeding local model token limits.
*   **Action:** Implement context chunking and pagination for handling large files. This will include a "summarize-on-load" feature for substantial documents to ensure manageable input for the local agent.

### 4. Local RAG: Semantic Search and Project Indexing
*   **Problem:** The assistant's current search capabilities are limited to basic text matching (`grep`, `find`), which is inefficient for understanding complex codebases or answering semantic queries.
*   **Action:** Integrate a local Vector Database (e.g., ChromaDB, FAISS) for project-wide indexing. This will enable a new `semantic_search` tool for the local agent, allowing for more intelligent and context-aware code exploration.

### 5. Privacy-Conscious Web Search
*   **Problem:** The assistant currently lacks real-time information access from the web, limiting its ability to consult external documentation or current data.
*   **Action:** Introduce an opt-in `live_search` tool. This feature will allow the local agent to perform web searches (e.g., via Perplexity) without compromising local file privacy by only sending specific queries.

### 6. Dynamic Model Ecosystem
*   **Problem:** A single, monolithic local model is used for all tasks, which may not be optimal for performance, cost, or specialized capabilities.
*   **Action:** Implement dynamic model routing. The assistant will be able to select the most appropriate local model based on the task at hand (e.g., a coding-specific model for code generation, a general-purpose model for summarization).

### 7. Interactive Clarification
*   **Problem:** Currently, if the local agent encounters ambiguity (e.g., "Which file?"), it has to guess or fail because it cannot ask the user for help during execution.
*   **Action:** Implement a "suspend-and-resume" protocol. The agent will be able to return a question to Gemini, which asks the user, and then resumes the local agent with the user's answer and the previous context preserved.

### 8. Batch Tool Operations
*   **Problem:** The agent currently reads files or runs commands one at a time, leading to excessive "thinking" pauses and slow execution for tasks involving multiple files.
*   **Action:** Update tools like `read_file` to accept lists of arguments (e.g., `filepaths=['a.txt', 'b.txt']`). This allows the agent to gather all necessary context in a single turn, significantly reducing latency.

### 9. Safe Mode (Read-Only)
*   **Problem:** Even with sandboxing, a powerful agent might accidentally overwrite a file or run a destructive command during complex investigations.
*   **Action:** Expose a dedicated `ask_local_assistant_readonly` tool. This version will strictly lack `write_file` and `run_shell_command` capabilities, allowing users to perform "pure" analysis and summarization with zero risk of side effects.

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

