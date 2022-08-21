import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.tasks import EventTask, PurgeEntitiesTask
from homeassistant.components.websocket_api import (
    ActiveConnection,
    async_register_command,
    decorators,
)
from homeassistant.core import (
    EVENT_STATE_CHANGED,
    Event,
    EventOrigin,
    HomeAssistant,
    State,
)
from homeassistant.helpers import config_validation as cv

_LOGGER = logging.getLogger(__name__)


async def wait_for_recorder_done(hass: HomeAssistant) -> None:
    # block_till_done waits for recorder queue being empty.
    # It doesn't wait for recorder to execute the last task.
    # But who cares.
    recorder = get_instance(hass)
    await hass.async_add_executor_job(recorder.block_till_done)


def prepare_entity_history(entity_data: Any) -> List[State]:
    entity_id = entity_data["entity_id"]
    constant_attributes = entity_data["constant_attributes"]
    history = list(entity_data["history"])

    history.sort(key=lambda item: item["timestamp"])  # type: ignore

    states: List[State] = []
    prev_state: Optional[str] = None
    prev_timestamp: Optional[datetime] = None
    for item in history:
        state_changed = item["state"] != prev_state
        attrs = {**constant_attributes, **item["attributes"]}
        last_changed = item["timestamp"] if state_changed else prev_timestamp
        last_updated = item["timestamp"]
        prev_state = item["state"]
        prev_timestamp = item["timestamp"]
        states.append(
            State(
                entity_id=entity_id,
                state=item["state"],
                attributes=attrs,
                last_changed=last_changed,
                last_updated=last_updated,
            )
        )
    return states


def prepare_entity_histories(entities_data: Any) -> List[List[State]]:
    histories: List[List[State]] = []
    for entity_history in entities_data:
        histories.append(prepare_entity_history(entity_history))
    return histories


@decorators.websocket_command(
    {
        vol.Required("type"): "time_machine/rewrite_history",
        vol.Required("entities"): [
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required("constant_attributes"): {cv.string: cv.string},
                vol.Required("history"): [
                    {
                        vol.Required("state"): str,
                        vol.Required("attributes"): {cv.string: cv.string},
                        vol.Required("timestamp"): cv.datetime,
                    }
                ],
            }
        ],
    }
)
@decorators.async_response
async def rewrite_history_command(
    hass: HomeAssistant, connection: ActiveConnection, msg: Dict[str, Any]
) -> None:
    entity_ids = set(e["entity_id"] for e in msg["entities"])

    # Sanity checks
    if len(entity_ids) != len(msg["entities"]):
        connection.send_error(msg["id"], "400", "duplicate entity ids")
        return
    for entity_data in msg["entities"]:
        if len(entity_data["history"]) == 0:
            connection.send_error(
                msg["id"], "400", f"{entity_data['entity_id']} has empty history"
            )
            return

    histories = prepare_entity_histories(msg["entities"])
    recorder = get_instance(hass)

    # Set states
    for entity_history in histories:
        last_state = entity_history[-1]
        prelast_state = entity_history[-2] if len(entity_history) >= 2 else None

        # Set state
        # Based on hass.async_set that dosn't have power to control time.
        # We have to modify private state because there is no suitable public method.
        # pylint: disable=protected-access
        hass.states._states[last_state.entity_id] = last_state
        hass.bus.async_fire(
            EVENT_STATE_CHANGED,
            {
                "entity_id": last_state.entity_id,
                "old_state": prelast_state,
                "new_state": last_state,
            },
            EventOrigin.local,
            time_fired=last_state.last_updated,
        )

    # Forget the history
    recorder.queue_task(
        PurgeEntitiesTask(entity_filter=lambda e_id: e_id in entity_ids)
    )
    await wait_for_recorder_done(hass)

    # Write the new history
    for history in histories:
        prev_state = None
        for state in history:
            event = Event(
                EVENT_STATE_CHANGED,
                {
                    "entity_id": state.entity_id,
                    "old_state": prev_state,
                    "new_state": state,
                },
            )
            recorder.queue_task(EventTask(event=event))
            prev_state = state
    await wait_for_recorder_done(hass)

    connection.send_result(msg["id"], "OK")


async def async_setup(hass: HomeAssistant, _hass_config: Any) -> bool:
    async_register_command(hass, rewrite_history_command)
    _LOGGER.info("Time Machine activated. Happy time travel!")
    return True
