"""JSON schemas of the tools registered with the LLM (Lab 1.2).

The handlers in tools/file_io.py and tools/code_executor.py accept exactly
these parameter names and types; a mismatch fails silently when the LLM
calls a tool.

The schemas come from the lab and must not be modified.
"""

READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read the contents of a file at the given path. "
            "Returns the file contents as a string, or an error message "
            "if the file does not exist or cannot be read."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or absolute path to the file to read.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

WRITE_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Write content to a file at the given path. "
            "Creates the file if it does not exist; overwrites if it does. "
            "Returns a confirmation message including the number of lines written, "
            "or an error message if the write fails."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or absolute path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The full text content to write to the file.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
}

EXEC_PYTHON_SCHEMA = {
    "type": "function",
    "function": {
        "name": "exec_python",
        "description": (
            "Execute a Python script at the given path in a sandboxed subprocess. "
            "Returns stdout (truncated to 2000 chars) on success, or stderr and "
            "the return code on failure. "
            "Execution is killed after the timeout if it has not completed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the .py file to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Maximum seconds to allow the script to run. "
                        "Defaults to 10. Maximum allowed value is 30."
                    ),
                    "default": 10,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

ALL_TOOL_SCHEMAS = [READ_FILE_SCHEMA, WRITE_FILE_SCHEMA, EXEC_PYTHON_SCHEMA]