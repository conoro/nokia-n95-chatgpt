#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
JDK_DIR="${JAVA_HOME:-}"
if [[ -z "$JDK_DIR" ]]; then
    for candidate in "$PWD"/.toolchain/jdk8*; do
        if [[ -d "$candidate" ]]; then JDK_DIR="$candidate"; break; fi
    done
fi
if [[ ! -x "$JDK_DIR/bin/javac" ]]; then
    echo 'Run scripts/setup-toolchain.sh or set JAVA_HOME to JDK 8.' >&2
    exit 1
fi
LIB="$PWD/.toolchain/template/sdk/lib"
rm -rf build/classes
mkdir -p build/classes dist
"$JDK_DIR/bin/javac" -source 1.3 -target 1.3 -Xlint:-options -bootclasspath "$LIB/cldc10.jar:$LIB/midp20.jar:$LIB/jsr135.jar" -d build/classes phone/src/*.java
"$JDK_DIR/bin/jar" cfm build/input.jar phone/manifest.mf -C build/classes . -C phone/res .
"$JDK_DIR/bin/java" -jar .toolchain/proguard.jar -injars build/input.jar -outjars dist/N95ChatGPT.jar -libraryjars "$LIB/cldc10.jar:$LIB/midp20.jar:$LIB/jsr135.jar" -microedition -target 1.2 -dontoptimize -dontobfuscate -keep 'public class * extends javax.microedition.midlet.MIDlet' -dontnote
cp phone/manifest.mf dist/N95ChatGPT.jad
printf 'MIDlet-Jar-URL: N95ChatGPT.jar\nMIDlet-Jar-Size: %s\n' "$(wc -c < dist/N95ChatGPT.jar)" >> dist/N95ChatGPT.jad
