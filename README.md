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

## 🏗️ Architecture

This project implements the **"Cloud Brain, Local Hands"** pattern:

1.  **Gemini (Cloud)** is the "manager". It understands your intent and high-level goals.
2.  When it encounters a suitable task, Gemini calls the `ask_local_assistant` tool.
3.  The **Local Assistant** (running on your Mac) accepts the sub-task. It enters a **"Think-Act-Observe"** loop:
    *   It *plans* using your local model (e.g., Qwen/Llama).
    *   It *acts* by running shell commands or reading files.
    *   It *observes* the output and refines its plan.
4.  Once finished, it returns the final answer to Gemini.

## 🔧 Troubleshooting

| Error Message | Cause & Fix |
| :--- | :--- |
| `CRITICAL ERROR: Local Assistant MUST be run within a Gemini CLI sandbox` | You forgot the `-s` flag. Run `gemini -s ...` |
| `No local models found in Ollama` | Ollama isn't running or you haven't pulled a model. Run `ollama serve` and `ollama pull <model>`. |
| `Error reading file...` | The file might not exist, or the sandbox prevented access (you can only access files in the current directory). |

## 📜 License
MIT

Software developed with Gemini 3.0 Pro in Gemini CLI.

