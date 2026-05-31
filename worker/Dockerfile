FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y make git linux-perf iptables curl wget gcc libssl-dev
RUN pip install requests

RUN useradd -r -m net_user

# usuario no privilegiado para la ejecucion de tareas
RUN groupadd -r worker && useradd -r -g worker -m worker


RUN mv /usr/bin/curl /usr/bin/curl.real && mv /usr/bin/wget /usr/bin/wget.real

COPY container/curl_wrapper.c /tmp/curl_wrapper.c
COPY container/wget_wrapper.c /tmp/wget_wrapper.c

RUN gcc /tmp/curl_wrapper.c -o /usr/bin/curl -lssl -lcrypto && \
    gcc /tmp/wget_wrapper.c -o /usr/bin/wget -lssl -lcrypto 

RUN chown net_user:net_user /usr/bin/curl /usr/bin/wget && \
    chmod u+s /usr/bin/curl /usr/bin/wget

RUN touch /home/net_user/external_deps.log && \
    chown net_user:net_user /home/net_user/external_deps.log && \
    chmod 600 /home/net_user/external_deps.log

COPY container/upload_results.py /scripts/upload_results.py
COPY container/hash_util.py /scripts/hash_util.py
COPY container/iptables.sh /scripts/iptables.sh

RUN chmod +x /scripts/iptables.sh

RUN usermod -aG worker net_user
RUN usermod -aG worker root

RUN mkdir -p /repo && \
    chown worker:worker /repo && \
    chmod 775 /repo

RUN chmod 750 /home/worker && chown worker:worker /home/worker

USER worker
WORKDIR /repo
