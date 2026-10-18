import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, LogOut, CheckCircle2 } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { useLang } from "../../context/LangContext";
import api, { formatErr } from "../../lib/api";
import { POLICIES } from "../../pages/PoliciesPage";

const norm = (x) => (x || "").trim().replace(/\s+/g, " ").toLowerCase();

async function sha256(text) {
  try {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return "";
  }
}

/** Blocks the app until the user has read and e-signed the current policies. Cannot be dismissed. */
export default function PolicyAgreementModal() {
  const { user, setUser, logout } = useAuth();
  const { lang, setLang, t } = useLang();
  const boxRef = useRef(null);
  const [atEnd, setAtEnd] = useState(false);
  const [checks, setChecks] = useState({ read_all: false, will_comply: false, accept_sanctions: false });
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const checkEnd = () => {
    const el = boxRef.current;
    if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 24) setAtEnd(true);
  };
  useEffect(() => { checkEnd(); }, [lang]);
  // First-time users who never picked a language start in Indonesian (EN/ID toggle stays available).
  useEffect(() => {
    try { if (!localStorage.getItem("lang")) setLang("ID"); } catch { /* storage unavailable */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nameOk = norm(name) === norm(user?.name) && norm(name) !== "";
  const allChecked = checks.read_all && checks.will_comply && checks.accept_sanctions;
  const canSubmit = atEnd && allChecked && nameOk && !saving;

  const submit = async () => {
    setSaving(true);
    try {
      const text = POLICIES.flatMap((p) => [t(p.titleKey), ...p.sections.flatMap((s) => [t(s.headingKey), t(s.bodyKey)])]).join("\n");
      const res = await api.post("/policy/accept", {
        version: user.policy_version, signed_name: name.trim(), text_hash: await sha256(text), lang, ...checks,
      });
      setUser({ ...user, ...res.data });
      toast.success(t("polack_saved"));
    } catch (err) {
      toast.error(formatErr(err) || t("polack_failed"));
    } finally {
      setSaving(false);
    }
  };

  const checkItems = [["read_all", "polack_s1"], ["will_comply", "polack_s2"], ["accept_sanctions", "polack_s3"]];

  return (
    <div className="fixed inset-0 z-[100] bg-slate-900/80 flex items-center justify-center p-0 sm:p-4"
         role="dialog" aria-modal="true" aria-labelledby="polack-title" data-testid="policy-modal">
      <div className="bg-white w-full max-w-3xl h-full sm:h-auto sm:max-h-[94vh] flex flex-col shadow-2xl">
        <div className="p-5 sm:p-6 border-b border-slate-200 flex items-start gap-4">
          <div className="w-10 h-10 flex-shrink-0 bg-slate-900 text-amber-300 flex items-center justify-center">
            <ShieldCheck className="w-5 h-5" strokeWidth={1.5} />
          </div>
          <div className="flex-1 min-w-0">
            <h2 id="polack-title" className="font-display text-xl font-semibold text-slate-900">{t("polack_title")}</h2>
            <p className="text-sm text-slate-500 mt-1">{t("polack_intro")}</p>
          </div>
          <div className="flex gap-1 flex-shrink-0">
            {["EN", "ID"].map((l) => (
              <button key={l} onClick={() => setLang(l)}
                className={`px-2 py-1 text-xs font-mono border ${lang === l ? "bg-slate-900 text-white border-slate-900" : "border-slate-300 text-slate-600"}`}>
                {l}
              </button>
            ))}
          </div>
        </div>

        <div className="relative flex-1 min-h-[200px] flex flex-col bg-slate-50 overflow-hidden">
        {/* YPJ logo watermark, centred behind the scrolling policy text */}
        <img src={require("../../ypj-logo.png")} alt="" aria-hidden="true" draggable={false}
             className="absolute inset-0 m-auto w-64 h-64 sm:w-80 sm:h-80 object-contain opacity-[0.09] pointer-events-none select-none" />
        <div ref={boxRef} onScroll={checkEnd} tabIndex={0}
             className="relative flex-1 min-h-[200px] overflow-y-auto p-5 sm:p-6 space-y-8">
          {POLICIES.map((p) => {
            const Icon = p.icon;
            return (
              <section key={p.id}>
                <div className="flex items-center gap-3 mb-3">
                  <div className={`w-8 h-8 border flex items-center justify-center ${p.color}`}><Icon className="w-4 h-4" strokeWidth={1.5} /></div>
                  <h3 className="font-display text-base font-semibold text-slate-900">{t(p.titleKey)}</h3>
                </div>
                <div className="space-y-3 pl-0 sm:pl-11">
                  {p.sections.map((sec) => (
                    <div key={sec.headingKey}>
                      <h4 className="label-mono text-slate-700 mb-1">{t(sec.headingKey)}</h4>
                      {sec.list ? (
                        <ul className="space-y-1">
                          {t(sec.bodyKey).split("||").map((item, i) => (
                            <li key={i} className="flex gap-2 text-sm text-slate-600 leading-relaxed">
                              <span className={`mt-2 w-1.5 h-1.5 rounded-full flex-shrink-0 ${p.dot}`} /><span>{item.trim()}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-slate-600 leading-relaxed">{t(sec.bodyKey)}</p>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
        </div>

        <div className="p-5 sm:p-6 border-t border-slate-200 space-y-4 overflow-y-auto max-h-[55vh] sm:max-h-none">
          {!atEnd ? (
            <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 px-3 py-2">{t("polack_scroll_hint")}</p>
          ) : (
            <p className="text-sm text-emerald-700 flex items-center gap-2"><CheckCircle2 className="w-4 h-4" />{t("polack_scrolled")}</p>
          )}
          <fieldset disabled={!atEnd} className="space-y-3 disabled:opacity-50">
            <legend className="text-sm font-semibold text-slate-800 mb-1">{t("polack_summary_h")}</legend>
            {checkItems.map(([k, key]) => (
              <label key={k} className="flex items-start gap-3 text-sm text-slate-700 cursor-pointer">
                <input type="checkbox" className="mt-1 w-4 h-4 accent-slate-900" checked={checks[k]}
                  onChange={(e) => setChecks((c) => ({ ...c, [k]: e.target.checked }))} data-testid={`policy-check-${k}`} />
                <span>{t(key)}</span>
              </label>
            ))}
            <div>
              <label className="block text-sm font-medium text-slate-800 mb-1" htmlFor="polack-name">{t("polack_name_label")}</label>
              <input id="polack-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off"
                className="w-full border border-slate-300 px-3 py-2 text-sm font-display italic" data-testid="policy-sign-name" />
              <p className="text-xs text-slate-500 mt-1">{t("polack_name_hint")} <b>{user?.name}</b></p>
              {name && !nameOk && <p className="text-xs text-red-600 mt-1">{t("polack_name_mismatch")}</p>}
            </div>
          </fieldset>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <button onClick={async () => { await logout(); }} className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900">
              <LogOut className="w-4 h-4" strokeWidth={1.75} /> {t("sign_out")}
            </button>
            <button onClick={submit} disabled={!canSubmit} data-testid="policy-submit"
              className="bg-slate-900 text-white px-5 py-2.5 text-sm font-medium hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed">
              {saving ? t("polack_submitting") : t("polack_submit")}
            </button>
          </div>
          <p className="text-xs text-slate-400">{t("polack_footer")}</p>
        </div>
      </div>
    </div>
  );
}
