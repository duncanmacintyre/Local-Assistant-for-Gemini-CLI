import os
import json
import logging
import asyncio
import signal
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
PLAN_FILE = ".gemini/local_plan.md"

# Global set to track active subprocesses for cleanup on cancellation/exit
active_subprocesses = set()

def is_sandboxed() -> bool:
    """Checks if the process is running within a macOS sandbox (seatbelt)."""
    try:
        # libsandbox is available on macOS
        libsandbox = ctypes.CDLL("/usr/lib/libsandbox.1.dylib")
        # sandbox_check(pid, entity, flags) returns 1 if sandboxed
        return libsandbox.sandbox_check(os.getpid(), None, 0) == 1
    except Exception:
        return False

def cleanup_resources():
    """Cleanup active subprocesses and plan files on exit or cancellation."""
    if os.path.exists(PLAN_FILE):
        try:
            os.remove(PLAN_FILE)
            logger.info(f"Cleaned up {PLAN_FILE}")
        except Exception as e:
            logger.error(f"Error cleaning up plan file: {e}")
            
    for p in list(active_subprocesses):
        try:
            if p.returncode is None:
                p.terminate()
                logger.info(f"Terminated background process {p.pid}")
        except Exception as e:
            logger.error(f"Error terminating process: {e}")
    active_subprocesses.clear()

def signal_handler(sig, frame):
    """Handle termination signals."""
    logger.info(f"Received signal {sig}, cleaning up...")
    cleanup_resources()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def _read_local_file(filepath: str, offset: int = 0, limit: int = None, pages: list[int] = None, tail: int = None) -> tuple[str, int, str]:
    """
    Helper to read text or PDF files locally.
    Returns: (content_string, total_units, unit_name)
    """
    if not os.path.exists(filepath):
        return f"[Error: File {filepath} not found]", 0, "unknown"

    if filepath.lower().endswith(".pdf"):
        try:
            reader = PdfReader(filepath)
            total_pages = len(reader.pages)
            text = ""
            
            # If tail is specified for PDF, get the last N pages
            if tail:
                target_pages = range(max(1, total_pages - tail + 1), total_pages + 1)
            else:
                target_pages = pages if pages else range(1, total_pages + 1)
            
            for p_num in target_pages:
                if 1 <= p_num <= total_pages:
                    if total_pages > 1:
                        text += f"--- Page {p_num} ---\n"
                    text += reader.pages[p_num - 1].extract_text() + "\n"
            return text, total_pages, "pages"
        except Exception as e:
            return f"[Error reading PDF {filepath}: {str(e)}]", 0, "pages"
    else:
        try:
            # Efficient buffered line count
            total_lines = 0
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    total_lines += chunk.count(b'\n')
            
            # If the file doesn't end in a newline but has content, it's still a line
            if total_lines == 0 and os.path.getsize(filepath) > 0:
                total_lines = 1

            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                if tail:
                    # For tail, we calculate the offset
                    start_line = max(0, total_lines - tail)
                    gen = islice(f, start_line, None)
                else:
                    stop = (offset + limit) if limit else None
                    gen = islice(f, offset, stop)
                return "".join(gen), total_lines, "lines"
        except Exception as e:
            return f"[Error reading file {filepath}: {str(e)}]", 0, "lines"

@mcp.tool()
async def get_model_info(model: str = LOCAL_WORKER_MODEL) -> str:
    """
    Retrieves detailed metadata for a specific Ollama model, including its native context limit.
    """
    try:
        client = ollama.AsyncClient(host=OLLAMA_BASE_URL)
        info = await client.show(model)
        model_info = info.get('modelinfo', {})
        
        # Look for context length in common architecture-specific keys
        ctx_len = None
        for key in model_info:
            if 'context_length' in key:
                ctx_len = model_info[key]
                break
        
        details = {
            "model": model,
            "context_length": ctx_len or "unknown (defaulting to 32k)",
            "parameter_size": info.get('details', {}).get('parameter_size', 'unknown'),
            "quantization": info.get('details', {}).get('quantization_level', 'unknown'),
            "architecture": model_info.get('general.architecture', 'unknown')
        }
        return json.dumps(details, indent=2)
    except Exception as e:
        logger.error(f"Error fetching model info for {model}: {e}")
        return f"Error: Could not retrieve info for model '{model}'."

