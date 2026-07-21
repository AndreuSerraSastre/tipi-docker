FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       alsa-utils \
       espeak-ng \
       libasound2 \
       libportaudio2 \
       libatomic1 \
       libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tipi_voice ./tipi_voice
COPY entrypoint.sh /app/entrypoint.sh

RUN useradd --create-home --uid 10001 --groups audio tipi \
    && mkdir -p /state \
    && chmod 755 /app/entrypoint.sh \
    && chown -R tipi:tipi /state

USER tipi
ENTRYPOINT ["/app/entrypoint.sh"]
