#!/usr/bin/env bash

#
# build and install PySide2 5.15.2 for Apple M1
#

mkdir -p "${HOME}/Src/pyside"
pushd "${HOME}/Src/pyside" || exit 1
brew install qt@5 llvm cmake ninja
git clone --recursive --branch v5.15.2 https://code.qt.io/pyside/pyside-setup
pushd pyside-setup || exit 1
pip install -r requirements.txt
export CLANG_INSTALL_DIR=/opt/homebrew/opt/llvm
python setup.py build --qmake=/opt/homebrew/Cellar/qt\@5/5.15.2_1/bin/qmake --build-tests --ignore-git --parallel=8
popd || exit 1
popd || exit 1
