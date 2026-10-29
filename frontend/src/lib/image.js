// Shrink a camera photo before upload: loan photos are taken per unit, so full-size phone pictures add up fast.
export function compressImage(file, maxSide = 1280, quality = 0.8) {
  return new Promise((resolve) => {
    if (!file || !file.type.startsWith("image/")) return resolve(file);
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob(
        (blob) => resolve(blob ? new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file),
        "image/jpeg", quality,
      );
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}

// Loan condition photos are capped (50 KB): shrink step by step until the JPEG fits, or give up with null.
export const LOAN_PHOTO_MAX_BYTES = 50 * 1024;

export const ASSET_PHOTO_MAX_BYTES = 100 * 1024;

export async function compressToMaxBytes(file, maxBytes = LOAN_PHOTO_MAX_BYTES, sides = [960, 800, 640, 520, 420, 340, 280]) {
  if (!file || !file.type.startsWith("image/")) return null;
  const qualities = [0.7, 0.55, 0.42, 0.32];
  for (const side of sides) {
    for (const q of qualities) {
      const out = await compressImage(file, side, q);
      if (out && out.size <= maxBytes) return out;
    }
  }
  return null;
}
