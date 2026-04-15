FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QT_QPA_PLATFORM=xcb \
    DISPLAY=:99

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        python3-pyqt5 \
        python3-pyqt5.qtmultimedia \
        python3-requests \
        xvfb \
        libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
        libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
        libxcb-xkb1 libxkbcommon-x11-0 libxcb-cursor0 \
        libgl1 \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-ugly gstreamer1.0-libav \
        fonts-liberation \
        libjpeg62-turbo zlib1g libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv --system-site-packages /venv
ENV PATH="/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p logs

EXPOSE 0

CMD ["xvfb-run", "--server-args=-screen 0 1920x1080x24 -ac", \
     "python3", "kiosk.py"]
