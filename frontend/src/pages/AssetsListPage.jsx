import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtCurrency, fmtDate } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { CATEGORY_VALUES, CATEGORY_KEYS, STATUS_KEYS } from "../i18n";
import { Input } from "../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Search, Plus, Filter, Upload, Download, CheckCircle2, XCircle, FileText } from "lucide-react";

const CAMPUSES = ["YPJ Kuala Kencana", "YPJ Tembagapura"];

const CAMPUS_DOT = {
  "YPJ Kuala Kencana": "bg-amber-400",
  "YPJ Tembagapura": "bg-blue-500",
};

const STATUS_CLS = {
  active: "bg-blue-50 text-blue-800 border-blue-200",
  in_repair: "bg-amber-50 text-amber-700 border-amber-200",
  retired: "bg-slate-100 text-slate-600 border-slate-200",
  lost: "bg-rose-50 text-rose-700 border-rose-200",
};

// ---- Import Modal ----
function ImportModal({ onClose, onImported }) {
  const { t } = useLang();
  const fileRef = useRef(null);
  const [step, setStep] = useState("upload"); // upload | preview | done
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(null); // { total, valid, invalid, preview[] }
  const [result, setResult] = useState(null);   // { imported, skipped }

  const pickFile = (f) => {
    if (!f) return;
    setFile(f);
    setError("");
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  };

  const doPreview = async () => {
    if (!file) { setError(t("import_file_required")); return; }
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post("/assets/import?dry_run=true", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(res.data);
      setStep("preview");
    } catch (e) {
      setError(e.response?.data?.detail || "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const doImport = async () => {
    if (!preview || preview.valid === 0) { setError(t("import_no_valid")); return; }
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post("/assets/import?dry_run=false", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
      setStep("done");
      onImported();
    } catch (e) {
      setError(e.response?.data?.detail || "Import failed");
    } finally {
      setLoading(false);
    }
  };

  const downloadTemplate = async () => {
    try {
      const res = await api.get("/assets/import-template", { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "asset-import-template.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {}
  };

  // Step indicators
  const steps = [
    { key: "upload",  label: t("import_step_upload") },
    { key: "preview", label: t("import_step_preview") },
    { key: "done",    label: t("import_step_done") },
  ];
  const stepIdx = steps.findIndex((s) => s.key === step);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white w-full max-w-3xl mx-4 shadow-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <h2 className="font-display text-lg font-semibold text-slate-900">
            {t("import_modal_title")}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl leading-none">&times;</button>
        </div>

        {/* Step bar */}
        <div className="flex items-center gap-0 px-6 pt-4 pb-2">
          {steps.map((s, i) => (
            <div key={s.key} className="flex items-center">
              <div className={`flex items-center gap-1.5 text-xs font-medium px-2 py-1 ${
                i === stepIdx ? "text-slate-900" : i < stepIdx ? "text-emerald-600" : "text-slate-400"
              }`}>
                {i < stepIdx ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                ) : (
                  <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] border ${
                    i === stepIdx ? "border-slate-700 bg-slate-900 text-white" : "border-slate-300 text-slate-400"
                  }`}>{i + 1}</span>
                )}
                {s.label}
              </div>
              {i < steps.length - 1 && <div className="w-6 h-px bg-slate-200 mx-1" />}
            </div>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">

          {/* ---- Step 1: Upload ---- */}
          {step === "upload" && (
            <div className="space-y-4">
              <button
                onClick={downloadTemplate}
                className="inline-flex items-center gap-2 text-sm text-blue-700 hover:text-blue-900 border border-blue-200 bg-blue-50 px-3 py-1.5"
              >
                <Download className="w-3.5 h-3.5" strokeWidth={1.75} />
                {t("import_download_template")}
              </button>

              {/* Drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileRef.current?.click()}
                className={`border-2 border-dashed rounded-none p-10 text-center cursor-pointer transition-colors ${
                  dragOver ? "border-slate-500 bg-slate-50" : "border-slate-300 hover:border-slate-400"
                }`}
              >
                <FileText className="w-8 h-8 text-slate-300 mx-auto mb-3" strokeWidth={1.25} />
                {file ? (
                  <div>
                    <div className="font-medium text-slate-800 text-sm">{file.name}</div>
                    <div className="text-xs text-slate-500 mt-0.5">{t("import_file_selected")}</div>
                  </div>
                ) : (
                  <div className="text-sm text-slate-500">{t("import_drop_hint")}</div>
                )}
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden"
                  onChange={(e) => pickFile(e.target.files[0])}
                />
              </div>

              {error && <div className="text-sm text-red-600">{error}</div>}

              <div className="flex justify-end">
                <button
                  onClick={doPreview}
                  disabled={loading || !file}
                  className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm px-4 py-2"
                >
                  {loading ? t("loading") : t("import_preview_btn")}
                </button>
              </div>
            </div>
          )}

          {/* ---- Step 2: Preview ---- */}
          {step === "preview" && preview && (
            <div className="space-y-4">
              {/* Summary */}
              <div className="flex items-center gap-4 text-sm">
                <span className="text-slate-600">{preview.total} {t("import_rows_found")}</span>
                <span className="flex items-center gap-1 text-emerald-700 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5" /> {preview.valid} {t("import_valid")}
                </span>
                {preview.invalid > 0 && (
                  <span className="flex items-center gap-1 text-red-600 font-medium">
                    <XCircle className="w-3.5 h-3.5" /> {preview.invalid} {t("import_invalid")}
                  </span>
                )}
              </div>

              {/* Table */}
              <div className="border border-slate-200 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200">
                      <th className="text-left label-mono py-2 px-3">{t("import_col_row")}</th>
                      <th className="text-left label-mono py-2 px-3">{t("import_col_name")}</th>
                      <th className="text-left label-mono py-2 px-3">{t("import_col_tag")}</th>
                      <th className="text-left label-mono py-2 px-3">{t("import_col_category")}</th>
                      <th className="text-left label-mono py-2 px-3">{t("import_col_campus")}</th>
                      <th className="text-left label-mono py-2 px-3">{t("import_col_status")}</th>
                      <th className="text-left label-mono py-2 px-3">{t("import_col_errors")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview.map((row) => (
                      <tr
                        key={row.row}
                        className={`border-b border-slate-100 ${row.errors.length > 0 ? "bg-red-50" : ""}`}
                      >
                        <td className="py-2 px-3 text-slate-500">{row.row}</td>
                        <td className="py-2 px-3 text-slate-800">{row.name || "—"}</td>
                        <td className="py-2 px-3 font-mono text-slate-600">{row.asset_tag || "—"}</td>
                        <td className="py-2 px-3 text-slate-700">{row.category || "—"}</td>
                        <td className="py-2 px-3 text-slate-700">{row.campus || "—"}</td>
                        <td className="py-2 px-3 text-slate-700">{row.status || "—"}</td>
                        <td className="py-2 px-3">
                          {row.errors.length > 0 ? (
                            <ul className="list-disc list-inside space-y-0.5">
                              {row.errors.map((e, i) => (
                                <li key={i} className="text-red-600">{e}</li>
                              ))}
                            </ul>
                          ) : (
                            <span className="text-emerald-600">✓</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {error && <div className="text-sm text-red-600">{error}</div>}

              <div className="flex items-center justify-between">
                <button
                  onClick={() => { setStep("upload"); setError(""); }}
                  className="text-sm text-slate-500 hover:text-slate-800 border border-slate-300 px-4 py-2"
                >
                  {t("back")}
                </button>
                <button
                  onClick={doImport}
                  disabled={loading || preview.valid === 0}
                  className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm px-4 py-2"
                >
                  <Upload className="w-3.5 h-3.5" strokeWidth={1.75} />
                  {loading ? t("import_importing") : `${t("import_confirm_btn")} (${preview.valid})`}
                </button>
              </div>
            </div>
          )}

          {/* ---- Step 3: Done ---- */}
          {step === "done" && result && (
            <div className="py-8 text-center space-y-4">
              <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto" strokeWidth={1.25} />
              <div>
                <div className="font-display text-xl font-semibold text-slate-900 mb-1">
                  {t("import_done_title")}
                </div>
                <div className="text-sm text-slate-600">
                  {t("import_done_msg")
                    .replace("{{imported}}", result.imported)
                    .replace("{{skipped}}", result.skipped)}
                </div>
              </div>
              <button
                onClick={onClose}
                className="inline-flex items-center bg-slate-900 hover:bg-slate-800 text-white text-sm px-6 py-2.5"
              >
                {t("import_done_close")}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Main page ----
export default function AssetsListPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [campus, setCampus] = useState("all");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");
  const [showImport, setShowImport] = useState(false);

  const load = () => {
    setLoading(true);
    const params = {};
    if (search) params.search = search;
    if (campus !== "all") params.campus = campus;
    if (category !== "all") params.category = category;
    if (status !== "all") params.status = status;
    api.get("/assets", { params })
      .then((r) => setAssets(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
    /* eslint-disable-next-line */
  }, [search, campus, category, status]);

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="assets-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="label-mono mb-2">{t("inventory")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            {t("assets")}
          </h1>
        </div>
        {isAdmin && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowImport(true)}
              className="inline-flex items-center gap-2 border border-slate-300 hover:border-slate-500 text-slate-700 hover:text-slate-900 text-sm px-4 py-2.5"
            >
              <Upload className="w-4 h-4" strokeWidth={1.75} /> {t("import_assets")}
            </button>
            <Link
              to="/assets/new"
              data-testid="add-asset-button"
              className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white text-sm px-4 py-2.5"
            >
              <Plus className="w-4 h-4" strokeWidth={1.75} /> {t("add_asset")}
            </Link>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="bg-white border border-slate-200 p-4 mb-6 grid grid-cols-1 md:grid-cols-12 gap-3">
        <div className="md:col-span-4 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" strokeWidth={1.75} />
          <Input
            placeholder={t("search_placeholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 rounded-none border-slate-300"
            data-testid="asset-search-input"
          />
        </div>
        <div className="md:col-span-3">
          <Select value={campus} onValueChange={setCampus}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-campus">
              <SelectValue placeholder={t("all_campuses")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("all_campuses")}</SelectItem>
              {CAMPUSES.map((c) => (
                <SelectItem key={c} value={c}>
                  <span className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${CAMPUS_DOT[c] || "bg-slate-400"}`} />
                    {c}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-3">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-category">
              <Filter className="w-3.5 h-3.5 mr-2 text-slate-400" strokeWidth={1.75} />
              <SelectValue placeholder={t("all_categories")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("all_categories")}</SelectItem>
              {CATEGORY_VALUES.map((c, i) => (
                <SelectItem key={c} value={c}>{t(CATEGORY_KEYS[i])}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-status">
              <SelectValue placeholder={t("all_statuses")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("all_statuses")}</SelectItem>
              {Object.entries(STATUS_KEYS).map(([val, key]) => (
                <SelectItem key={val} value={val}>{t(key)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="assets-table">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_tag")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_asset")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_category")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_campus")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_room")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_assigned")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_status")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_asset_property_of")}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="text-center text-slate-500 py-12">{t("loading")}</td></tr>
              ) : assets.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center text-slate-500 py-16">
                    <div className="font-display text-lg text-slate-700 mb-1">{t("no_assets")}</div>
                    <div className="text-xs">{t("no_assets_sub")}</div>
                  </td>
                </tr>
              ) : assets.map((a) => {
                const cls = STATUS_CLS[a.status] || STATUS_CLS.active;
                const dot = CAMPUS_DOT[a.campus];
                return (
                  <tr key={a.id} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" data-testid={`asset-row-${a.id}`}>
                    <td className="py-3 px-4 font-mono text-xs text-slate-600">
                      <Link to={`/assets/${a.id}`} className="hover:text-blue-800">{a.asset_tag}</Link>
                    </td>
                    <td className="py-3 px-4">
                      <Link to={`/assets/${a.id}`} className="font-medium text-slate-900 hover:text-blue-800">{a.name}</Link>
                      <div className="text-xs text-slate-500 mt-0.5">{a.serial_number || "—"}</div>
                    </td>
                    <td className="py-3 px-4 text-slate-700">{a.category}</td>
                    <td className="py-3 px-4 text-slate-700">
                      {a.campus ? (
                        <span className="flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot || "bg-slate-400"}`} />
                          {a.campus}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="py-3 px-4 text-slate-700">{a.location}</td>
                    <td className="py-3 px-4 text-slate-700">{a.assigned_to_name || "—"}</td>
                    <td className="py-3 px-4">
                      <span className={`inline-flex items-center px-2 py-0.5 text-xs border ${cls}`}>
                        {t(STATUS_KEYS[a.status] || "status_active")}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-700 text-sm">{a.asset_type || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="text-xs text-slate-500 mt-3 flex items-center justify-between">
        <span>{assets.length} {assets.length !== 1 ? t("count_assets") : t("count_asset")}</span>
        <span>{t("last_refreshed")} {fmtDate(new Date().toISOString())}</span>
      </div>

      {showImport && (
        <ImportModal
          onClose={() => setShowImport(false)}
          onImported={() => { load(); }}
        />
      )}
    </div>
  );
}
