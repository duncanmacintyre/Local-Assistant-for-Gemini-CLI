import os
import json
import logging
import subprocess
import ctypes
import sys
import ollama
from itertools import islice
from pypdf import PdfReader
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("Local Assistant for Gemini CLI")

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LOCAL_WORKER_MODEL = os.getenv("LOCAL_WORKER_MODEL", "qwen3-coder:30b")

def is_sandboxed() -> bool:
    """Checks if the process is running within a macOS sandbox (seatbelt)."""
    try:
        # libsandbox is available on macOS
        libsandbox = ctypes.CDLL("/usr/lib/libsandbox.1.dylib")
        # sandbox_check(pid, entity, flags) returns 1 if sandboxed
        return libsandbox.sandbox_check(os.getpid(), None, 0) == 1
    except Exception:
        return False

def _read_local_file(filepath: str, offset: int = 0, limit: int = None, pages: list[int] = None) -> str:
    """Helper to read text or PDF files locally with support for partial reading."""
    if not os.path.exists(filepath):
        return f"[Error: File {filepath} not found]"

    if filepath.lower().endswith(".pdf"):
        try:
            reader = PdfReader(filepath)
            total_pages = len(reader.pages)
            text = ""
            
            # If pages are specified, use them (1-indexed for user convenience)
            target_pages = pages if pages else range(1, total_pages + 1)
            
            for p_num in target_pages:
                if 1 <= p_num <= total_pages:
                    text += f"--- Page {p_num} ---\n"
                    text += reader.pages[p_num - 1].extract_text() + "\n"
                else:
                    text += f"[Warning: Page {p_num} out of range (Total pages: {total_pages})]\n"
            return text
        except Exception as e:
            return f"[Error reading PDF {filepath}: {str(e)}]"
    else:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                # Use offset/limit for text files (lines) efficiently with islice
                stop = (offset + limit) if limit else None
                gen = islice(f, offset, stop)
                return "".join(gen)
        except Exception as e:
            return f"[Error reading file {filepath}: {str(e)}]"

@mcp.tool()
async def list_local_models() -> str:
    """
    Lists the available local Ollama models that can be used with ask_local_assistant.
    """
    try:
        models_info = ollama.list()
        models = [m['name'] for m in models_info.get('models', [])]
        if not models:
            return "No local models found in Ollama."
        return "Available local models:\n- " + "\n- ".join(models)
    except Exception as e:
        logger.error(f"Error listing Ollama models: {e}")
        return f"Error listing models: {str(e)}"

