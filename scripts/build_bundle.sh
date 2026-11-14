#!/usr/bin/env bash
set -euo pipefail
NODE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_NAME=operator-vlm-action-policy
if [[ "$(uname -s)" != Linux ]]; then
  printf 'Build this Linux Node on the target Linux architecture.\n' >&2
  exit 1
fi
PYTHON="${NODE_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  printf 'Run uv sync --frozen in the project directory before building.\n' >&2
  exit 1
fi
VERSION="$("${PYTHON}" -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "${NODE_ROOT}/pyproject.toml")"
OUT_ROOT="${VLM_BUNDLE_OUTPUT_DIR:-${NODE_ROOT}/dist/release}"
mkdir -p "${OUT_ROOT}"
OUT_ROOT="$(cd -- "${OUT_ROOT}" && pwd)"
ARCHIVE="${OUT_ROOT}/${NODE_NAME}-${VERSION}-linux-$(uname -m).tar.gz"
if [[ -e "${ARCHIVE}" ]]; then
  printf 'Refusing to overwrite existing archive: %s\n' "${ARCHIVE}" >&2
  exit 1
fi
# Build in a clean intermediate directory; never include a development venv or secrets.
BUILD_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${BUILD_ROOT}"' EXIT
"${PYTHON}" -m PyInstaller --noconfirm --clean --onedir \
  --name "${NODE_NAME}" --paths "${NODE_ROOT}/src" \
  --collect-all dora --collect-all forge_msgs \
  --distpath "${BUILD_ROOT}/dist" --workpath "${BUILD_ROOT}/build" \
  --specpath "${BUILD_ROOT}" "${NODE_ROOT}/scripts/entrypoint.py"
PACKAGE_ROOT="${BUILD_ROOT}/dist/${NODE_NAME}"
mkdir -p "${PACKAGE_ROOT}/config"
cp "${NODE_ROOT}/examples/libero/policy.yaml" "${PACKAGE_ROOT}/config/policy.yaml"
cp "${NODE_ROOT}/LICENSE" "${NODE_ROOT}/NOTICE" "${PACKAGE_ROOT}/"
chmod 0755 "${PACKAGE_ROOT}/${NODE_NAME}"
# Check the frozen executable outside the source tree, without model credentials.
(cd -- "${BUILD_ROOT}" && "${PACKAGE_ROOT}/${NODE_NAME}" \
  --config "${PACKAGE_ROOT}/config/policy.yaml" --check-config)
STAGED_ARCHIVE="${BUILD_ROOT}/${NODE_NAME}.tar.gz"
tar -czf "${STAGED_ARCHIVE}" -C "${BUILD_ROOT}/dist" "${NODE_NAME}"
"${PYTHON}" "${NODE_ROOT}/scripts/verify_bundle.py" "${STAGED_ARCHIVE}"
mv -- "${STAGED_ARCHIVE}" "${ARCHIVE}"
(cd -- "${OUT_ROOT}" && sha256sum "$(basename -- "${ARCHIVE}")" > "${ARCHIVE}.sha256")
printf 'Node archive: %s\nChecksum: %s.sha256\n' "${ARCHIVE}" "${ARCHIVE}"
