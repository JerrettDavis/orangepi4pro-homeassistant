#!/bin/sh
# Stop the trial Supervisor stack (data under the storage directory is kept). Needs root.
D="docker -H unix:///run/docker-trial.sock"
$D stop hassio_supervisor >/dev/null 2>&1 || true
$D ps -q | xargs -r $D stop >/dev/null
echo stopped
