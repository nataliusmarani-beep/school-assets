// The database stores campus as "YPJ TPRA"; people know it as "YPJ Tembagapura". Show the label, keep the stored value.
const LABELS = { "YPJ TPRA": "YPJ Tembagapura" };
export const campusLabel = (c) => LABELS[c] || c;
