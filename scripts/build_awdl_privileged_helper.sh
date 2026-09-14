#!/usr/bin/env bash
set -euo pipefail

if [[ "${PLATFORM_NAME:-}" != "macosx" ]]; then
  exit 0
fi

helper_label="${PRODUCT_BUNDLE_IDENTIFIER}.AwdlPrivilegedHelper"
helper_source="${SRCROOT}/Limelight/macOS/Helpers/AwdlPrivilegedHelperMain.m"
helper_include_dir="${SRCROOT}/Limelight/macOS/Helpers"
helper_output_dir="${TARGET_BUILD_DIR}/${CONTENTS_FOLDER_PATH}/Library/LaunchServices"
helper_output_path="${helper_output_dir}/${helper_label}"
helper_info_plist="${TARGET_TEMP_DIR}/AwdlPrivilegedHelper-Info.plist"
helper_launchd_plist="${TARGET_TEMP_DIR}/AwdlPrivilegedHelper-Launchd.plist"
has_signing_identity=1

if [[ -z "${EXPANDED_CODE_SIGN_IDENTITY_NAME:-}" || -z "${EXPANDED_CODE_SIGN_IDENTITY:-}" ]]; then
  has_signing_identity=0
  echo "warning: Building unsigned AWDL helper because no code signing identity is available"
fi

app_requirement=""
if [[ "${has_signing_identity}" -eq 1 ]]; then
  app_requirement="identifier \"${PRODUCT_BUNDLE_IDENTIFIER}\" and anchor apple generic and certificate leaf[subject.CN] = \"${EXPANDED_CODE_SIGN_IDENTITY_NAME}\" and certificate 1[field.1.2.840.113635.100.6.2.1] exists"
fi

python3 - \
  "$helper_info_plist" \
  "$helper_launchd_plist" \
  "$helper_label" \
  "${BUILD_NUMBER:-${CURRENT_PROJECT_VERSION:-1}}" \
  "$MARKETING_VERSION" \
  "$app_requirement" <<'PY'
import plistlib
import sys

info_path, launchd_path, helper_label, build_version, short_version, app_requirement = sys.argv[1:]

info = {
    "CFBundleIdentifier": helper_label,
    "CFBundleExecutable": helper_label,
    "CFBundleName": helper_label,
    "CFBundleVersion": build_version or "1",
    "CFBundleShortVersionString": short_version or "1.0",
}

if app_requirement:
    info["SMAuthorizedClients"] = [app_requirement]

launchd = {
    "Label": helper_label,
    "MachServices": {helper_label: True},
}

with open(info_path, "wb") as fp:
    plistlib.dump(info, fp)

with open(launchd_path, "wb") as fp:
    plistlib.dump(launchd, fp)
PY

mkdir -p "$helper_output_dir"
rm -f "$helper_output_path"

clang_args=(
  -fobjc-arc
  -fmodules
  -mmacosx-version-min="${MACOSX_DEPLOYMENT_TARGET}"
  -framework Foundation
  -framework Security
  -I"${helper_include_dir}"
)

# ARCHS arrives as one string, "arm64 x86_64", and every architecture has to
# become its own -arch argument, because clang rejects "-arch arm64 x86_64".
# bash splits an unquoted expansion on IFS, which is what the loop needs. zsh
# does not split unless forced with ${=ARCHS}, and that flag is what pinned this
# script to zsh: under bash it is a bad substitution at run time, invisible to
# bash -n. Unquoted $ARCHS is also strict, since set -u reports an unset ARCHS
# instead of building a helper with no architecture at all.
for arch in $ARCHS; do
  clang_args+=(-arch "$arch")
done

xcrun clang \
  "${clang_args[@]}" \
  "$helper_source" \
  -o "$helper_output_path" \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$helper_info_plist" \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __launchd_plist -Xlinker "$helper_launchd_plist"

/usr/bin/codesign --remove-signature "$helper_output_path" >/dev/null 2>&1 || true
if [[ "${has_signing_identity}" -eq 1 ]]; then
  /usr/bin/codesign --force --sign "${EXPANDED_CODE_SIGN_IDENTITY}" --timestamp=none "$helper_output_path"
else
  echo "note: Applying ad-hoc signature to AWDL helper"
  /usr/bin/codesign --force --sign - --timestamp=none "$helper_output_path"
fi
