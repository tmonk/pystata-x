#!/usr/bin/env bash
# Installs Stata on Linux under a Parallels Rosetta environment
set -euo pipefail

DEFAULT_URL="https://public.econ.duke.edu/stata/installers/19/StataNow19Linux64.tar.gz"
TARBALL_URL="${1:-$DEFAULT_URL}"
EXTRACT_DIR="/tmp/statafiles"
INSTALL_DIR="/usr/local/stata19"

echo "Downloading Stata 19..."
wget -q --show-progress -O /tmp/Stata19Linux64.tar.gz "$TARBALL_URL"

echo "Extracting..."
umask 0002
mkdir -p "$EXTRACT_DIR"
tar -zxf /tmp/Stata19Linux64.tar.gz -C "$EXTRACT_DIR"

echo "Installing Stata to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
"$EXTRACT_DIR/install" <<< "$INSTALL_DIR"

echo "Installing dependencies..."
apt install -y libstdc++6:amd64 zlib1g-dev:amd64 libncurses6:amd64 libcurl4:amd64

echo "Initialising Stata..."
cd "$INSTALL_DIR"
sudo ./stinit

echo "Done. Run Stata with: $INSTALL_DIR/stata-se"