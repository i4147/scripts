#!/bin/sh

if ! pgrep -x "tor" >/dev/null; then
    tor >/dev/null 2>&1 &
    echo "Tor started..."
fi
