'use strict';

/**
 * Generates build/icon.png (256x256) and build/icon.ico for the app + installer.
 * Pure-JS via Jimp; the .ico embeds the PNG (Vista+ PNG-in-ICO format).
 * Run: node build/make-icon.js
 */
const fs = require('fs');
const path = require('path');
const Jimp = require('jimp');
const _pti = require('png-to-ico');
const pngToIco = typeof _pti === 'function' ? _pti : _pti.default;

const SIZE = 256;
const RADIUS = 56;

function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
const A = hexToRgb('#7c5cff');   // accent
const B = hexToRgb('#4dd0e1');   // cyan
const C = hexToRgb('#ff6bce');   // pink highlight

function lerp(a, b, t) { return Math.round(a + (b - a) * t); }

async function main() {
  const img = new Jimp(SIZE, SIZE, 0x00000000);

  const cxOrb = SIZE * 0.62;
  const cyOrb = SIZE * 0.40;
  const orbR = SIZE * 0.30;

  img.scan(0, 0, SIZE, SIZE, function (x, y, idx) {
    // Rounded-corner mask
    const inCornerX = x < RADIUS ? RADIUS - x : (x > SIZE - RADIUS ? x - (SIZE - RADIUS) : 0);
    const inCornerY = y < RADIUS ? RADIUS - y : (y > SIZE - RADIUS ? y - (SIZE - RADIUS) : 0);
    let alpha = 255;
    if (inCornerX > 0 && inCornerY > 0) {
      const d = Math.sqrt(inCornerX * inCornerX + inCornerY * inCornerY);
      if (d > RADIUS) alpha = 0;
      else if (d > RADIUS - 1.5) alpha = Math.round(255 * (RADIUS - d) / 1.5);
    }

    // Diagonal gradient accent -> cyan, with a pink wash near the orb
    const t = (x + y) / (SIZE * 2);
    let r = lerp(A.r, B.r, t);
    let g = lerp(A.g, B.g, t);
    let b = lerp(A.b, B.b, t);

    // Glossy orb highlight (radial)
    const od = Math.sqrt((x - cxOrb) ** 2 + (y - cyOrb) ** 2);
    if (od < orbR) {
      const k = 1 - od / orbR;
      const gloss = Math.pow(k, 1.6);
      r = lerp(r, 255, gloss * 0.85);
      g = lerp(g, 255, gloss * 0.85);
      b = lerp(b, 255, gloss * 0.9);
      r = lerp(r, C.r, gloss * 0.10);
    }

    this.bitmap.data[idx] = r;
    this.bitmap.data[idx + 1] = g;
    this.bitmap.data[idx + 2] = b;
    this.bitmap.data[idx + 3] = alpha;
  });

  const pngPath = path.join(__dirname, 'icon.png');
  await img.writeAsync(pngPath);

  // Build a proper multi-resolution .ico (16..256) that rcedit + NSIS accept.
  const sizes = [16, 24, 32, 48, 64, 128, 256];
  const buffers = await Promise.all(sizes.map(async (s) => {
    const c = img.clone().resize(s, s);
    return c.getBufferAsync(Jimp.MIME_PNG);
  }));
  const ico = await pngToIco(buffers);
  fs.writeFileSync(path.join(__dirname, 'icon.ico'), ico);

  console.log(`icon.png + multi-size icon.ico written (${(ico.length / 1024 | 0)} KB ico)`);
}

main().catch((e) => { console.error(e); process.exit(1); });
