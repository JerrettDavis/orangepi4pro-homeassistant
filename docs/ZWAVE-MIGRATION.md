# Z-Wave production migration

This is an ownership transfer of an existing network, not a new inclusion
workflow. Never reset the controller, exclude/reinclude devices, or generate
replacement security keys during migration.

## Evidence to capture before disconnecting anything

Keep this material private and encrypted:

- exact current Z-Wave JS/server version and packaging,
- controller manufacturer/model, firmware, Home ID, and stable USB identity,
- a controller/NVM backup when the controller and software support it,
- the complete stopped server store,
- S0 and all S2 keys, including Long Range keys when used,
- node count and a short list of critical secure and mains-powered nodes,
- the existing Home Assistant Z-Wave integration endpoint,
- the commands that stop and restart the old radio server.

Do not print key values in inventory output or terminal transcripts. A record
that each required key exists is sufficient for the public checklist.

## Prepare the Orange Pi without claiming the radio

1. Leave the production controller attached to the old server.
2. Install/render Z-Wave JS UI on the Orange Pi with the service disabled.
3. After the controller is eventually attached, identify it through
   `/dev/serial/by-id/`; do not configure `/dev/ttyUSB0` or `/dev/ttyACM0`.
4. Import the stopped Z-Wave JS UI store only if the source really is Z-Wave
   JS UI. Other Z-Wave JS packages require their supported export/import path.
5. Review UI authentication and keep management and WebSocket ports on
   loopback unless an explicit firewall/proxy design says otherwise.

The current hardware baseline has no controller attached and no
`/dev/serial/by-id` entry. Therefore the stable path and radio operation remain
pending hardware evidence.

## Deliberate cutover

1. Stop Home Assistant or disable its Z-Wave integration so it cannot reconnect
   while the radio server moves.
2. Stop the old Z-Wave server and verify it stays stopped.
3. Disconnect the controller once and attach it to the Orange Pi.
4. Record the new `/dev/serial/by-id/...` path and configure that exact path.
5. Start local Z-Wave JS UI. Confirm Home ID and node inventory before changing
   any security or inclusion setting.
6. Reconfigure the existing Home Assistant integration to the local WebSocket
   endpoint. Preserve the existing integration entry so entity identities are
   not needlessly recreated.
7. Validate several mains-powered nodes, at least one secure node, locks/access
   control where present, and sleeping battery nodes as they wake.

Do not perform firmware updates during this transfer. They create a second
change axis and may invalidate the rollback pairing of software, store, and
controller state.

## Rollback

Stop Home Assistant's local Z-Wave connection, stop local Z-Wave JS UI, move
the controller back, restore the old server's matching version/store when
needed, and start only the old server. Revert the HA integration endpoint only
after the old radio server is healthy. Never run both radio servers against
the same controller or treat exclusion/reinclusion as rollback.
