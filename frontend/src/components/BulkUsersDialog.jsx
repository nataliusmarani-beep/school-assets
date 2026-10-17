import { useRef, useState } from "react";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { CheckCircle2, XCircle, Download, FileText } from "lucide-react";

const dl = (blob, name) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
};

export default function BulkUsersDialog({ onClose, onImported }) {
  const { t } = useLang();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [step, setStep] = useState("upload"); // upload | preview | done
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [invite, setInvite] = useState(true);

  const send = async (dry) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post(`/users/import?dry_run=${dry}&send_invite=${invite}`, fd, { headers: { "Content-Type": "multipart/form-data" } });
  };

  const doPreview = async () => {
    if (!file) return setError(t("import_file_required"));
    setLoading(true); setError("");
    try { const r = await send(true); setPreview(r.data); setStep("preview"); }
    catch (e) { setError(formatErr(e)); }
    finally { setLoading(false); }
  };

  const doImport = async () => {
    setLoading(true); setError("");
    try { const r = await send(false); setResult(r.data); setStep("done"); onImported(); }
    catch (e) { setError(formatErr(e)); }
    finally { setLoading(false); }
  };

  const downloadTemplate = async () => {
    try { const r = await api.get("/users/import-template", { responseType: "blob" }); dl(r.data, "user-import-template.csv"); } catch (e) { setError(formatErr(e)); }
  };

  const downloadCredentials = () => {
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const rows = [["name", "email", "role", "password"], ...result.users.map((u) => [u.name, u.email, u.role, u.password])];
    dl(new Blob(["﻿" + rows.map((r) => r.map(esc).join(",")).join("\n")], { type: "text/csv" }), "new-user-credentials.csv");
  };

  const steps = [["upload", t("import_step_upload")], ["preview", t("import_step_preview")], ["done", t("import_step_done")]];
  const idx = steps.findIndex((s) => s[0] === step);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" data-testid="bulk-users-dialog">
      <div className="bg-white w-full max-w-4xl mx-4 shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <h2 className="font-display text-lg font-semibold text-slate-900">{t("bu_title")}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl leading-none" data-testid="bu-close">&times;</button>
        </div>
        <div className="flex items-center px-6 pt-4 pb-2 text-xs gap-3">
          {steps.map(([k, label], i) => (
            <span key={k} className={i === idx ? "font-semibold text-slate-900" : i < idx ? "text-emerald-600" : "text-slate-400"}>{i + 1}. {label}</span>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {step === "upload" && (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">{t("bu_hint")}</p>
              <button onClick={downloadTemplate} data-testid="bu-template"
                className="inline-flex items-center gap-2 text-sm text-blue-700 border border-blue-200 bg-blue-50 px-3 py-1.5">
                <Download className="w-3.5 h-3.5" strokeWidth={1.75} /> {t("import_download_template")}
              </button>
              <div onClick={() => fileRef.current?.click()}
                className="border-2 border-dashed border-slate-300 hover:border-slate-400 p-10 text-center cursor-pointer">
                <FileText className="w-8 h-8 text-slate-300 mx-auto mb-3" strokeWidth={1.25} />
                <div className="text-sm text-slate-600">{file ? file.name : t("import_drop_hint")}</div>
                <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" data-testid="bu-file"
                  onChange={(e) => { setFile(e.target.files[0] || null); setError(""); }} />
              </div>
              <label className="flex items-start gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={invite} onChange={(e) => setInvite(e.target.checked)} className="mt-1" data-testid="bu-invite" />
                <span>{t("bu_invite")}</span>
              </label>
              {error && <div className="text-sm text-red-600">{error}</div>}
              <div className="flex justify-end">
                <button onClick={doPreview} disabled={loading || !file} data-testid="bu-preview"
                  className="bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm px-4 py-2">
                  {loading ? t("loading") : t("import_preview_btn")}
                </button>
              </div>
            </div>
          )}

          {step === "preview" && preview && (
            <div className="space-y-4">
              <div className="flex items-center gap-4 text-sm">
                <span className="text-slate-600">{preview.total} {t("import_rows_found")}</span>
                <span className="flex items-center gap-1 text-emerald-700 font-medium"><CheckCircle2 className="w-3.5 h-3.5" /> {preview.valid} {t("import_valid")}</span>
                {preview.invalid > 0 && <span className="flex items-center gap-1 text-red-600 font-medium"><XCircle className="w-3.5 h-3.5" /> {preview.invalid} {t("import_invalid")}</span>}
              </div>
              <div className="border border-slate-200 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="bg-slate-50 border-b border-slate-200">
                    {["import_col_row", "col_name", "email", "role", "department", "col_campus", "supervisor_email", "import_col_errors"].map((k) => (
                      <th key={k} className="text-left label-mono py-2 px-3">{t(k)}</th>))}
                  </tr></thead>
                  <tbody>
                    {preview.preview.map((p) => (
                      <tr key={p.row} className={`border-b border-slate-100 ${p.errors.length ? "bg-red-50" : ""}`} data-testid="bu-row">
                        <td className="py-2 px-3 text-slate-500">{p.row}</td>
                        <td className="py-2 px-3 text-slate-800">{p.name || "—"}</td>
                        <td className="py-2 px-3 text-slate-700">{p.email || "—"}</td>
                        <td className="py-2 px-3">{p.role}</td>
                        <td className="py-2 px-3">{p.department || "—"}</td>
                        <td className="py-2 px-3">{p.campus || "—"}</td>
                        <td className="py-2 px-3">{p.supervisor || "—"}</td>
                        <td className="py-2 px-3">
                          {p.errors.length ? <ul className="list-disc list-inside">{p.errors.map((e, i) => <li key={i} className="text-red-600">{e}</li>)}</ul>
                            : <span className="text-emerald-600">✓</span>}
                        </td>
                      </tr>))}
                  </tbody>
                </table>
              </div>
              {preview.invalid > 0 && <div className="text-xs text-slate-500">{t("bu_skip_note")}</div>}
              {error && <div className="text-sm text-red-600">{error}</div>}
              <div className="flex justify-between">
                <button onClick={() => { setStep("upload"); setPreview(null); }} className="text-sm border border-slate-300 px-4 py-2">{t("back")}</button>
                <button onClick={doImport} disabled={loading || preview.valid === 0} data-testid="bu-import"
                  className="bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm px-4 py-2">
                  {loading ? t("loading") : t("bu_import_btn").replace("{n}", preview.valid)}
                </button>
              </div>
            </div>
          )}

          {step === "done" && result && (
            <div className="space-y-4" data-testid="bu-done">
              <div className="text-sm text-slate-800">
                <b>{result.created}</b> {t("bu_created")}{result.skipped > 0 && <>, <b>{result.skipped}</b> {t("bu_skipped")}</>}
                {result.invite_requested && (result.email_configured
                  ? <>. {t("bu_invited").replace("{n}", result.invited)}</>
                  : <>. <span className="text-amber-700">{t("bu_no_email")}</span></>)}
              </div>
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 px-3 py-2">{t("bu_pw_warning")}</div>
              <div className="border border-slate-200 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="bg-slate-50 border-b border-slate-200">
                    {["col_name", "email", "role", "password"].map((k) => <th key={k} className="text-left label-mono py-2 px-3">{t(k)}</th>)}
                  </tr></thead>
                  <tbody>
                    {result.users.map((u) => (
                      <tr key={u.id} className="border-b border-slate-100" data-testid="bu-cred-row">
                        <td className="py-2 px-3 text-slate-800">{u.name}</td>
                        <td className="py-2 px-3">{u.email}</td>
                        <td className="py-2 px-3">{u.role}</td>
                        <td className="py-2 px-3 font-mono">{u.password}{u.generated && <span className="ml-2 text-slate-400">({t("bu_auto")})</span>}</td>
                      </tr>))}
                  </tbody>
                </table>
              </div>
              <div className="flex justify-between">
                <button onClick={downloadCredentials} data-testid="bu-download"
                  className="inline-flex items-center gap-2 text-sm text-blue-700 border border-blue-200 bg-blue-50 px-3 py-1.5">
                  <Download className="w-3.5 h-3.5" /> {t("bu_download")}
                </button>
                <button onClick={onClose} className="bg-slate-900 text-white text-sm px-4 py-2">{t("close")}</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
