import os
import pytest
import subprocess
import ctypes
import json
from unittest.mock import MagicMock, patch
import mcp_server

# --- Sandbox Detection Tests ---

def test_is_sandboxed_true():
    """Test is_sandboxed returns True when sandbox_check returns 1."""
    with patch("ctypes.CDLL") as mock_cdll:
        mock_libsandbox = MagicMock()
        mock_libsandbox.sandbox_check.return_value = 1
        mock_cdll.return_value = mock_libsandbox
        
        from mcp_server import is_sandboxed
        assert is_sandboxed() is True

def test_is_sandboxed_false():
    """Test is_sandboxed returns False when sandbox_check returns 0."""
    with patch("ctypes.CDLL") as mock_cdll:
        mock_libsandbox = MagicMock()
        mock_libsandbox.sandbox_check.return_value = 0
        mock_cdll.return_value = mock_libsandbox
        
        from mcp_server import is_sandboxed
        assert is_sandboxed() is False

def test_is_sandboxed_exception():
    """Test is_sandboxed returns False when an exception occurs."""
    with patch("ctypes.CDLL", side_effect=Exception("Not macOS")):
        from mcp_server import is_sandboxed
        assert is_sandboxed() is False

# --- File Reading Tests ---

def test_read_local_file_text(tmp_path):
    """Test reading a standard text file."""
    test_file = tmp_path / "hello.txt"
    test_file.write_text("hello world", encoding="utf-8")
    
    from mcp_server import _read_local_file as read_fn
    assert read_fn(str(test_file)) == "hello world"

@patch("mcp_server.PdfReader")
def test_read_local_file_pdf(mock_pdf_reader, tmp_path):
    """Test reading a PDF file (mocked)."""
    test_pdf = tmp_path / "test.pdf"
    test_pdf.write_text("pdf-like-content")
    
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "extracted pdf text"
    mock_pdf_reader.return_value.pages = [mock_page]
    
    from mcp_server import _read_local_file as read_fn
    assert "extracted pdf text" in read_fn(str(test_pdf))

def test_read_local_file_not_found():
    """Verify error message for non-existent files."""
    from mcp_server import _read_local_file as read_fn
    result = read_fn("missing_file_xyz.txt")
    assert "not found" in result

@patch("mcp_server.PdfReader")
def test_read_local_file_pdf_corrupt(mock_pdf_reader, tmp_path):
    """Verify handling of corrupted PDF files."""
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_text("not-a-pdf")
    mock_pdf_reader.side_effect = Exception("Invalid PDF format")
    
    from mcp_server import _read_local_file as read_fn
    result = read_fn(str(bad_pdf))
    assert "Error reading PDF" in result

# --- Tool Execution Tests ---

@pytest.mark.asyncio
async def test_write_file(tmp_path):
    """Test the write_file tool."""
    from mcp_server import write_file
    target = tmp_path / "new.txt"
    result = await write_file(str(target), "content")
    assert "Successfully wrote" in result
    assert target.read_text() == "content"

@pytest.mark.asyncio
async def test_run_shell_command_success():
    """Test the shell command runner."""
    from mcp_server import run_shell_command
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "ls output"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        
        result = await run_shell_command("ls")
        assert "ls output" in result
        args = mock_run.call_args[0][0]
        assert args == ["zsh", "-c", "ls"]

@pytest.mark.asyncio
async def test_run_shell_command_error():
    """Test that non-zero exit codes are handled and reported."""
    from mcp_server import run_shell_command
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "permission denied"
        mock_run.return_value.returncode = 1
        
        result = await run_shell_command("invalid_cmd")
        assert "Return Code: 1" in result
        assert "permission denied" in result

# --- Agent Loop Logic (Mocked Ollama) ---

