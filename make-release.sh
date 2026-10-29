#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Package the committed pipeline code into a dated zip file for sharing.
# Run from the python_code directory.
#
# Output: mp3transcription-pipeline-YYYY-MM-DD.zip
#         Written to the same directory as this script.
#
# Usage:
#   ./make-release.sh
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATE="$(date +%Y-%m-%d)"
OUTPUT="$SCRIPT_DIR/mp3transcription-pipeline-${DATE}.zip"

echo ""
echo "Building release from committed code..."
echo ""

git -C "$SCRIPT_DIR" archive --format=zip --output="$OUTPUT" HEAD

echo "Created: $OUTPUT"
echo ""
echo "Share this file with recipients. They should:"
echo "  1. Unzip it"
echo "  2. Run the pipeline once — it creates ~/Library/Application Support/SermonTranscriber"
echo "  3. Fill in their api_key, input_dir, and output_dir in config.txt there"
echo ""
