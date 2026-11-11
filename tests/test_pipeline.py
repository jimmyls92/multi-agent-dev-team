"""Unit tests of the routing after the PM (spec `lab_2_3_pipeline`, AC-2.3-5)."""

from langgraph.graph import END

from orchestration.graph import CODER_NODE, route_after_pm
from orchestration.state import ProjectState
from tests.coder_helpers import state_data


def test_ac_2_3_5_route_after_pm():
    with_tasks = ProjectState.model_validate(state_data())
    failed = with_tasks.model_copy(update={"error": "RuntimeError: API down"})
    no_tasks = with_tasks.model_copy(update={"tasks": []})

    assert route_after_pm(with_tasks) == CODER_NODE
    assert route_after_pm(failed) == END
    assert route_after_pm(no_tasks) == END