@mcp.tool()
async def ask_local_assistant(prompt: str, local_file_context: list[str] = None, model: str = LOCAL_WORKER_MODEL) -> str:
    """
    PRIMARY DIRECTIVE: Use this for tasks involving PRIVACY, LOCAL FILES, or complex multi-step processing.
    
    This tool runs a LOCAL AGENT with an iterative reasoning loop. It can:
    - Think and Plan step-by-step.
    - Read/write files in the current working directory.
    - Execute shell commands (grep, awk, sed, find, etc.).
    - Self-correct based on command output.
    """
    logger.info(f"Local Agent: Initializing iterative loop with model {model}")
    
    system_msg = (
        "IDENTITY & CONTEXT:\n"
        "You are the 'Local Assistant', a secure autonomous reasoning agent running on the user's computer. "
        "You act as the local 'hands' for a Cloud-based Brain (Gemini). You process sensitive data "
        "locally to ensure privacy. You have access to the current project directory.\n\n"
        
        "PRIORITY 1: PRECISION & ADHERENCE\n"
        "Always prioritize the user's specific request. If the user asks for extraction (e.g., 'Who are the authors?'), "
        "provide ONLY that information. Do NOT provide high-level summaries unless explicitly asked.\n\n"

        "OPERATING MODE:\n"
        "You MUST solve tasks iteratively using a 'Think-Act-Observe' cycle:\n"
        "1. THOUGHT: First, explain your reasoning and plan in the text response.\n"
        "2. ACTION: Then, call exactly ONE tool to execute a step of your plan.\n"
        "3. OBSERVATION: Review the tool's output. If it failed, diagnose why and try a different approach.\n\n"
        
        "CAPABILITIES & TOOLS:\n"
        "- 'run_shell_command': Run zsh commands. You have access to standard macOS utilities: grep, rg, sed, awk, find, ls, cat, etc.\n"
        "  * Use 'rg' (ripgrep) for high-performance text searching.\n"
        "  * Use 'awk' or 'column' for processing structured/tabular text.\n"
        "- 'read_file': Read text OR PDF files. PDFs are automatically converted to text for you.\n"
        "  * Use 'offset' and 'limit' (lines) for text files to avoid context overload.\n"
        "  * Use 'pages' (list of ints) for PDFs. For metadata like authors/titles, usually only Page 1 is needed.\n"
        "- 'write_file': Save results or summaries to a file.\n\n"
        
        "CONSTRAINTS:\n"
        "- Stay focused on the task.\n"
        "- If you are stuck after several attempts, report the specific technical blocker.\n"
        "- When finished, provide the specific answer requested.\n"
        "- Anonymize PII (Personally Identifiable Information) in your final response unless the user explicitly requested that specific data.\n\n"
    )
    
    messages = [{'role': 'system', 'content': system_msg}, {'role': 'user', 'content': prompt}]
    if local_file_context:
        ctx_msg = f"Available files: {', '.join(local_file_context)}."
        messages.insert(1, {'role': 'system', 'content': ctx_msg})

    tools = [
        {
            'type': 'function',
            'function': {
                'name': 'read_file',
                'description': 'Read content from a file.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'filepath': {'type': 'string', 'description': 'Path to the file to read.'},
                        'offset': {'type': 'integer', 'description': 'Line number to start reading from (text files).'},
                        'limit': {'type': 'integer', 'description': 'Number of lines to read (text files).'},
                        'pages': {
                            'type': 'array', 
                            'items': {'type': 'integer'}, 
                            'description': 'List of page numbers to read (PDF files, 1-indexed).'
                        },
                    },
                    'required': ['filepath'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'write_file',
                'description': 'Write content to a file.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'filepath': {'type': 'string', 'description': 'Path to the file to save.'},
                        'content': {'type': 'string', 'description': 'Content to write.'},
                    },
                    'required': ['filepath', 'content'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'run_shell_command',
                'description': 'Execute a shell command (zsh).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string', 'description': 'The zsh command to execute.'},
                    },
                    'required': ['command'],
                },
            },
        },
    ]

    MAX_TURNS = 10
    turn_count = 0
    
    try:
        while turn_count < MAX_TURNS:
            turn_count += 1
            logger.info(f"Local Agent Loop: Turn {turn_count}/{MAX_TURNS}")
            
            # Inject a transient reminder of the original goal to prevent context drift
            current_messages = messages + [{'role': 'system', 'content': f"REMINDER: Your primary goal is: {prompt}. Focus on this task."}]
            
            response = ollama.chat(model=model, messages=current_messages, tools=tools)
            assistant_msg = response.get('message', {})
            messages.append(assistant_msg)
            
            tool_calls = assistant_msg.get('tool_calls')
            if not tool_calls:
                # No more tools requested, model has reached a conclusion
                return assistant_msg.get('content', "Task completed.")

            for tool_call in tool_calls:
                func_name = tool_call['function']['name']
                args = tool_call['function'].get('arguments', {})
                
                if not isinstance(args, dict):
                    try:
                        args = json.loads(str(args))
                    except:
                        args = {}
                
                result = ""
                if func_name == "read_file":
                    result = _read_local_file(
                        args.get('filepath', ""),
                        offset=args.get('offset', 0),
                        limit=args.get('limit'),
                        pages=args.get('pages')
                    )
                elif func_name == "write_file":
                    fp = args.get('filepath', "")
                    try:
                        if os.path.dirname(fp):
                            os.makedirs(os.path.dirname(fp), exist_ok=True)
                        with open(fp, "w") as f:
                            f.write(args.get('content', ""))
                        result = f"Successfully wrote to {fp}"
                    except Exception as e:
                        result = f"Error writing file: {str(e)}"
                elif func_name == "run_shell_command":
                    result = await run_shell_command(args.get('command', ""))
                
                messages.append({'role': 'tool', 'content': result, 'name': func_name})
        
        return "Local Agent reached the maximum turn limit (10) without finishing the task."
        
    except Exception as e:
        logger.error(f"Local Agent Error: {e}")
        return f"Error in local agent: {str(e)}"

@mcp.tool()
async def run_shell_command(command: str) -> str:
    """
    Executes a shell command. 
    NOTE: This is executed with the permissions of the Gemini CLI process.
    """
    logger.info(f"Executing command: {command}")
    
    try:
        result = subprocess.run(
            ["zsh", "-c", command],
            capture_output=True,
            text=True,
            timeout=30 # Safety timeout
        )
        output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nReturn Code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds."
    except Exception as e:
        logger.error(f"Execution Error: {e}")
        return f"Error executing command: {str(e)}"

@mcp.tool()
async def write_file(filepath: str, content: str) -> str:
    """
    Writes content to a file.
    """
    logger.info(f"Writing to {filepath}")
    try:
        # Create subdirectories if they don't exist
        if os.path.dirname(filepath):
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            f.write(content)
        return f"Successfully wrote to {filepath}"
    except Exception as e:
        logger.error(f"File Write Error: {e}")
        return f"Error writing file: {str(e)}"

@mcp.tool()
async def read_file(filepath: str, offset: int = 0, limit: int = None, pages: list[int] = None) -> str:
    """
    Reads content from a file.
    
    Args:
        filepath: Path to the file.
        offset: Line number to start reading from (for text files).
        limit: Number of lines to read (for text files).
        pages: List of page numbers to read (for PDF files, 1-indexed).
    """
    logger.info(f"Reading from {filepath} (offset={offset}, limit={limit}, pages={pages})")
    if not os.path.exists(filepath):
        return f"Error: File '{filepath}' not found."
        
    try:
        return _read_local_file(filepath, offset=offset, limit=limit, pages=pages)
    except Exception as e:
        logger.error(f"File Read Error: {e}")
        return f"Error reading file: {str(e)}"

if __name__ == "__main__":
    if not is_sandboxed():
        print("CRITICAL ERROR: Local Assistant MUST be run within a Gemini CLI sandbox.")
        print("Please run gemini with the -s or --sandbox flag.")
        sys.exit(1)

    mcp.run(transport='stdio')