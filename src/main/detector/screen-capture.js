'use strict';

const { screen, Region } = require('@nut-tree-fork/nut-js');
const Jimp = require('jimp');

/**
 * Screen capture wrapper around nut-js.
 *
 * nut-js works in *logical* coordinates for the mouse and for Region, but
 * grabRegion() returns an image in *physical* pixels (DPI-scaled). We capture
 * a Region (full screen or a user-defined rectangle) and convert nut-js's raw
 * BGRA buffer into a Jimp image. The caller then derives a logical->physical
 * scale from (region.width / image.width) so click coordinates line up exactly
 * with what was seen, regardless of HiDPI / Retina scaling.
 */

/** Resolve the capture region (logical coords) from settings. */
async function resolveRegion(detection) {
  const r = detection.region || { mode: 'full' };
  if (r.mode === 'custom' && r.width > 0 && r.height > 0) {
    return new Region(r.x, r.y, r.width, r.height);
  }
  const w = await screen.width();
  const h = await screen.height();
  return new Region(0, 0, w, h);
}

/** Convert a nut-js Image (BGRA/BGR) into a Jimp image (RGBA). */
function nutImageToJimp(img) {
  const { width, height, data } = img;
  const channels = img.channels || (data.length / (width * height)) | 0;
  const out = Buffer.alloc(width * height * 4);
  const px = width * height;
  for (let i = 0; i < px; i++) {
    const s = i * channels;
    const d = i * 4;
    // nut-js default colour mode is BGR(A): swap B and R for Jimp's RGBA.
    out[d] = data[s + 2];                                  // R
    out[d + 1] = data[s + 1];                              // G
    out[d + 2] = data[s];                                  // B
    out[d + 3] = channels >= 4 ? data[s + 3] : 255;        // A
  }
  // eslint-disable-next-line no-bitwise
  return new Jimp({ data: out, width, height });
}

/**
 * Capture the configured region.
 * @returns {Promise<{jimp: Jimp, region: Region, scaleX: number, scaleY: number}>}
 */
async function capture(detection) {
  const region = await resolveRegion(detection);
  const nutImg = await screen.grabRegion(region);
  const jimp = nutImageToJimp(nutImg);
  const scaleX = region.width / jimp.bitmap.width;
  const scaleY = region.height / jimp.bitmap.height;
  return { jimp, region, scaleX, scaleY };
}

/** Encode a Jimp image to a PNG buffer for OCR. (getBufferAsync does not
 *  mutate the image, so no clone is needed — saves a full-frame copy per scan.) */
function toPngBuffer(jimp) {
  return jimp.getBufferAsync(Jimp.MIME_PNG);
}

/** Build a small base64 JPEG thumbnail for the live preview (kept cheap). */
async function toThumbnail(jimp, maxWidth = 380) {
  const clone = jimp.clone();
  if (clone.bitmap.width > maxWidth) {
    clone.resize(maxWidth, Jimp.AUTO);
  }
  clone.quality(58);
  return clone.getBase64Async(Jimp.MIME_JPEG);
}

module.exports = { capture, toPngBuffer, toThumbnail, resolveRegion };
