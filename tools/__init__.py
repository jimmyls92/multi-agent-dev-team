from .file_io import read_file, write_file
from .code_executor import exec_python

TOOL_HANDLERS = {
    "read_file": read_file,
    "write_file": write_file,
    "exec_python": exec_python,
}