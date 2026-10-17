import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { translations } from "../i18n";
import api, { setCurrencyContext, FX_FALLBACK_RATE } from "../lib/api";

const LangContext = createContext(null);

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => localStorage.getItem("lang") || "EN");

  const setLang = useCallback((l) => {
    localStorage.setItem("lang", l);
    setLangState(l);
  }, []);

  // USD -> IDR rate for the Indonesian view (cached locally so the first paint is already right)
  const [fx, setFx] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("fx_rate"));
      if (saved && saved.rate > 0) return saved;
    } catch { /* ignore */ }
    return { rate: FX_FALLBACK_RATE, as_of: null, source: "fallback" };
  });

  useEffect(() => {
    api.get("/fx")
      .then((r) => {
        if (r.data && r.data.rate > 0) {
          setFx(r.data);
          try { localStorage.setItem("fx_rate", JSON.stringify(r.data)); } catch { /* ignore */ }
        }
      })
      .catch(() => { /* keep the cached / fallback rate */ });
  }, []);

  // Set synchronously so every fmtCurrency call during this render uses the right currency
  setCurrencyContext(lang, fx.rate);

  const t = useCallback(
    (key) => translations[lang]?.[key] ?? translations["EN"][key] ?? key,
    [lang]
  );

  return (
    <LangContext.Provider value={{ lang, setLang, t, fx }}>
      {children}
    </LangContext.Provider>
  );
}

export function useLang() {
  return useContext(LangContext);
}
