import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ShieldCheck, CheckCircle2, Plus, Trash2 } from "lucide-react";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import SignaturePad from "../components/SignaturePad";

export const BYOD_STATEMENTS = ["own_device", "liability", "project_only", "rules", "monitoring", "revoke", "privacy"];
const emptyDevice = () => ({ kind: "laptop", brand: "", model: "", os: "", os_version: "", mac: "", serial: "" });
const INPUT = "w-full border border-slate-300 px-3 py-2 text-sm bg-white";
const LABEL = "block text-xs font-mono uppercase tracking-wide text-slate-500 mb-1";

async function sha256(text) {
  try {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch { return ""; }
}

/** Public page opened from the parent's one-time link: no account, no login. */
export default function ByodSignPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const { lang, setLang, t } = useLang();
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [parent, setParent] = useState({ name: "", relation: "" });
  const [devices, setDevices] = useState([emptyDevice()]);
  const [stmts, setStmts] = useState({});
  const [signature, setSignature] = useState("");

  // parents land here without having chosen a language: start in Indonesian
  useEffect(() => {
    try { if (!localStorage.getItem("lang")) setLang("ID"); } catch { /* storage unavailable */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!token) { setError("invalid"); return; }
    api.get(`/public/byod/${encodeURIComponent(token)}`)
      .then((r) => { setForm(r.data); setParent((p) => ({ name: r.data.parent_name || p.name, relation: r.data.parent_relation || p.relation })); })
      .catch(() => setError("invalid"));
  }, [token]);

  const allTicked = BYOD_STATEMENTS.every((k) => stmts[k]);
  const devicesOk = devices.every((d) => d.brand.trim() && d.model.trim() && d.mac.trim());
  const canSubmit = allTicked && devicesOk && parent.name.trim().length >= 3 && parent.relation.trim().length >= 2 && signature && !busy;
  const setDev = (i, patch) => setDevices((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));

  const submit = async () => {
    setBusy(true);
    try {
      const text = [t("byod_pub_title"), ...BYOD_STATEMENTS.map((k) => t(`byod_s_${k}`))].join("\n");
      await api.post(`/public/byod/${encodeURIComponent(token)}/sign`, {
        parent_name: parent.name.trim(), parent_relation: parent.relation.trim(), devices, statements: stmts,
        signature, text_hash: await sha256(text), lang,
      });
      setDone(true);
      window.scrollTo(0, 0);
    } catch (e) { toast.error(formatErr(e) || t("byod_pub_fix")); } finally { setBusy(false); }
  };

  const shell = (children) => (
    <div className="min-h-screen bg-slate-50 py-6 px-4" data-testid="byod-sign-page">
      <div className="relative max-w-2xl mx-auto bg-white border border-slate-200 shadow-sm">
        {/* YPJ logo watermark: stays centred in the viewport while the form scrolls */}
        <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
          <img src={require("../ypj-logo.png")} alt="" draggable={false}
               className="sticky top-[calc(50vh-9rem)] mx-auto w-64 h-64 sm:w-72 sm:h-72 object-contain opacity-[0.07] select-none" />
        </div>
        <div className="relative p-5 border-b border-slate-200 flex items-start gap-3">
          <div className="w-10 h-10 bg-slate-900 text-amber-300 flex items-center justify-center flex-shrink-0"><ShieldCheck className="w-5 h-5" strokeWidth={1.5} /></div>
          <div className="flex-1 min-w-0"><div className="text-xs font-mono uppercase tracking-wide text-slate-500">YPJ</div>
            <h1 className="font-display text-lg font-semibold text-slate-900 leading-snug">{t("byod_pub_title")}</h1></div>
          <div className="flex gap-1">{["EN", "ID"].map((l) => (
            <button key={l} onClick={() => setLang(l)} className={`px-2 py-1 text-xs font-mono border ${lang === l ? "bg-slate-900 text-white border-slate-900" : "border-slate-300 text-slate-600"}`}>{l}</button>))}</div>
        </div>
        <div className="relative p-5 space-y-6">{children}</div>
      </div>
    </div>
  );

  if (error) return shell(<p className="text-sm text-rose-700 bg-rose-50 border border-rose-200 p-4" data-testid="byod-invalid">{t("byod_pub_invalid")}</p>);
  if (!form) return shell(<p className="text-sm text-slate-500">…</p>);
  if (done) return shell(
    <div className="text-center py-8" data-testid="byod-done">
      <CheckCircle2 className="w-12 h-12 text-emerald-600 mx-auto" strokeWidth={1.5} />
      <h2 className="font-display text-xl font-semibold text-slate-900 mt-4">{t("byod_pub_done_title")}</h2>
      <p className="text-sm text-slate-600 mt-2">{t("byod_pub_done_body")}</p>
      <p className="font-mono text-xs text-slate-400 mt-4">{form.number}</p>
    </div>);

  const p = form.project;
  return shell(
    <>
      <p className="text-sm text-slate-600">{t("byod_pub_intro")}</p>
      <div className="border border-slate-200 bg-slate-50 p-4 text-sm grid grid-cols-3 gap-y-1.5 gap-x-3">
        <div className="text-slate-500">{t("byod_pub_student")}</div><div className="col-span-2 font-medium">{form.student_name}{form.student_class ? ` (${form.student_class})` : ""}</div>
        <div className="text-slate-500">{t("byod_pub_project")}</div><div className="col-span-2">{p.name}{p.subject ? ` · ${p.subject}` : ""}</div>
        <div className="text-slate-500">{t("byod_period")}</div><div className="col-span-2">{p.start_date} → {p.end_date}, {p.hour_from}–{p.hour_to}</div>
        <div className="text-slate-500">{t("byod_location")}</div><div className="col-span-2">{p.location || "—"}</div>
        <div className="text-slate-500">{t("byod_pub_teacher")}</div><div className="col-span-2">{form.teacher_name}</div>
      </div>

      <section>
        <h2 className="font-display text-base font-semibold text-slate-900 mb-3">{t("byod_pub_terms_h")}</h2>
        <div className="space-y-2.5">
          {BYOD_STATEMENTS.map((k) => (
            <label key={k} className="flex items-start gap-3 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" className="mt-1 w-4 h-4 accent-slate-900" checked={!!stmts[k]} onChange={(e) => setStmts((s) => ({ ...s, [k]: e.target.checked }))} data-testid={`byod-stmt-${k}`} />
              <span>{t(`byod_s_${k}`)}</span>
            </label>))}
        </div>
      </section>

      <section>
        <h2 className="font-display text-base font-semibold text-slate-900 mb-1">{t("byod_pub_devices_h")}</h2>
        <p className="text-xs text-slate-500 mb-3 bg-amber-50 border border-amber-200 p-3">{t("byod_pub_mac_help")}</p>
        {devices.map((d, i) => (
          <div key={i} className="border border-slate-200 p-4 mb-3 space-y-3" data-testid={`byod-device-${i}`}>
            <div className="flex items-center justify-between"><div className="text-sm font-medium">{t("byod_pub_device")} {i + 1}</div>
              {devices.length > 1 && <button onClick={() => setDevices((ds) => ds.filter((_, j) => j !== i))} className="text-xs text-rose-600 inline-flex items-center gap-1"><Trash2 className="w-3.5 h-3.5" />{t("byod_remove")}</button>}</div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className={LABEL}>{t("byod_devices")}</label>
                <select className={INPUT} value={d.kind} onChange={(e) => setDev(i, { kind: e.target.value })} data-testid={`byod-kind-${i}`}>
                  {form.device_kinds.map((k) => <option key={k} value={k}>{t(`byod_kind_${k}`)}</option>)}</select></div>
              <div><label className={LABEL}>{t("byod_brand")} *</label><input className={INPUT} value={d.brand} onChange={(e) => setDev(i, { brand: e.target.value })} data-testid={`byod-brand-${i}`} /></div>
              <div><label className={LABEL}>{t("byod_model")} *</label><input className={INPUT} value={d.model} onChange={(e) => setDev(i, { model: e.target.value })} data-testid={`byod-model-${i}`} /></div>
              <div><label className={LABEL}>{t("byod_os")}</label><input className={INPUT} value={d.os} onChange={(e) => setDev(i, { os: e.target.value })} /></div>
              <div><label className={LABEL}>{t("byod_os_version")}</label><input className={INPUT} value={d.os_version} onChange={(e) => setDev(i, { os_version: e.target.value })} /></div>
              <div><label className={LABEL}>{t("byod_serial")}</label><input className={INPUT} value={d.serial} onChange={(e) => setDev(i, { serial: e.target.value })} /></div>
            </div>
            <div><label className={LABEL}>{t("byod_mac")} *</label><input className={`${INPUT} font-mono`} placeholder="A1:B2:C3:D4:E5:F6" value={d.mac} onChange={(e) => setDev(i, { mac: e.target.value })} data-testid={`byod-mac-${i}`} /></div>
          </div>))}
        {devices.length < form.max_devices && (
          <button onClick={() => setDevices((ds) => [...ds, emptyDevice()])} className="text-sm text-slate-700 inline-flex items-center gap-1 border border-slate-300 px-3 py-1.5"><Plus className="w-4 h-4" />{t("byod_pub_add_device")}</button>)}
      </section>

      <section className="space-y-3">
        <h2 className="font-display text-base font-semibold text-slate-900">{t("byod_pub_parent_h")}</h2>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>{t("byod_parent_name")} *</label><input className={INPUT} value={parent.name} onChange={(e) => setParent({ ...parent, name: e.target.value })} data-testid="byod-parent-name" /></div>
          <div><label className={LABEL}>{t("byod_relation")} *</label><input className={INPUT} value={parent.relation} onChange={(e) => setParent({ ...parent, relation: e.target.value })} data-testid="byod-parent-relation" /></div>
        </div>
        <div><label className={LABEL}>{t("byod_pub_signature")} *</label><SignaturePad onChange={setSignature} clearLabel={t("byod_clear")} /></div>
      </section>

      <button onClick={submit} disabled={!canSubmit} data-testid="byod-submit"
        className="w-full bg-slate-900 text-white py-3 text-sm font-medium hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed">
        {busy ? "…" : t("byod_pub_submit")}
      </button>
      {!canSubmit && <p className="text-xs text-slate-400 text-center">{t("byod_pub_fix")}</p>}
    </>
  );
}