@pytest.mark.asyncio
@patch("ollama.chat")
async def test_ask_local_assistant_no_tool(mock_chat):
    """Test assistant when no tool call is needed."""
    from mcp_server import ask_local_assistant
    mock_chat.return_value = {
        'message': {'role': 'assistant', 'content': 'direct answer'}
    }
    
    result = await ask_local_assistant("What is 2+2?")
    assert result == "direct answer"

@pytest.mark.asyncio
@patch("ollama.chat")
async def test_ask_local_assistant_multiple_turns(mock_chat, tmp_path):
    """Test assistant when it calls tools iteratively over multiple turns."""
    from mcp_server import ask_local_assistant
    
    test_file = tmp_path / "a.txt"
    test_file.write_text("source")
    
    mock_chat.side_effect = [
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{'function': {'name': 'log_thought', 'arguments': {'thought': 'Planning'}}}]
            }
        },
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{'function': {'name': 'read_file', 'arguments': {'filepath': str(test_file)}}}]
            }
        },
        {'message': {'role': 'assistant', 'content': 'Done!'}}
    ]
    
    result = await ask_local_assistant("Analyze a.txt")
    
    assert result == "Done!"
    assert mock_chat.call_count == 3

@pytest.mark.asyncio
@patch("ollama.chat")
async def test_ask_local_assistant_turn_limit(mock_chat):
    """Verify that the agent stops and returns a message when the turn limit is reached."""
    from mcp_server import ask_local_assistant
    mock_chat.return_value = {
        'message': {
            'role': 'assistant',
            'tool_calls': [{'function': {'name': 'log_thought', 'arguments': {'thought': 'Looping'}}}]
        }
    }
    
    result = await ask_local_assistant("Do something")
    assert "maximum turn limit" in result
    assert mock_chat.call_count == 10

@pytest.mark.asyncio
@patch("ollama.chat")
async def test_ask_local_assistant_agent_read_missing(mock_chat):
    """Verify that if the agent tries to read a missing file, it receives an error result."""
    from mcp_server import ask_local_assistant
    
    mock_chat.side_effect = [
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{'function': {'name': 'read_file', 'arguments': {'filepath': 'gone.txt'}}}]
            }
        },
        {'message': {'content': 'The file is gone.'}}
    ]
    
    await ask_local_assistant("Read gone.txt")
    
    final_history = mock_chat.call_args_list[1][1]['messages']
    tool_msg = next(m for m in final_history if m['role'] == 'tool')
    assert "not found" in tool_msg['content']

# --- Model & Ollama Tool Tests ---

@pytest.mark.asyncio
@patch("ollama.list")
async def test_list_local_models(mock_list):
    """Test listing available Ollama models."""
    from mcp_server import list_local_models
    mock_list.return_value = {
        'models': [
            {'name': 'mistral-nemo:latest'},
            {'name': 'llama3:8b'}
        ]
    }
    
    result = await list_local_models()
    assert "Available local models:" in result
    assert "mistral-nemo:latest" in result
    assert "llama3:8b" in result

@pytest.mark.asyncio
@patch("ollama.list")
async def test_list_local_models_empty(mock_list):
    """Test listing models when none are installed."""
    from mcp_server import list_local_models
    mock_list.return_value = {'models': []}
    result = await list_local_models()
    assert "No local models found" in result

@pytest.mark.asyncio
@patch("ollama.list")
async def test_list_local_models_error(mock_list):
    """Test list_local_models error handling."""
    from mcp_server import list_local_models
    mock_list.side_effect = Exception("Ollama connection failed")
    result = await list_local_models()
    assert "Error listing models" in result

@pytest.mark.asyncio
@patch("ollama.chat")
async def test_ask_local_assistant_custom_model(mock_chat):
    """Test assistant using a specific model."""
    from mcp_server import ask_local_assistant
    mock_chat.return_value = {'message': {'content': 'using custom model'}}
    await ask_local_assistant("Hello", model="llama3")
    kwargs = mock_chat.call_args[1]
    assert kwargs['model'] == "llama3"