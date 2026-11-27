FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl iproute2 proxychains4 openssl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash playground
COPY dist/expose dist/expose-online /usr/local/bin/
COPY dist/expose dist/expose-online /opt/expose/dist/
COPY dist/console-clients/linux-amd64 /opt/expose/dist/console-clients/linux-amd64
COPY src/assets/consoles.py /opt/expose/src/assets/consoles.py
COPY tests/operator_cli.py /opt/expose/tests/operator_cli.py
ENV HOME=/home/playground PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
WORKDIR /home/playground
ENTRYPOINT ["python3", "/opt/expose/tests/operator_cli.py"]
CMD ["--playground"]
