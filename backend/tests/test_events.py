import pytest

from app.agent.events import RunEventHub


@pytest.mark.asyncio
async def test_run_event_hub_replays_and_delivers_new_events():
    hub = RunEventHub()
    await hub.publish(42, "plan_update", {"step": "window"})
    await hub.publish(42, "tool_call", {"tool_name": "query_metrics"})

    stream = hub.subscribe(42, after_id=1)
    replayed = await anext(stream)
    assert replayed.id == 2
    assert replayed.event == "tool_call"

    await hub.publish(42, "tool_summary", {"artifact_id": 9})
    delivered = await anext(stream)
    assert delivered.id == 3
    assert delivered.event == "tool_result_summary"
    await stream.aclose()

