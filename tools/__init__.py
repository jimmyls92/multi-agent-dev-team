"""Tools the agents can call (Lab 1.2, C1.3).

Exports the lab functions and TOOL_HANDLERS, the validated wrappers that
LLM tool calls are dispatched to (DEC-042).
"""

from .file_io import read_file, write_file
from .code_executor import exec_python
from .handlers import TOOL_HANDLERS  # DEC-042: validated wrappers
