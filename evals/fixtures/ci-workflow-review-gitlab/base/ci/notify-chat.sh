#!/bin/sh
# Post a one-line message to the team chat channel. CHAT_WEBHOOK_URL is a
# masked, protected CI/CD variable.
set -eu
wget -q -O /dev/null --post-data "text=$1" "$CHAT_WEBHOOK_URL"
