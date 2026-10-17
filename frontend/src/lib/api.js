import axios from "axios";

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API = `${BACKEND_URL}/api`;

const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;

export function formatErr(err) {
  const detail = err?.response?.data?.detail;
  if (!detail) return err?.message || "Something went wrong";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .join(" ");
  }
  return JSON.stringify(detail);
}

// ---- Currency ----
// Amounts are STORED IN RUPIAH (IDR). Indonesian (ID) shows them as they are; English (EN) shows
// USD, calculated from the stored Rupiah with the current USD->IDR rate (fetched from /api/fx).
export const FX_FALLBACK_RATE = 17950;
const fxState = { lang: "EN", rate: FX_FALLBACK_RATE };

export function setCurrencyContext(lang, rate) {
  fxState.lang = lang;
  if (rate > 0) fxState.rate = rate;
}

export const isRupiah = () => fxState.lang === "ID";

// v is an amount in IDR (as stored)
export function fmtCurrency(v) {
  const n = Number(v) || 0;
  if (isRupiah()) {
    return new Intl.NumberFormat("id-ID", {
      style: "currency",
      currency: "IDR",
      maximumFractionDigits: 0,
    }).format(n);
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n / fxState.rate);
}

// Short label for chart axes: Rp 1,2 M  /  $12k
export function fmtAxisCurrency(v) {
  const n = Number(v) || 0;
  if (isRupiah()) {
    const short = new Intl.NumberFormat("id-ID", { notation: "compact", maximumFractionDigits: 1 }).format(n);
    return `Rp ${short}`;
  }
  return `$${(n / fxState.rate / 1000).toFixed(0)}k`;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
