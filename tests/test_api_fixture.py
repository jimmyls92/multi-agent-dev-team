"""Tests of the API request fixture itself (spec `lab_2_3_pipeline`, AC-2.3-19).

The fixture must tell a correct API from one that answers 415 instead of
400 to a body that is not JSON (DEC-118).
"""

import pytest

from tests.api_fixture import check_in_process, check_real_server

REFERENCE_API = '''
from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/echo")
def echo():
    body = request.get_json(silent=True)
    if body is None:
        return jsonify(error="body must be JSON"), 400
    return jsonify(body)


if __name__ == "__main__":
    app.run(port=0)
'''

# Flask's get_json() without silent=True answers 415 to a non-JSON content type.
STRICT_API = REFERENCE_API.replace("get_json(silent=True)", "get_json()")


@pytest.fixture
def api_file(tmp_path):
    """Returns a function that writes an API source to ``app.py`` in tmp_path.

    Args:
        tmp_path: Pytest's temporary folder.

    Returns:
        A function from source text to the written file's path.
    """

    def write(source: str):
        """Returns the path of ``app.py`` after writing the source to it."""
        path = tmp_path / "app.py"
        path.write_text(source, encoding="utf-8")
        return path

    return write


def test_ac_2_3_19_fixture_tells_apart(api_file):
    reference = api_file(REFERENCE_API)
    check = check_in_process(reference)
    assert check.returncode == 0, check.stderr
    assert "FIXTURE OK" in check.stdout
    check_real_server(reference)

    strict = api_file(STRICT_API)
    check = check_in_process(strict)
    assert check.returncode != 0
    assert "415" in check.stderr
    with pytest.raises(AssertionError, match="415"):
        check_real_server(strict)
