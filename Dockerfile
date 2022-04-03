FROM docker.io/library/python:3
ARG MIRACRON_UPDATE_TIME="0 5 * * *"
ENV MIRACRON_UPDATE_COMMAND="set -o pipefail && busybox crontab -l | head -n 1 | python3 /usr/local/lib/miracron/miracron.py /etc/miracron/config.yml | busybox crontab -"
ENV MIRACRON_SHOW_COMMAND="busybox crontab -l | grep '^#'"

RUN pip3 install pyyaml yamale && \
    apt update && apt install --yes busybox-static && \
    mkdir -p /var/spool/cron/crontabs && \
    (echo '#!/bin/bash'; echo "${MIRACRON_UPDATE_COMMAND}") > /usr/local/bin/miracron-update.sh && \
    (echo '#!/bin/bash'; echo "${MIRACRON_SHOW_COMMAND}") > /usr/local/bin/miracron-show.sh && \
    chmod +x /usr/local/bin/miracron-update.sh && \
    chmod +x /usr/local/bin/miracron-show.sh && \
    echo "${MIRACRON_UPDATE_TIME} miracron-update.sh" | busybox crontab -

COPY miracron.py schema.yml /usr/local/lib/miracron/
CMD ["busybox", "crond", "-f", "-l", "8", "-L", "/dev/stderr"]
