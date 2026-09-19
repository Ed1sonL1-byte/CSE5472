#!/bin/sh
set -eu

seedbridge_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
adapter_root="$seedbridge_root/adapters/medusa"
patched_root="$adapter_root/.patched/medusa-v1.5.1"
source_root="$(go env GOMODCACHE)/github.com/crytic/medusa@v1.5.1"
source_file="$source_root/fuzzing/fuzzer_worker_sequence_generator.go"
patched_file="$patched_root/fuzzing/fuzzer_worker_sequence_generator.go"
patch_file="$adapter_root/patches/medusa-v1.5.1-lineage.patch"
source_sha="4a8d63a9f0ab17589fdae7713a8c9bbfd4356f18103e2f6c4ca0572adfc01c7b"
patched_sha="d3793f5a7083fc518706d4db2a0b84f04c49e42d2075f2f7025ef2e52281a800"

if [ -f "$patched_file" ]; then
    actual_patched=$(shasum -a 256 "$patched_file" | cut -d ' ' -f 1)
    if [ "$actual_patched" = "$patched_sha" ]; then
        exit 0
    fi
    echo "seedbridge: refusing to overwrite unexpected patched Medusa tree: $patched_root" >&2
    exit 1
fi

if [ ! -f "$source_file" ]; then
    (cd "$adapter_root" && GOTOOLCHAIN=local go mod download github.com/crytic/medusa@v1.5.1)
fi
actual_source=$(shasum -a 256 "$source_file" | cut -d ' ' -f 1)
if [ "$actual_source" != "$source_sha" ]; then
    echo "seedbridge: Medusa v1.5.1 source checksum mismatch" >&2
    exit 1
fi

mkdir -p "$patched_root"
cp -R "$source_root"/. "$patched_root"/
chmod -R u+w "$patched_root"
patch -s -p1 -d "$patched_root" < "$patch_file"
actual_patched=$(shasum -a 256 "$patched_file" | cut -d ' ' -f 1)
if [ "$actual_patched" != "$patched_sha" ]; then
    echo "seedbridge: patched Medusa checksum mismatch" >&2
    exit 1
fi
