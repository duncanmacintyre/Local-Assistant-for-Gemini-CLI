import pytest
import json
import os
from unittest.mock import MagicMock, patch
from mcp_server import get_model_info, ask_local_assistant, _read_local_file

@pytest.mark.asyncio
@patch("mcp_server.ollama.show")
async def test_get_model_info_qwen(mock_show):
    """Verify that get_model_info correctly extracts qwen-specific context limit."""
    mock_show.return_value = {
        "modelinfo": {
            "general.architecture": "qwen3",
            "qwen3.context_length": 131072,
            "qwen3.parameter_size": "30B"
        },
        "details": {
            "parameter_size": "30B",
            "quantization_level": "Q4_K_M"
        }
    }
    
    result = await get_model_info("qwen3-coder:30b")
    data = json.loads(result)
    
    assert data["context_length"] == 131072
    assert data["architecture"] == "qwen3"
    assert data["parameter_size"] == "30B"

@pytest.mark.asyncio
@patch("ollama.chat")
@patch("mcp_server.get_model_info")
async def test_batch_read_file(mock_get_info, mock_chat, tmp_path):
    """Test reading multiple files in a single tool call."""
    mock_get_info.return_value = json.dumps({"context_length": 32768})

    # Create two test files
    f1 = tmp_path / "a.txt"
    f1.write_text("content A")
    f2 = tmp_path / "b.txt"
    f2.write_text("content B")

    mock_chat.side_effect = [
        # Turn 1: Assistant calls batch read_file
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{
                    'function': {
                        'name': 'read_file',
                        'arguments': json.dumps({'filepaths': [str(f1), str(f2)]})
                    }
                }]
            }
        },
        # Turn 2: Final response
        {'message': {'role': 'assistant', 'content': 'I read both.'}},
        # Turn 2: Reflection
        {'message': {'role': 'assistant', 'content': '{"status": "complete"}'}}
    ]

    # We mock os.path.exists for the files
    with patch("os.path.exists", return_value=True):
        result = await ask_local_assistant("Read a and b")

    # In ask_local_assistant, tool results are appended to the 'messages' list.
    # The history sent in Turn 2 should contain the result of Turn 1.
    history_sent_to_turn_2 = mock_chat.call_args_list[1][1]['messages']

    # The last message in history_sent_to_turn_2 (excluding the turn-specific system prompt)
    # should be the tool response.
    # Actually, current_messages = messages + [{'role': 'system', 'content': loop_system_msg}]
    # So the tool result is at history_sent_to_turn_2[-2] (before the loop system msg)
    tool_result_msg = history_sent_to_turn_2[-2]
    assert tool_result_msg['role'] == 'tool'
    assert f"--- FILE: {f1} (1 lines total) ---" in tool_result_msg['content']
    assert "content A" in tool_result_msg['content']
    assert f"--- FILE: {f2} (1 lines total) ---" in tool_result_msg['content']
    assert "content B" in tool_result_msg['content']

@pytest.mark.asyncio
@patch("ollama.chat")
@patch("mcp_server.get_model_info")
async def test_context_guard_truncation(mock_get_info, mock_chat, tmp_path):
    """Test that large outputs are truncated by the Context Guard."""
    # Set a small num_ctx to trigger truncation easily
    num_ctx = 1000
    mock_get_info.return_value = json.dumps({"context_length": 1000})

    # Create a "large" file
    large_content = "x" * 5000
    test_file = tmp_path / "large.txt"
    test_file.write_text(large_content)

    mock_chat.side_effect = [
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{
                    'function': {
                        'name': 'read_file',
                        'arguments': json.dumps({'filepaths': [str(test_file)]})
                    }
                }]
            }
        },
        {'message': {'role': 'assistant', 'content': 'It was too big.'}},
        {'message': {'role': 'assistant', 'content': '{"status": "complete"}'}}
    ]

    with patch("os.path.exists", return_value=True):
        await ask_local_assistant("Read large", num_ctx=num_ctx)

    history_sent_to_turn_2 = mock_chat.call_args_list[1][1]['messages']
    tool_result_msg = history_sent_to_turn_2[-2]

    assert f"--- FILE: {test_file} (1 lines total) ---" in tool_result_msg['content']
    assert "[WARNING: Output truncated due to context limits" in tool_result_msg['content']
    assert len(tool_result_msg['content']) < 2000

