#!/bin/bash
# Watchdog for hermes-omc-workflow bridge
# Runs from the omc project repo, not the old discord-bridge directory

cd /home/dennis/hermes-omc-workflow

while true; do
    echo "[$(date)] Starting Hermes OMC Bridge..."
    python3 -u bridge.py >> bridge.log 2>&1
    EXIT_CODE=$?
    echo "[$(date)] Bridge exited with code $EXIT_CODE. Restarting in 5s..."
    sleep 5
done
