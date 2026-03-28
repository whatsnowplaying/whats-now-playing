# AlmaLinux 8 = manylinux_2_28: the exact ABI PySide6 wheels target.
# Ships libwebp.so.6, libtiff.so.5, glibc 2.28, Mesa 23.x natively —
# no compatibility shims needed.  Binaries run on Ubuntu 22.04+
# (glibc 2.34+) via backward glibc compatibility.
FROM almalinux:8

# Enable EPEL (patchelf, xcb-util-*) and PowerTools/CRB (some devel headers)
RUN dnf install -y epel-release dnf-plugins-core && \
    dnf config-manager --set-enabled powertools && \
    dnf clean all

# Python 3.12 + build essentials
# python3.12-devel is needed for pyicu / other extension wheels
RUN dnf install -y \
    python3.12 \
    python3.12-devel \
    binutils \
    gcc-c++ \
    git \
    glibc-langpack-en \
    libicu-devel \
    patchelf \
    pkg-config \
    zip \
    && dnf clean all

# Qt/WebEngine runtime deps that PySide6's bundled Qt6WebEngine needs at
# PyInstaller analysis time.  AlmaLinux 8 ships the same library versions
# the PySide6 manylinux wheel was compiled against, so PyInstaller bundles
# them under the right SONAMEs automatically.
RUN dnf install -y \
    alsa-lib \
    libdrm \
    mesa-libEGL \
    mesa-libGL \
    nss \
    nspr \
    pulseaudio-libs \
    libwayland-client \
    libwayland-cursor \
    libwayland-egl \
    libwayland-server \
    libX11-xcb \
    libxcb \
    xcb-util \
    xcb-util-cursor \
    xcb-util-image \
    xcb-util-keysyms \
    xcb-util-renderutil \
    xcb-util-wm \
    libxkbcommon-x11 \
    && dnf clean all

RUN git config --system --add safe.directory /src

# Tell builder.sh to use Python 3.12 explicitly
ENV PYTHONBIN=/usr/bin/python3.12
ENV NLTK_DATA=/tmp/nltk_data
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
WORKDIR /src
