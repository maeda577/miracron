#!/bin/bash
set -eu
set -o pipefail

(echo "${MIRACRON_SAMBA_PASSWORD}"; echo "${MIRACRON_SAMBA_PASSWORD}") | pdbedit -a -u root --password-from-stdin

smbd --foreground --log-stdout --no-process-group -s /etc/samba/smb.conf
