# hass-time-machine

*Rule the time*

The component that provides WebSocket API that can rewrite histories for entities.
Intended to be used to fabricate the history for taking a screenshot of a history-displaying card.

# Example
Send to HA websocket
```json
{
    "type": "time_machine/rewrite_history",
    "entities": [{ 
        "entity_id": "input_boolean.test", 
        "constant_attributes": {
            "editable": false 
        },
        "history": [
            {
                "state": "off", 
                "timestamp": "2022-08-21T00:00:00Z",
                "attributes": {} 
            }, {
                "state": "on", 
                "timestamp": "2022-08-21T01:00:00Z",
                "attributes": {} 
            }
        ]
    }]
}
```

As a result current state of input_boolean.test will change to 'on' since 2022-08-21 01:00:00 UTC. Also history entries will be created for both state changes.
