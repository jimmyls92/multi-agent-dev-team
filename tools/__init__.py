"""Tools the agents can call (Lab 1.2, C1.3).

Exports the lab functions, TOOL_HANDLERS (the validated wrappers, DEC-042)
and dispatch_tool, the entry point for LLM tool calls (DEC-062).
"""

from .file_io import read_file, write_file
from .code_executor import ExecutionResult, exec_python, run_python  # DEC-063
from .handlers import TOOL_HANDLERS, ToolOutcome, dispatch_tool  # DEC-042, DEC-062
