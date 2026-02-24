#!/bin/bash

set -e

IMAGE_PATH="$1"
TARGET_WIDTH=1920
TARGET_HEIGHT=1440
JPEG_QUALITY=82
TMP_PATH="/tmp/$(basename "$IMAGE_PATH")"

rm -f "$TMP_PATH"

if [[ "$IMAGE_PATH" =~ \.png$ ]]; then
  # PNG files are typically UI screenshots: keep full content and only downscale when needed.
  RESIZE_OPTIONS=(
    -resize "${TARGET_WIDTH}x${TARGET_HEIGHT}>"
  )
  EXTENT_OPTIONS=()
  FORMAT_OPTIONS=(
    -define png:compression-level=9
    -define png:compression-strategy=1
  )
elif [[ "$IMAGE_PATH" =~ \.jpg$ ]]; then
  # JPG files are typically photos: fill target frame and center-crop to keep a consistent final size.
  RESIZE_OPTIONS=(
    -resize "${TARGET_WIDTH}x${TARGET_HEIGHT}^"
  )
  EXTENT_OPTIONS=(
    -gravity center
    -background white
    -extent "${TARGET_WIDTH}x${TARGET_HEIGHT}"
  )
  FORMAT_OPTIONS=(
    -sampling-factor 4:2:0
    -interlace Plane
    -quality "$JPEG_QUALITY"
  )
else
  echo "Unsupported file extension: $IMAGE_PATH"
  exit 1
fi

# Resize and optimize based on image format.
convert "$IMAGE_PATH" \
  -auto-orient \
  -strip \
  "${RESIZE_OPTIONS[@]}" \
  "${EXTENT_OPTIONS[@]}" \
  "${FORMAT_OPTIONS[@]}" \
  "$TMP_PATH"

mv "$TMP_PATH" "$IMAGE_PATH"
