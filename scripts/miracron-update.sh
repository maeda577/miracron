#!/bin/ash
set -eu

# 録画ルール生成(ファイルは上書きされる)
python3 /usr/local/lib/miracron/miracron.py --outfile /var/spool/cron/crontabs/root
# 定期アップデートルールを末尾に追加
echo "${MIRACRON_UPDATE_SCHEDULE:-0 5 * * *} miracron-update.sh" >> /var/spool/cron/crontabs/root
# cron更新したフラグを作成
echo 'root' >> /var/spool/cron/crontabs/cron.update