@pytest.mark.asyncio
@patch("ollama.chat")
@patch("mcp_server.get_model_info")
@patch("mcp_server.PdfReader")
async def test_read_file_tail(mock_pdf_reader, mock_get_info, mock_chat, tmp_path):
    """Test reading the tail of text and PDF files."""
    mock_get_info.return_value = json.dumps({"context_length": 32768})

    # 1. Text file tail
    text_file = tmp_path / "tail_test.txt"
    text_file.write_text("line1\nline2\nline3\nline4\nline5\n")

    # 2. PDF file tail (mocked)
    pdf_file = tmp_path / "tail_test.pdf"
    pdf_file.write_text("fake pdf")

    mock_pages = []
    for i in range(1, 6):
        p = MagicMock()
        p.extract_text.return_value = f"page {i} content"
        mock_pages.append(p)
    mock_pdf_reader.return_value.pages = mock_pages

    mock_chat.side_effect = [
        # Turn 1: Read tail of text file (last 2 lines)
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{
                    'function': {
                        'name': 'read_file',
                        'arguments': json.dumps({'filepaths': [str(text_file)], 'tail': 2})
                    }
                }]
            }
        },
        # Turn 2: Read tail of PDF file (last 2 pages)
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{
                    'function': {
                        'name': 'read_file',
                        'arguments': json.dumps({'filepaths': [str(pdf_file)], 'tail': 2})
                    }
                }]
            }
        },
        # Turn 3: Final response
        {'message': {'role': 'assistant', 'content': 'Read tails.'}},
        # Turn 3: Reflection
        {'message': {'role': 'assistant', 'content': '{"status": "complete"}'}}
    ]

    with patch("os.path.exists", return_value=True):
        await ask_local_assistant("Read tails of text and pdf")

    # Verify Text Tail Result
    # History passed to Turn 2 (index 1) contains Turn 1 tool result
    history_2 = mock_chat.call_args_list[1][1]['messages']
    text_tool_res = history_2[-2]['content']
    assert "line4\nline5\n" in text_tool_res
    assert "--- FILE: " in text_tool_res
    assert "(5 lines total)" in text_tool_res

    # Verify PDF Tail Result
    # History passed to Turn 3 (index 2) contains Turn 2 tool result
    history_3 = mock_chat.call_args_list[2][1]['messages']
    pdf_tool_res = history_3[-2]['content']
    assert "page 4 content" in pdf_tool_res
    assert "page 5 content" in pdf_tool_res
    assert "page 3 content" not in pdf_tool_res
    assert "--- Page 4 ---" in pdf_tool_res
    assert "--- Page 5 ---" in pdf_tool_res
    assert "--- FILE: " in pdf_tool_res
    assert "(5 pages total)" in pdf_tool_res

@pytest.mark.asyncio
@patch("ollama.chat")
@patch("mcp_server.get_model_info")
async def test_interactive_clarification(mock_get_info, mock_chat):
    """Test that the assistant can pause for clarification."""
    mock_get_info.return_value = json.dumps({"context_length": 32768})

    mock_chat.side_effect = [
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{
                    'function': {
                        'name': 'request_clarification',
                        'arguments': json.dumps({'question': 'Which file do you mean?'})
                    }
                }]
            }
        }
    ]

    result = await ask_local_assistant("Fix the file")

    assert result.startswith("CLARIFICATION_REQUIRED:")
    assert "Which file do you mean?" in result
    assert mock_chat.call_count == 1

@pytest.mark.asyncio
@patch("mcp_server.run_shell_command")
@patch("ollama.chat")
@patch("mcp_server.get_model_info")
async def test_batch_shell_commands(mock_get_info, mock_chat, mock_shell):
    """Test executing multiple shell commands in one turn."""
    mock_get_info.return_value = json.dumps({"context_length": 32768})
    mock_shell.side_effect = ["Output 1", "Output 2"]

    mock_chat.side_effect = [
        {
            'message': {
                'role': 'assistant',
                'tool_calls': [{
                    'function': {
                        'name': 'run_shell_command',
                        'arguments': json.dumps({'commands': ['ls', 'pwd']})
                    }
                }]
            }
        },
        {'message': {'role': 'assistant', 'content': 'Done.'}},
        {'message': {'role': 'assistant', 'content': '{"status": "complete"}'}}
    ]

    await ask_local_assistant("Run ls and pwd")

    history_sent_to_turn_2 = mock_chat.call_args_list[1][1]['messages']
    tool_result_msg = history_sent_to_turn_2[-2]

    assert "--- COMMAND: ls ---" in tool_result_msg['content']
    assert "--- COMMAND: pwd ---" in tool_result_msg['content']
    assert "Output 1" in tool_result_msg['content']
    assert "Output 2" in tool_result_msg['content']
