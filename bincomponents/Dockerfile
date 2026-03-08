# Use Python 3.11 on Debian Bookworm for a stable glibc base
FROM python:3.11-slim-bullseye

# Install essential build tools and Qt/XCB dependencies
# We include 'binutils' and 'patchelf' which PyInstaller needs to
# bake the RPATH into your binary for ICU/Qt.
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils \
    g++ \
    git \
    libcairo-gobject2 \
    libcairo2 \
    libdbus-1-3 \
    libegl1 \
    libfontconfig1 \
    libfreetype6 \
    libgdk-pixbuf-2.0-0 \
    libgl1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libharfbuzz0b \
    libicu-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libtiff5 \
    libx11-xcb1 \
    libxcb-cursor0 \
    libxcb-glx0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    locales \
    patchelf \
    pkg-config \
    zip \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen

RUN git config --system --add safe.directory /src

ENV NLTK_DATA=/tmp/nltk_data
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
WORKDIR /src
