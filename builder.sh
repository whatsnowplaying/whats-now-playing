#!/usr/bin/env bash

set -ex

SYSTEM=$1

if [[ -z "${SYSTEM}" ]]; then
  echo "Provide extra requirements"
  exit 1
fi

case "${SYSTEM}" in
  windows)
    PYTHON=python
    ;;
  macosx)
    PYTHON=python3
    "${PYTHON}" -m venv /tmp/venv
    # shellcheck disable=SC1091
    source /tmp/venv/bin/activate
  ;;
esac

rm -rf build dist || true

"${PYTHON}" -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-"${SYSTEM}".txt
pyside2-rcc nowplaying/resources/settings.qrc > nowplaying/qtrc.py
"${PYTHON}" setup.py build
mv nowplaying/version.py nowplaying/version.py.old
mv build/lib/nowplaying/version.py nowplaying/version.py
pyinstaller NowPlaying.spec
cp -p CHANGELOG* README* LICENSE.txt NOTICE.txt dist
mv dist NowPlaying-"${SYSTEM}"
mv nowplaying/version.py.old nowplaying/version.py

if [[ "${SYSTEM}" == "macosx" ]]; then
  rm -rf NowPlaying-macosx/NowPlaying || true
  zip -r NowPlaying-macosx.zip NowPlaying-macosx
fi
