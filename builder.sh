#!/usr/bin/env bash

set -e

export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SYSTEM=$1
VERSION=$(git describe --tags)
UNAMESYS=$(uname -s)

check_python_version() {
  local pybin="$1"
  local pyver
  local IFS='.'
  local -a PY_VER
  pyver=$("${pybin}" --version 2>&1)
  pyver=${pyver#* }
  read -ra PY_VER <<< "${pyver}"
  if [[ ${PY_VER[0]} -ne 3 || ${PY_VER[1]} -lt 11 ]]; then
    echo "Python 3.11 or later is required (got ${pyver})."
    exit 1
  fi
  if [[ ${PY_VER[1]} -ge 15 ]]; then
    echo "Python 3.15+ is not yet supported (got ${pyver}). Use Python 3.11–3.14."
    exit 1
  fi
}

if [[ "${SYSTEM}" == "dev" ]]; then
  case "${UNAMESYS}" in
    MINGW*)
      PYTHON=python
      ACTIVATE="venv/Scripts/activate"
      ;;
    *)
      PYTHON=python3
      ACTIVATE="venv/bin/activate"
      ;;
  esac
  PYTHONBIN="${PYTHONBIN:-$(command -v "${PYTHON}")}"
  if [[ -z "${PYTHONBIN}" ]]; then
    echo "Error: '${PYTHON}' not found on PATH. Please install Python 3.11–3.13."
    exit 1
  fi
  check_python_version "${PYTHONBIN}"
  echo "*****"
  echo "* Dev setup using ${PYTHONBIN} ($("${PYTHONBIN}" --version 2>&1))"
  echo "****"
  if [[ ! -d venv ]]; then
    "${PYTHONBIN}" -m venv venv
  fi
  # shellcheck disable=SC1090
  source "${ACTIVATE}"
  PYTHONBINDIR=$(dirname "${ACTIVATE}")
  PYTHONBIN="${PYTHONBINDIR}/${PYTHON}"
  "${PYTHONBIN}" -m pip install --upgrade pip
  "${PYTHONBIN}" -m pip install --upgrade --upgrade-strategy eager -e ".[dev,docs,osspecials,test]"
  "${PYTHONBIN}" -m vendoring sync
  git checkout nowplaying/vendor/.gitkeep
  versioningit --write
  "${PYTHONBIN}" tools/setupnltk.py
  "${PYTHONBIN}" tools/build_templates.py
  if [[ -x "${PYTHONBINDIR}/pyside6-rcc" ]]; then
    "${PYTHONBINDIR}/pyside6-rcc" nowplaying/resources/settings.qrc > nowplaying/qtrc.py
  else
    pyside6-rcc nowplaying/resources/settings.qrc > nowplaying/qtrc.py
  fi
  echo "*****"
  echo "* Dev setup complete. Activate with: source ${ACTIVATE}"
  echo "* Then run: ./wnppyi.py"
  echo "****"
  exit 0
fi

if [[ "${SYSTEM}" == "linuxbin" ]]; then
  docker buildx build --load -t wnp-linux-builder  -f bincomponents/Dockerfile .
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$(pwd):/src" \
    wnp-linux-builder /src/builder.sh linux
  exit 0
fi

if [[ -z "${SYSTEM}" ]]; then
  case "${UNAMESYS}" in
    Darwin)
      SYSTEM=macosx
      ;;
    MINGW*)
      SYSTEM=windows
      ;;
    *)
      ;;
  esac
fi

case "${SYSTEM}" in
  windows)
    PYTHON=python
    ;;
  macosx|linux)
    PYTHON=python3
    ;;
  *)
    PYTHON=python
    ;;
esac

# Generate user-friendly distribution name
case "${SYSTEM}" in
  macosx)
    # Detect macOS version and architecture
    MACOS_VERSION=$(sw_vers -productVersion | cut -d. -f1)
    ARCH=$(uname -m)
    if [[ "${ARCH}" == "arm64" ]]; then
      DISTNAME="macOS${MACOS_VERSION}-AppleSilicon"
    else
      DISTNAME="macOS${MACOS_VERSION}-Intel"
    fi
    ;;
  windows)
    DISTNAME="Windows"
    ;;
  linux)
    ARCH=$(uname -m)
    DISTNAME="Linux-${ARCH}"
    ;;
  *)
    DISTNAME="${SYSTEM}"
    ;;
esac

DISTDIR=WhatsNowPlaying-"${VERSION}-${DISTNAME}"

PYTHONBIN="${PYTHONBIN:-$(command -v "${PYTHON}")}"
echo "*****"
echo "* Building on ${SYSTEM} / ${UNAMESYS}"
echo "* Using ${PYTHONBIN} ($("${PYTHONBIN}" --version 2>&1))"
echo "****"

check_python_version "${PYTHONBIN}"

case "${SYSTEM}" in
  windows)
    echo "*****"
    echo "* Building a virtual environment"
    echo "****"
    rm -rf "${TMP}/build-venv" || true
    "${PYTHONBIN}" -m venv "${TMP}/build-venv"
    # shellcheck disable=SC1091
    source "${TMP}/build-venv/scripts/activate"
    ;;
  *)
    echo "*****"
    echo "* Building a virtual environment"
    echo "****"
    rm -rf /tmp/build-venv || true
    "${PYTHONBIN}" -m venv /tmp/build-venv
    # shellcheck disable=SC1091
    source /tmp/build-venv/bin/activate
    ;;
esac

PYTHONBIN=$(command -v "${PYTHON}")
PYTHONBINDIR=$(dirname "${PYTHONBIN}")

rm -rf build dist || true

echo "*****"
echo "* Upgrading pip"
echo "****"

"${PYTHONBIN}" -m pip install --upgrade pip

echo "*****"
echo "* Installing dependencies"
echo "****"

"${PYTHONBIN}" -m pip install ".[binaries,osspecials]"

echo "*****"
echo "* Installing vendored dependencies"
echo "****"

"${PYTHONBIN}" -m vendoring sync

echo "*****"
echo "* Setting up NLTK"
echo "****"

"${PYTHONBIN}"  tools/setupnltk.py

echo "*****"
echo "* Update templates"
echo "****"

"${PYTHONBIN}" tools/build_templates.py

echo "*****"
echo "* Compiling Qt resources"
echo "****"

if [[ -x "${PYTHONBINDIR}/pyside6-rcc" ]]; then
  "${PYTHONBINDIR}/pyside6-rcc" nowplaying/resources/settings.qrc > nowplaying/qtrc.py
else
  rcc=$(command -v pyside6-rcc)
  echo "Using ${rcc}"
  pyside6-rcc nowplaying/resources/settings.qrc > nowplaying/qtrc.py
fi

echo "*****"
echo "* Making binary with PyInstaller "
echo "****"

if [[ -x "${PYTHONBINDIR}/pyinstaller" ]]; then
  "${PYTHONBINDIR}/pyinstaller" WhatsNowPlaying.spec
else
  rcc=$(command -v pyinstaller)
  echo "Using ${rcc}"
  pyinstaller WhatsNowPlaying.spec
fi

echo "*****"
echo "* Cleanup "
echo "****"

cp -p CHANGELOG* README* LICENSE.txt NOTICE.txt dist
rm -rf "${DISTDIR}" || true
mv dist "${DISTDIR}"

if [[ "${SYSTEM}" == "macosx" ]]; then
  rm -rf "${DISTDIR}"/WhatsNowPlaying || true
fi

if [[ ${SYSTEM} != "windows" ]]; then
  zip --symlinks -r "${DISTDIR}".zip "${DISTDIR}"
fi
