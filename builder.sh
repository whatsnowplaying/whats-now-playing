#!/usr/bin/env bash

set -ex

SYSTEM=$1
VERSION=$(git describe --tags)
DISTDIR=NowPlaying-"${VERSION}-${SYSTEM}"

if [[ -z "${SYSTEM}" ]]; then
  echo "Provide extra requirements: 'windows' or 'macosx' "
  exit 1
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

PYTHON_VERSION=$("${PYTHON}" --version)
PYTHON_VERSION=${PYTHON_VERSION#* }
IFS="." read -ra PY_VERSION <<< "${PYTHON_VERSION}"

if [[ ${PY_VERSION[0]} -ne 3 && ${PY_VERSION[1]} -ne 10 ]]; then
  echo "Building requires version Python 3.10.  Binaries with 3.11 have been known to have issues."
  exit 1
fi

case "${SYSTEM}" in
  macosx)
    "${PYTHON}" -m venv /tmp/venv
    # shellcheck disable=SC1091
    source /tmp/venv/bin/activate
    ;;
  *)
    ;;
esac



rm -rf build dist || true

"${PYTHON}" -m pip install --upgrade pip
pip install ".[dev,osspecials]"
"${PYTHON}"  setupnltk.py
pyside6-rcc nowplaying/resources/settings.qrc > nowplaying/qtrc.py
pyinstaller NowPlaying.spec
cp -p CHANGELOG* README* LICENSE.txt NOTICE.txt dist
mv dist "${DISTDIR}"

if [[ "${SYSTEM}" == "macosx" ]]; then
  rm -rf "${DISTDIR}"/NowPlaying || true
  rm -rf "${DISTDIR}"/NowPlayingBeam || true
fi

if [[ ${SYSTEM} != "windows" ]]; then
  zip -r "${DISTDIR}".zip "${DISTDIR}"
fi
