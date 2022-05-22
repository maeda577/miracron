#!/bin/ash
set -eu

# 初回アップデート実行してからcron開始
miracron-update.sh
crond -f -d 8