@mcp.tool()
async def list_local_models() -> str:
    """
    Lists the available local Ollama models that can be used with ask_local_assistant.
    """
    try:
        client = ollama.AsyncClient(host=OLLAMA_BASE_URL)
        models_info = await client.list()
        models = []
        if hasattr(models_info, 'models'):
            models = [m.model for m in models_info.models]
        elif isinstance(models_info, dict) and 'models' in models_info:
            models = [m.get('name') or m.get('model') for m in models_info['models']]
            
        if not models:
            return "No local models found in Ollama."
        return "Available local models:\n- " + "\n- ".join(models)
    except Exception as e:
        logger.error(f"Error listing Ollama models: {e}")
        return f"Error listing models: {str(e)}"

@mcp.tool()
async def complete_plan_step(step_index: int) -> str:
    """
    Marks a specific step in the local execution plan as completed.
    
    Args:
        step_index: The 1-based index of the step to mark as complete (e.g., 1 for the first step).
    """
    if not os.path.exists(PLAN_FILE):
        return f"Error: Plan file {PLAN_FILE} not found. Are you in Planning Mode?"
        
    try:
        with open(PLAN_FILE, "r") as f:
            lines = f.readlines()
            
        count = 0
        updated = False
        for i, line in enumerate(lines):
            # Matches "- [ ]" or "- [x]"
            if "- [" in line and ("] " in line):
                count += 1
                if count == step_index:
                    if "- [ ]" in line:
                        lines[i] = line.replace("- [ ]", "- [x]")
                        updated = True
                    else:
                        return f"Step {step_index} is already marked as complete."
                    break
        
        if not updated:
            return f"Error: Could not find step {step_index} in the plan."
            
        with open(PLAN_FILE, "w") as f:
            f.writelines(lines)
            
        return f"Successfully marked step {step_index} as complete in {PLAN_FILE}."
    except Exception as e:
        logger.error(f"Error updating plan: {e}")
        return f"Error updating plan: {str(e)}"

