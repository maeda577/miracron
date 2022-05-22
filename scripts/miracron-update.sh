#!/bin/ash
set -eu

unset MIRACRON_RULES
MIRACRON_RULES="$(python3 /usr/local/lib/miracron/miracron.py)"

(echo "${MIRACRON_UPDATE_SCHEDULE:-0 5 * * *} miracron-update.sh"; echo "$MIRACRON_RULES") | busybox crontab -
