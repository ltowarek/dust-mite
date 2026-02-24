#!/bin/bash

set -e

LOGO_PATH="$1"
IMAGE_PATH="$2"
TMP_PATH="/tmp/$(basename "$IMAGE_PATH")"

# Compute relative overlay geometry so logo size and margins stay visually consistent
# across different image resolutions (logo width = 18% of image width, margins = 2%).
IMAGE_WIDTH="$(identify -format "%w" "$IMAGE_PATH")"
IMAGE_HEIGHT="$(identify -format "%h" "$IMAGE_PATH")"
LOGO_WIDTH="$(( IMAGE_WIDTH * 18 / 100 ))"
MARGIN_X="$(( IMAGE_WIDTH * 2 / 100 ))"
MARGIN_Y="$(( IMAGE_HEIGHT * 2 / 100 ))"

rm -f "$TMP_PATH"

convert "$IMAGE_PATH" \( -background none "$LOGO_PATH" -resize "${LOGO_WIDTH}x" \) -gravity northeast -geometry +"${MARGIN_X}"+"${MARGIN_Y}" -composite "$TMP_PATH"
mv "$TMP_PATH" "$IMAGE_PATH"
