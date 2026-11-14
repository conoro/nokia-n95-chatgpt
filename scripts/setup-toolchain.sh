#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .toolchain
if [[ ! -d .toolchain/template ]]; then
    git clone https://github.com/gtrxAC/j2me-template.git .toolchain/template
fi
git -C .toolchain/template checkout --detach b1be318cef88a0d2a1239841b9c45190a4df2401
curl -fL https://repo.maven.apache.org/maven2/net/sf/proguard/proguard-base/6.2.2/proguard-base-6.2.2.jar -o .toolchain/proguard.jar
python3 - <<'PY'
import hashlib
from pathlib import Path
actual = hashlib.sha256(Path('.toolchain/proguard.jar').read_bytes()).hexdigest()
assert actual == '7587a3a415d6aea1946f597f4babe710a245f085bac4dc5e7cda653acfc39b03', 'ProGuard checksum mismatch'
PY
if [[ -n "${JAVA_HOME:-}" ]]; then
    echo "Using your JAVA_HOME. It must point to a JDK 8 installation."
elif [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]]; then
    curl -fL 'https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u512-b09/OpenJDK8U-jdk_x64_linux_hotspot_8u512b09.tar.gz' -o .toolchain/jdk.tar.gz
    python3 - <<'PY'
import hashlib
from pathlib import Path
actual = hashlib.sha256(Path('.toolchain/jdk.tar.gz').read_bytes()).hexdigest()
assert actual == 'fb3bfa869012419b562bb4235d0d83ec4f8c1dda62ae432ba20c6c3a7e43f7e4', 'JDK checksum mismatch'
PY
    tar -xzf .toolchain/jdk.tar.gz -C .toolchain
else
    echo 'Install a JDK 8 for your OS/CPU, set JAVA_HOME, then run ./build.sh.'
fi