@mcp.tool()
async def ask_local_assistant(prompt: str, local_file_context: list[str] = None, model: str = LOCAL_WORKER_MODEL, use_plan: bool = False, num_ctx: int = 32768, max_turns: int = None) -> str:
    """
    PRIMARY DIRECTIVE: Use this for tasks involving PRIVACY, LOCAL FILES, or complex multi-step processing.
    
    Args:
        prompt: The task description.
        local_file_context: Optional list of files to provide as context.
        model: The local model to use (default: qwen3-coder:30b).
        use_plan: IMPORTANT: Set to True if the task is complex, requires multiple steps (e.g. refactoring, debugging), or modifies files.
                  When True, the agent will create a plan and execute it step-by-step. The final response will include a detailed execution checklist for verification.
                  Default is False (for simple queries).
        num_ctx: The context window size in tokens (default: 32768). 
                  - Use 8192-16384 for simple single-file tasks.
                  - Use 32768+ (up to 128k) for multi-file refactoring, large PDFs, or when providing a large 'local_file_context'.
                  - Note: High values increase RAM/VRAM usage on your local machine.
        max_turns: Optional override for the maximum number of Think-Act-Observe cycles.
                  - ADVICE FOR GEMINI CLI: 
                    * DEFAULT: 20 turns (Direct), 40 turns (Planning).
                    * WHEN TO INCREASE: For massive refactorings, complex bug hunts, or tasks spanning 10+ files.
                    * WHEN TO DECREASE: For simple data extraction or single-file analysis to save time and tokens.
                    * WHY: Complex tasks with many dependencies often require more iterative turns to verify and correct intermediate steps.
                    * NOTE: Planning mode requires at least 30 turns to account for setup and plan updates.
    """
    logger.info(f"Local Agent: Initializing iterative loop with model {model} (Planning Mode: {use_plan}, Context Window: {num_ctx}, Max Turns: {max_turns})")
    
    # Set default turn limits
    if use_plan:
        if max_turns is not None and max_turns < 30:
            return f"Warning: Planning mode requires at least 30 turns for reliable execution. You specified {max_turns}. Please increase 'max_turns' or use Direct Execution mode."
        MAX_TURNS = max_turns if max_turns is not None else 40
    else:
        MAX_TURNS = max_turns if max_turns is not None else 20

    # Discovery Phase: Get model context limit
    try:
        raw_info = await get_model_info(model)
        model_meta = json.loads(raw_info)
        native_ctx = model_meta.get('context_length')
        model_ctx_msg = f"LOCAL MODEL CAPABILITIES: Model '{model}' reports a native context limit of {native_ctx} tokens.\n"
    except Exception:
        model_ctx_msg = ""

    # Define available tools
    tools = [
        {
            'type': 'function',
            'function': {
                'name': 'read_file',
                'description': 'Read content from one or more files.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'filepaths': {
                            'type': 'array', 
                            'items': {'type': 'string'}, 
                            'description': 'List of paths to the files to read.'
                        },
                        'offset': {'type': 'integer', 'description': 'Line number to start reading from (text files).'},
                        'limit': {'type': 'integer', 'description': 'Number of lines to read (text files).'},
                        'tail': {'type': 'integer', 'description': 'Number of lines/pages to read from the END of the file.'},
                        'pages': {
                            'type': 'array', 
                            'items': {'type': 'integer'}, 
                            'description': 'List of page numbers to read (PDF files, 1-indexed).'
                        },
                    },
                    'required': ['filepaths'],
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
                'name': 'complete_plan_step',
                'description': 'Mark a step in the execution plan as completed.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'step_index': {'type': 'integer', 'description': 'The 1-based index of the step to mark as complete.'},
                    },
                    'required': ['step_index'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'run_shell_command',
                'description': 'Execute one or more shell commands (zsh).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string', 'description': 'A single zsh command to execute.'},
                        'commands': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'A list of zsh commands to execute sequentially.'
                        },
                    },
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'request_clarification',
                'description': 'Ask the user for missing information or to resolve an ambiguity.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'question': {'type': 'string', 'description': 'The question to ask the user.'},
                    },
                    'required': ['question'],
                },
            },
        },
    ]

    async def execute_tool(func_name, args):
        # A conservative estimation: 3.5 characters per token. 
        # num_ctx is in tokens.
        safe_char_limit = int(num_ctx * 0.25 * 3.5)
        # Cap at a reasonable maximum to prevent massive strings being returned even if num_ctx is huge
        absolute_max_chars = 64000
        char_limit = min(safe_char_limit, absolute_max_chars)

        def truncate_with_meta(text, unit_name, total_units):
            if len(text) > char_limit:
                truncated = text[:char_limit]
                footer = (
                    f"\n\n[WARNING: Output truncated due to context limits ({len(text)} chars > {char_limit} limit). "
                    f"This file has {total_units} {unit_name} total. "
                    f"Use 'offset'/'limit' or 'pages' to read the next segment.]"
                )
                return truncated + footer
            return text

        if func_name == "read_file":
            fps = args.get('filepaths')
            if not fps:
                fps = [args.get('filepath', "")]
            
            results = []
            for fp in fps:
                res, total, unit = _read_local_file(
                    fp,
                    offset=args.get('offset', 0),
                    limit=args.get('limit'),
                    pages=args.get('pages'),
                    tail=args.get('tail')
                )
                res = truncate_with_meta(res, unit, total)
                # Wrap each file's output with a header including total units
                results.append(f"--- FILE: {fp} ({total} {unit} total) ---\n{res}\n")
            return "\n".join(results)

        elif func_name == "write_file":
            fp = args.get('filepath', "")
            try:
                if os.path.dirname(fp):
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w") as f:
                    f.write(args.get('content', ""))
                return f"Successfully wrote to {fp}"
            except Exception as e:
                return f"Error writing file: {str(e)}"
        elif func_name == "complete_plan_step":
            return await complete_plan_step(args.get('step_index', 0))
        elif func_name == "run_shell_command":
            cmds = args.get('commands')
            if not cmds:
                cmds = [args.get('command', "")]
            
            results = []
            for cmd in cmds:
                if not cmd: continue
                res = await run_shell_command(cmd)
                # Count lines for metadata in shell command context
                total_lines = res.count('\n') + 1
                res = truncate_with_meta(res, "lines", total_lines)
                if len(cmds) > 1:
                    results.append(f"--- COMMAND: {cmd} ---\n{res}\n")
                else:
                    results.append(res)
            return "\n".join(results)
        elif func_name == "request_clarification":
            return f"CLARIFICATION_REQUIRED: {args.get('question', 'What do you need?')}"
        return f"Unknown tool: {func_name}"

    client = ollama.AsyncClient(host=OLLAMA_BASE_URL)

    try:
        # --- PHASE 1: FORCED PLANNING (If enabled) ---
        if use_plan:
            logger.info("Local Agent: Entering Planning Phase...")
            
            # 1. Clear old plan
            if os.path.exists(PLAN_FILE):
                os.remove(PLAN_FILE)
                
            # 2. Planning Loop
            plan_system_msg = (
                "You are a Senior Technical Planner. Your goal is to create a detailed, step-by-step implementation plan "
                "for the user's request. To create a grounded and accurate plan, you should first explore the project "
                "using 'run_shell_command' (e.g., 'ls -R', 'grep') and 'read_file'.\n\n"
                f"Once you understand the context, you MUST call the 'write_file' tool to save your plan to the EXACT path: '{PLAN_FILE}'.\n"
                "Format your plan as a Markdown checklist:\n"
                "- [ ] Step 1: <Description>\n"
                "- [ ] Step 2: <Description>\n\n"
                "Do NOT execute implementation steps yet. Only use discovery tools to inform your plan. "
                "After writing the plan file, stop."
            )
            
            plan_messages = [{'role': 'system', 'content': plan_system_msg}, {'role': 'user', 'content': prompt}]
            
            plan_created = False
            attempted_paths = []
            planning_tools = [t for t in tools if t['function']['name'] in ['write_file', 'read_file', 'run_shell_command', 'request_clarification']]

            for i in range(10): # Max 10 turns to explore + write a plan
                logger.info(f"Planning Turn {i+1}/10")
                response = await client.chat(
                    model=model, 
                    messages=plan_messages, 
                    tools=planning_tools,
                    options={'num_ctx': num_ctx}
                )
                msg = response.get('message', {})
                logger.info(f"Planning Response: {msg}")
                plan_messages.append(msg)
                
                tool_calls = msg.get('tool_calls')
                if not tool_calls:
                    if plan_created:
                        break
                    else:
                        plan_messages.append({'role': 'system', 'content': f"You must write the plan to '{PLAN_FILE}' using 'write_file' before finishing."})
                        continue

                for tc in tool_calls:
                    func_name = tc['function']['name']
                    args = json.loads(tc['function']['arguments']) if isinstance(tc['function']['arguments'], str) else tc['function']['arguments']
                    
                    result = await execute_tool(func_name, args)
                    plan_messages.append({'role': 'tool', 'content': result, 'name': func_name})
                    
                    if result.startswith("CLARIFICATION_REQUIRED:"):
                        return result

                    if func_name == "write_file":
                        fp = args.get('filepath', "")
                        attempted_paths.append(fp)
                        if fp.endswith("local_plan.md"):
                            plan_created = True
                
                if plan_created and not any(tc['function']['name'] != 'write_file' for tc in tool_calls):
                    # If we just wrote the plan and didn't do anything else, we might be done
                    pass 

            if not plan_created:
                return f"Error: Agent failed to generate a plan file ({PLAN_FILE}) in Planning Mode. Attempted paths: {attempted_paths}"
            
            logger.info("Local Agent: Plan created. Entering Execution Phase.")

        # --- PHASE 2: EXECUTION LOOP (Main) ---
        
        base_system_msg = (
            "IDENTITY & CONTEXT:\n"
            "You are the 'Local Assistant', a secure autonomous reasoning agent running on the user's computer. "
            "You act as the local 'hands' for a Cloud-based Brain (Gemini). You process sensitive data "
            "locally to ensure privacy. You have access to the current project directory.\n\n"
            
            f"{model_ctx_msg}"
            "PRIORITY 1: PRECISION & ADHERENCE\n"
            "Always prioritize the user's specific request. If the user asks for extraction (e.g., 'Who are the authors?'), "
            "provide ONLY that information. Do NOT provide high-level summaries unless explicitly asked.\n\n"

            "CAPABILITIES & TOOLS:\n"
            "- 'run_shell_command': Run one or more zsh commands. Use standard macOS utilities: grep, rg, find, ls, sed, awk, cat, column, etc.\n"
            "  * You can pass a list of 'commands' to execute multiple operations in a single turn.\n"
            "  * EFFICIENT FILTERING: Use 'grep', 'sed', 'awk', or 'column' to extract only the necessary data locally. This is faster and prevents hitting the Context Guard's truncation limits.\n"
            "- 'read_file': Read text OR PDF files. \n"
            "  * You can pass a list of 'filepaths' to read multiple files at once.\n"
            "  * Use 'offset' and 'limit' (lines) for text files to avoid context overload.\n"
            "  * Use 'tail' (int) to read the last N lines/pages. This is great for logs or the end of documents.\n"
            "  * Use 'pages' (list of ints) for PDFs. For metadata, usually only Page 1 is needed.\n"
            "  * WARNING: Large outputs will be automatically truncated. Use segmentation to read long files.\n"
            "- 'write_file': Save results or summaries to a file.\n"
            "- 'get_model_info': Inspect local model details (context limit, etc.) if needed.\n"
            "- 'request_clarification': If you are stuck because the user's request is ambiguous or missing info, "
            "use this to ask the user a specific question. This will pause your execution.\n\n"
            
            "CONSTRAINTS:\n"
            "- Stay focused on the task.\n"
            "- If you are stuck after several attempts, report the specific technical blocker.\n"
            "- When finished, provide the specific answer requested.\n"
            "- Anonymize PII (Personally Identifiable Information) in your final response unless the user explicitly requested that specific data.\n\n"
        )

        if use_plan:
            execution_instructions = (
                "OPERATING MODE: PLAN EXECUTION\n"
                "You are executing a pre-defined plan. The current plan status will be provided to you every turn.\n"
                "YOUR JOB:\n"
                "1. Review the 'CURRENT PLAN STATE'.\n"
                "2. Execute the next unchecked step ([ ]).\n"
                "3. VERY IMPORTANT: After finishing the work for a step, you MUST call 'complete_plan_step' to mark it as [x].\n"
                "   - You MUST pass the 1-based index of the step you just completed.\n"
                "   - Do NOT try to edit the plan file manually using 'write_file'. Use 'complete_plan_step'.\n"
                "4. Do not deviate from the plan."
            )
            system_msg = base_system_msg + execution_instructions
        else:
            system_msg = base_system_msg + (
                "OPERATING MODE: DIRECT EXECUTION\n"
                "You MUST solve tasks iteratively using a 'Think-Act-Observe' cycle:\n"
                "1. THOUGHT: First, explain your reasoning and plan in the text response.\n"
                "2. ACTION: Then, call exactly ONE tool to execute a step of your plan.\n"
                "3. OBSERVATION: Review the tool's output. If it failed, diagnose why and try a different approach.\n\n"
            )
        
        messages = [{'role': 'system', 'content': system_msg}, {'role': 'user', 'content': prompt}]
        if local_file_context:
            ctx_msg = f"Available files: {', '.join(local_file_context)}."
            messages.insert(1, {'role': 'system', 'content': ctx_msg})

        turn_count = 0
        has_reflected = False
        plan_nudge_count = 0
        last_tool_was_work = False
        
        while turn_count < MAX_TURNS:
            turn_count += 1
            remaining = MAX_TURNS - turn_count
            logger.info(f"Local Agent Loop: Turn {turn_count}/{MAX_TURNS}")
            
            # --- CONTEXT INJECTION (The "Python-Led" Logic) ---
            loop_system_msg = f"REMINDER: {prompt}\n"
            loop_system_msg += f"PROGRESS: Turn {turn_count}/{MAX_TURNS} ({remaining} remaining).\n"
            
            if use_plan and os.path.exists(PLAN_FILE):
                try:
                    with open(PLAN_FILE, 'r') as f:
                        plan_content = f.read()
                    loop_system_msg += f"\n=== CURRENT PLAN STATE ({PLAN_FILE}) ===\n{plan_content}\n===============================\n"
                    
                    if last_tool_was_work:
                        loop_system_msg += "The previous action appeared successful. If a plan step is now complete, you should update the plan using 'complete_plan_step' before proceeding.\n"
                    else:
                        loop_system_msg += "INSTRUCTION: Execute the next [ ] step. Then call 'complete_plan_step' with the correct index to mark it [x].\n"

                    # Detect if plan is fully complete to nudge finishing
                    if "- [ ]" not in plan_content and "- [x]" in plan_content:
                        loop_system_msg += "Plan appears complete. You can now provide your final response.\n"
                except Exception as e:
                    loop_system_msg += f"\n[Warning: Could not read plan file: {e}]\n"
            else:
                loop_system_msg += " Focus on this task.\n"
            
            current_messages = messages + [{'role': 'system', 'content': loop_system_msg}]
            
            response = await client.chat(
                model=model, 
                messages=current_messages, 
                tools=tools,
                options={'num_ctx': num_ctx}
            )
            assistant_msg = response.get('message', {})
            messages.append(assistant_msg)
            
            tool_calls = assistant_msg.get('tool_calls')
            if not tool_calls:
                # --- REFLECTION STEP ---
                if not has_reflected:
                    logger.info("Local Agent: Performing self-reflection check...")
                    
                    reflection_prompt = (
                        f"Self-Correction Check: Review your work. Did you fully answer the user's request: '{prompt}'? "
                        "If you need to do more work (e.g. read more files, run more commands), answer 'incomplete'. "
                        "Respond ONLY in JSON format: {\"status\": \"complete\"} OR {\"status\": \"incomplete\", \"reason\": \"<what is missing>\"}."
                    )
                    
                    # Create a temporary message history for the reflection (don't pollute the main history yet)
                    reflection_messages = messages + [{'role': 'system', 'content': reflection_prompt}]
                    
                    try:
                        # Force JSON mode for the reflection
                        ref_response = await client.chat(
                            model=model, 
                            messages=reflection_messages, 
                            format='json',
                            options={'num_ctx': num_ctx}
                        )
                        ref_content = ref_response.get('message', {}).get('content', '{}')
                        ref_data = json.loads(ref_content)
                        
                        if ref_data.get('status') == 'incomplete':
                            reason = ref_data.get('reason', 'No reason provided')
                            logger.info(f"Local Agent Reflection: Incomplete ({reason}). Extending turns.")
                            
                            has_reflected = True
                            MAX_TURNS += 5
                            
                            # Inject the realization back into the main history so the agent acts on it
                            messages.append({
                                'role': 'system', 
                                'content': f"SELF-CORRECTION: You acknowledged the task is incomplete because: '{reason}'. "
                                           f"You have been granted 5 extra turns. Please continue working to resolve this."
                            })
                            continue # Resume the loop to allow more tool calls
                            
                        else:
                            logger.info("Local Agent Reflection: Task complete.")
                            has_reflected = True
                            
                    except Exception as e:
                        logger.warning(f"Reflection failed (parsing error or model limitation): {e}. Assuming complete.")
                
                # --- PLAN VALIDATION NUDGE ---
                if use_plan and os.path.exists(PLAN_FILE):
                    try:
                        with open(PLAN_FILE, 'r') as f:
                            plan_content = f.read()
                        if "- [ ]" in plan_content and plan_nudge_count < 2:
                            plan_nudge_count += 1
                            logger.info(f"Local Agent: Intercepting finish. {plan_content.count('- [ ]')} steps still unchecked. Nudging...")
                            messages.append({
                                'role': 'system', 
                                'content': "You have attempted to finish, but some steps in the plan are still marked as incomplete [ ]. "
                                           "If these steps are finished, please update the plan using 'complete_plan_step'. "
                                           "If they are not needed or you have a reason to skip them, please explain. "
                                           "Otherwise, continue with the remaining work."
                            })
                            continue # Re-run the loop for another turn
                    except Exception as e:
                        logger.warning(f"Plan validation failed: {e}")

                # No more tools requested and reflection/plan checks passed
                final_response = assistant_msg.get('content', "Task completed.")
                
                if use_plan and os.path.exists(PLAN_FILE):
                    try:
                        with open(PLAN_FILE, 'r') as f:
                            plan_content = f.read()
                        
                        # Check if plan was actually updated (basic check for [x])
                        if "- [x]" not in plan_content and "- [ ]" in plan_content:
                             final_response += "\n\n[Warning: Agent executed actions but failed to update the plan checklist.]"
                        
                        final_response += f"\n\n--- EXECUTION PLAN ---\n{plan_content}\n----------------------"
                        
                        # Cleanup
                        if os.path.exists(PLAN_FILE):
                            os.remove(PLAN_FILE)
                        # Try to remove the directory if empty
                        try:
                            os.rmdir(os.path.dirname(PLAN_FILE))
                        except (OSError, FileNotFoundError):
                            pass # Directory not empty or already gone
                            
                    except Exception as e:
                        logger.warning(f"Could not read/cleanup plan file: {e}")
                
                return final_response

            for tool_call in tool_calls:
                func_name = tool_call['function']['name']
                args = tool_call['function'].get('arguments', {})
                
                # Track if this turn involved actual work vs just bureaucracy
                if func_name in ["run_shell_command", "write_file"]:
                    last_tool_was_work = True
                else:
                    last_tool_was_work = False
                
                if not isinstance(args, dict):
                    try:
                        args = json.loads(str(args))
                    except:
                        args = {}
                
                result = await execute_tool(func_name, args)
                messages.append({'role': 'tool', 'content': result, 'name': func_name})

                # --- CLARIFICATION BREAK ---
                if result.startswith("CLARIFICATION_REQUIRED:"):
                    return result
        
        return f"Local Agent reached the maximum turn limit ({MAX_TURNS}) without finishing the task."

    except asyncio.CancelledError:
        logger.info("ask_local_assistant was cancelled. Cleaning up...")
        cleanup_resources()
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Local Agent Error: {e}\n{error_trace}")
        return f"Error in local agent: {str(e)}"
    finally:
        cleanup_resources()

@mcp.tool()
async def run_shell_command(command: str) -> str:
    """
    Executes a shell command. 
    NOTE: This is executed with the permissions of the Gemini CLI process.
    """
    logger.info(f"Executing command: {command}")
    
    try:
        # Create subprocess in the current event loop
        process = await asyncio.create_subprocess_exec(
            "zsh", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        active_subprocesses.add(process)
        
        try:
            # Use asyncio.wait_for for timeout
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            output = f"STDOUT:\n{stdout.decode()}\nSTDERR:\n{stderr.decode()}"
            if process.returncode != 0:
                output += f"\nReturn Code: {process.returncode}"
            return output
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()
            return "Error: Command timed out after 30 seconds."
        finally:
            active_subprocesses.discard(process)
            
    except asyncio.CancelledError:
        logger.info(f"Shell command cancelled: {command}")
        # Terminate process if cancelled
        for p in list(active_subprocesses):
            if p.returncode is None:
                p.terminate()
        raise
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