import os
import sys
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# Add current directory to sys.path
sys.path.append(os.getcwd())

# --- MOCKING DEPENDENCIES ---
# We mock these BEFORE importing mcp_server because they are imported at the top level
sys.modules["ollama"] = MagicMock()
sys.modules["pypdf"] = MagicMock()

# Mock FastMCP so its .tool() decorator returns the original function
mock_mcp_instance = MagicMock()
mock_mcp_instance.tool.return_value = lambda f: f

mock_mcp_module = MagicMock()
mock_mcp_module.FastMCP.return_value = mock_mcp_instance

sys.modules["mcp"] = MagicMock()
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = mock_mcp_module

import mcp_server

class TestMCPServer(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Reset mocks
        sys.modules["ollama"].chat.reset_mock(side_effect=True, return_value=True)
        sys.modules["ollama"].list.reset_mock(side_effect=True, return_value=True)
        sys.modules["ollama"].chat.side_effect = None
        sys.modules["ollama"].chat.return_value = None
        sys.modules["ollama"].list.side_effect = None
        sys.modules["ollama"].list.return_value = None

    # --- Sandbox Detection Tests ---

    def test_is_sandboxed_true(self):
        with patch("ctypes.CDLL") as mock_cdll:
            mock_libsandbox = MagicMock()
            mock_libsandbox.sandbox_check.return_value = 1
            mock_cdll.return_value = mock_libsandbox
            self.assertTrue(mcp_server.is_sandboxed())

    def test_is_sandboxed_false(self):
        with patch("ctypes.CDLL") as mock_cdll:
            mock_libsandbox = MagicMock()
            mock_libsandbox.sandbox_check.return_value = 0
            mock_cdll.return_value = mock_libsandbox
            self.assertFalse(mcp_server.is_sandboxed())

    def test_is_sandboxed_exception(self):
        with patch("ctypes.CDLL", side_effect=Exception("Error")):
            self.assertFalse(mcp_server.is_sandboxed())

    # --- File Reading Tests ---

    def test_read_local_file_text(self):
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", unittest.mock.mock_open(read_data="hello")):
                result = mcp_server._read_local_file("test.txt")
                self.assertEqual(result, "hello")

    def test_read_local_file_not_found(self):
        with patch("os.path.exists", return_value=False):
            result = mcp_server._read_local_file("missing.txt")
            self.assertIn("not found", result)

    def test_read_local_file_pdf_success(self):
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "pdf text"
        mock_reader.pages = [mock_page]
        
        with patch("os.path.exists", return_value=True):
            with patch("mcp_server.PdfReader", return_value=mock_reader):
                result = mcp_server._read_local_file("test.pdf")
                self.assertEqual(result, "pdf text\n")

    def test_read_local_file_pdf_error(self):
        with patch("os.path.exists", return_value=True):
            with patch("mcp_server.PdfReader", side_effect=Exception("Bad PDF")):
                result = mcp_server._read_local_file("test.pdf")
                self.assertIn("Error reading PDF", result)

    # --- Tool Execution Tests ---

    async def test_run_shell_command_success(self):
        mock_result = MagicMock()
        mock_result.stdout = "out"
        mock_result.stderr = "err"
        mock_result.returncode = 0
        
        with patch("subprocess.run", return_value=mock_result):
            result = await mcp_server.run_shell_command("ls")
            self.assertIn("STDOUT:\nout", result)

    async def test_run_shell_command_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ls", timeout=30)):
            result = await mcp_server.run_shell_command("ls")
            self.assertIn("timed out", result)

    async def test_write_file_success(self):
        with patch("os.makedirs"):
            with patch("builtins.open", unittest.mock.mock_open()):
                result = await mcp_server.write_file("dir/file.txt", "data")
                self.assertIn("Successfully wrote", result)

    async def test_write_file_error(self):
        with patch("os.makedirs", side_effect=OSError("Perm Denied")):
            result = await mcp_server.write_file("dir/file.txt", "data")
            self.assertIn("Error writing file", result)

    # --- Agent Loop Logic ---

    async def test_ask_local_assistant_no_tool(self):
        sys.modules["ollama"].chat.return_value = {
            'message': {'role': 'assistant', 'content': 'hello'}
        }
        result = await mcp_server.ask_local_assistant("hi")
        self.assertEqual(result, "hello")

    async def test_ask_local_assistant_all_tools(self):
        # Mocking Turn 1: log_thought, Turn 2: read_file, Turn 3: write_file, Turn 4: run_shell_command, Turn 5: Finish
        sys.modules["ollama"].chat.side_effect = [
            {'message': {'role': 'assistant', 'tool_calls': [{'function': {'name': 'log_thought', 'arguments': {'thought': 't'}}}]}},
            {'message': {'role': 'assistant', 'tool_calls': [{'function': {'name': 'read_file', 'arguments': {'filepath': 'f.txt'}}}]}},
            {'message': {'role': 'assistant', 'tool_calls': [{'function': {'name': 'write_file', 'arguments': {'filepath': 'w.txt', 'content': 'c'}}}]}},
            {'message': {'role': 'assistant', 'tool_calls': [{'function': {'name': 'run_shell_command', 'arguments': {'command': 'ls'}}}]}},
            {'message': {'role': 'assistant', 'content': 'Done'}}
        ]
        
        with patch("mcp_server._read_local_file", return_value="read"):
            with patch("mcp_server.write_file", new_callable=AsyncMock, return_value="wrote"):
                with patch("mcp_server.run_shell_command", new_callable=AsyncMock, return_value="ran"):
                    result = await mcp_server.ask_local_assistant("hi")
                    self.assertEqual(result, "Done")
                    self.assertEqual(sys.modules["ollama"].chat.call_count, 5)

    async def test_ask_local_assistant_turn_limit(self):
        # Always return a tool call to hit the turn limit
        sys.modules["ollama"].chat.return_value = {
            'message': {'role': 'assistant', 'tool_calls': [{'function': {'name': 'log_thought', 'arguments': {'thought': 'Thinking'}}}]}
        }
        result = await mcp_server.ask_local_assistant("hi")
        self.assertIn("maximum turn limit", result)

    # --- Tool Wrapper Tests ---

    async def test_read_file_tool(self):
        with patch("mcp_server._read_local_file", return_value="content"):
            with patch("os.path.exists", return_value=True):
                result = await mcp_server.read_file("f.txt")
                self.assertEqual(result, "content")

    async def test_read_file_tool_missing(self):
        with patch("os.path.exists", return_value=False):
            result = await mcp_server.read_file("f.txt")
            self.assertIn("not found", result)

    async def test_ask_local_assistant_error(self):
        sys.modules["ollama"].chat.side_effect = Exception("Ollama Down")
        result = await mcp_server.ask_local_assistant("hi")
        self.assertIn("Error in local agent", result)

    # --- Model Listing ---

    async def test_list_local_models_success(self):
        sys.modules["ollama"].list.return_value = {
            'models': [{'name': 'm1'}, {'name': 'm2'}]
        }
        result = await mcp_server.list_local_models()
        self.assertIn("m1", result)
        self.assertIn("m2", result)

    async def test_list_local_models_empty(self):
        sys.modules["ollama"].list.return_value = {'models': []}
        result = await mcp_server.list_local_models()
        self.assertIn("No local models found", result)

    async def test_list_local_models_error(self):
        sys.modules["ollama"].list.side_effect = Exception("Failed")
        result = await mcp_server.list_local_models()
        self.assertIn("Error listing models", result)

if __name__ == "__main__":
    unittest.main()
