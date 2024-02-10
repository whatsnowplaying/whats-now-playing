#!/usr/bin/env bash

set -e

SYSTEM=$1
VERSION=$(git describe --tags)
DISTDIR=NowPlaying-"${VERSION}-${SYSTEM}"
UNAMESYS=$(uname -s)

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
  macosx)
    PYTHON=python3
    ;;
  *)
    PYTHON=python
    ;;
esac

PYTHONBIN=$(command -v "${PYTHON}")
echo "*****"
echo "* Building on ${SYSTEM} / ${UNAMESYS}"
echo "* Using ${PYTHONBIN}"
echo "****"

PYTHON_VERSION=$("${PYTHONBIN}" --version)
PYTHON_VERSION=${PYTHON_VERSION#* }
IFS="." read -ra PY_VERSION <<< "${PYTHON_VERSION}"

if [[ ${PY_VERSION[0]} -ne 3 && ${PY_VERSION[1]} -lt 10 ]]; then
  echo "Building requires at least version Python 3.10."
  exit 1
fi

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

"${PYTHONBIN}" -m pip install ".[dev,osspecials]"

echo "*****"
echo "* Setting up NLTK"
echo "****"

"${PYTHONBIN}"  setupnltk.py

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
  "${PYTHONBINDIR}/pyinstaller" NowPlaying.spec
else
  rcc=$(command -v pyinstaller)
  echo "Using ${rcc}"
  pyinstaller NowPlaying.spec
fi

echo "*****"
echo "* Cleanup "
echo "****"

cp -p CHANGELOG* README* LICENSE.txt NOTICE.txt dist
mv dist "${DISTDIR}"

if [[ "${SYSTEM}" == "macosx" ]]; then
  rm -rf "${DISTDIR}"/NowPlaying || true
  rm -rf "${DISTDIR}"/NowPlayingBeam || true
fi

if [[ ${SYSTEM} != "windows" ]]; then
  zip -r "${DISTDIR}".zip "${DISTDIR}"
fi
