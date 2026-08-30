#!/bin/sh
set -eu
umask 077

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
source_file="$script_dir/AirDropShare.swift"
runtime_root="$repo_root/.runtime"
native_dir="$runtime_root/native"
runtime_dir="$native_dir/airdrop-share"
output="$runtime_dir/airdrop-share"

[ -f "$source_file" ] && [ ! -L "$source_file" ] || {
  echo "Swift helper source must be a regular non-symlink file" >&2
  exit 2
}

ensure_owned_directory() {
  directory=$1
  if [ -L "$directory" ]; then
    echo "Refusing symlinked runtime directory: $directory" >&2
    exit 2
  fi
  if [ -e "$directory" ]; then
    [ -d "$directory" ] || {
      echo "Runtime path is not a directory: $directory" >&2
      exit 2
    }
    [ "$(/usr/bin/stat -f %u "$directory")" = "$(/usr/bin/id -u)" ] || {
      echo "Runtime directory is not owned by the current user: $directory" >&2
      exit 2
    }
  else
    /bin/mkdir -m 700 "$directory"
  fi
  /bin/chmod 700 "$directory"
}

ensure_owned_directory "$runtime_root"
ensure_owned_directory "$native_dir"
ensure_owned_directory "$runtime_dir"
if [ -e "$output" ] || [ -L "$output" ]; then
  [ -f "$output" ] && [ ! -L "$output" ] || {
    echo "Existing helper is not a regular non-symlink file" >&2
    exit 2
  }
  [ "$(/usr/bin/stat -f %u "$output")" = "$(/usr/bin/id -u)" ] || {
    echo "Existing helper is not owned by the current user" >&2
    exit 2
  }
fi
temporary=$(mktemp "$runtime_dir/.airdrop-share.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM

/usr/bin/xcrun --sdk macosx swiftc \
  -O \
  -framework AppKit \
  "$source_file" \
  -o "$temporary"
chmod 700 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT HUP INT TERM
