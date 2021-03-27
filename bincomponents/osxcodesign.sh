#!/usr/bin/env bash

CERTIFICATE=$1

if [[ -z "${CERTIFICATE}" ]]; then
  echo "ERROR: Must provide name of certificate in keychain."
  exit 1
fi

codesign \
	-v \
	-s "${CERTIFICATE}" \
	--entitlements bincomponents/entitlements.plist \
	--deep \
	dist/NowPlaying.app/
