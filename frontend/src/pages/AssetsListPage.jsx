import { Fragment, useEffect, useRef, useState } from "react";
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
import { Search, Plus, Filter, Upload, Download, CheckCircle2, XCircle, FileText, FileSpreadsheet, ChevronRight, ChevronDown } from "lucide-react";
import { isManagerRole, isCampusBound } from "../lib/roles";
import { ownerName } from "../lib/format";
import BulkTransferDialog from "../components/assets/BulkTransferDialog";
import { campusLabel } from "../lib/campus";

const CAMPUSES = ["YPJ Kuala Kencana", "YPJ TPRA"];

const CAMPUS_DOT = {
  "YPJ Kuala Kencana": "bg-amber-400",
  "YPJ TPRA": "bg-blue-500",
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
                        <td className="py-2 px-3 text-slate-700">{campusLabel(row.campus) || "—"}</td>
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
                {result.pending_confirmation > 0 && (
                  <div className="text-xs text-slate-500 mt-2">{t("import_pending_note").replace("{n}", result.pending_confirmation)}</div>
                )}
                {result.owner_ignored?.length > 0 && (
                  <div className="text-xs text-amber-700 mt-2" data-testid="import-owner-ignored">
                    {t("import_owner_ignored").replace("{n}", result.owner_ignored.length)}
                  </div>
                )}
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
  const isAdmin = isManagerRole(user?.role);
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [campus, setCampus] = useState("all");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");
  const [showImport, setShowImport] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [showBulk, setShowBulk] = useState(false);

  const doExport = async () => {
    setExporting(true);
    try {
      const params = {};
      if (search) params.search = search;
      if (campus !== "all") params.campus = campus;
      if (category !== "all") params.category = category;
      if (status !== "all") params.status = status;
      const res = await api.get("/assets/export", { params, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      a.download = `assets-export-${today}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Export failed", e);
    } finally {
      setExporting(false);
    }
  };

  const selectable = assets.filter((a) => !a.pending_assignment);

  // Accordion: assets grouped by category, each group collapsible with its asset count.
  // Groups stay collapsed by default; searching or filtering opens them so the matches are visible.
  const [openCats, setOpenCats] = useState(new Set());
  const filtering = !!search || category !== "all" || campus !== "all" || status !== "all";
  const catLabel = (c) => { const i = CATEGORY_VALUES.indexOf(c); return i >= 0 ? t(CATEGORY_KEYS[i]) : (c || "—"); };
  const groups = (() => {
    const by = new Map();
    assets.forEach((a) => { const k = a.category || ""; if (!by.has(k)) by.set(k, []); by.get(k).push(a); });
    const order = (k) => { const i = CATEGORY_VALUES.indexOf(k); return i < 0 ? 999 : i; };
    return [...by.entries()].sort((x, y) => order(x[0]) - order(y[0])).map(([key, items]) => ({ key, items }));
  })();
  const isOpen = (key) => filtering || openCats.has(key);
  const toggleCat = (key) => setOpenCats((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const allOpen = groups.length > 0 && groups.every((g) => openCats.has(g.key));

  const load = () => {
    setLoading(true);
    const params = {};
    if (search) params.search = search;
    if (campus !== "all") params.campus = campus;
    if (category !== "all") params.category = category;
    if (status !== "all") params.status = status;
    api.get("/assets", { params })
      .then((r) => { setAssets(r.data); setSelected((s) => new Set([...s].filter((id) => r.data.some((a) => a.id === id)))); })
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
        <div className="flex items-center gap-2">
          <button
            onClick={doExport}
            disabled={exporting}
            className="inline-flex items-center gap-2 border border-slate-300 hover:border-slate-500 text-slate-700 hover:text-slate-900 disabled:opacity-50 text-sm px-4 py-2.5"
          >
            <FileSpreadsheet className="w-4 h-4" strokeWidth={1.75} />
            {exporting ? t("exporting") : t("export_excel")}
          </button>
          {(isAdmin || isCampusBound(user?.role)) && (
            <>
              {isAdmin && (
              <button
                onClick={() => setShowImport(true)}
                className="inline-flex items-center gap-2 border border-slate-300 hover:border-slate-500 text-slate-700 hover:text-slate-900 text-sm px-4 py-2.5"
              >
                <Upload className="w-4 h-4" strokeWidth={1.75} /> {t("import_assets")}
              </button>
              )}
              <Link
                to="/assets/new"
                data-testid="add-asset-button"
                className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white text-sm px-4 py-2.5"
              >
                <Plus className="w-4 h-4" strokeWidth={1.75} /> {t("add_asset")}
              </Link>
            </>
          )}
        </div>
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
                    {campusLabel(c)}
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

      {isAdmin && selected.size > 0 && (
        <div className="mb-3 flex items-center gap-4 bg-blue-50 border border-blue-200 px-4 py-2.5 text-sm" data-testid="bulk-transfer-bar">
          <span className="font-medium text-blue-900">{t("bt_selected").replace("{n}", selected.size)}</span>
          <button onClick={() => setShowBulk(true)} className="bg-blue-800 hover:bg-blue-900 text-white px-3 py-1.5" data-testid="bulk-transfer-button">{t("bt_transfer")}</button>
          <button onClick={() => setSelected(new Set())} className="text-slate-600 hover:text-slate-900" data-testid="bulk-clear">{t("bt_clear")}</button>
        </div>
      )}

      {groups.length > 1 && (
        <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
          <span>{groups.length} {t("asset_categories")}</span>
          <button type="button" className="text-blue-800 hover:underline disabled:opacity-40" disabled={filtering}
            onClick={() => setOpenCats(allOpen ? new Set() : new Set(groups.map((g) => g.key)))} data-testid="toggle-all-groups">
            {allOpen || filtering ? t("collapse_all") : t("expand_all")}
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="assets-table">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                {isAdmin && (
                  <th className="py-3 px-4 w-8">
                    <input type="checkbox" data-testid="select-all-assets"
                      checked={selectable.length > 0 && selectable.every((a) => selected.has(a.id))}
                      onChange={(e) => setSelected(e.target.checked ? new Set(selectable.map((a) => a.id)) : new Set())} />
                  </th>
                )}
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
                <tr><td colSpan={isAdmin ? 9 : 8} className="text-center text-slate-500 py-12">{t("loading")}</td></tr>
              ) : assets.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 9 : 8} className="text-center text-slate-500 py-16">
                    <div className="font-display text-lg text-slate-700 mb-1">{t("no_assets")}</div>
                    <div className="text-xs">{t("no_assets_sub")}</div>
                  </td>
                </tr>
              ) : groups.map((g) => {
                const open = isOpen(g.key);
                const sel = g.items.filter((a) => !a.pending_assignment);
                return (
                  <Fragment key={g.key || "none"}>
                    <tr className="bg-slate-50 border-b border-slate-200 cursor-pointer select-none hover:bg-slate-100"
                        onClick={() => toggleCat(g.key)} data-testid={`asset-group-${g.key}`}>
                      <td colSpan={isAdmin ? 9 : 8} className="py-2.5 px-4">
                        <div className="flex items-center gap-3">
                          {isAdmin && (
                            <input type="checkbox" onClick={(e) => e.stopPropagation()}
                              checked={sel.length > 0 && sel.every((a) => selected.has(a.id))}
                              onChange={(e) => setSelected((s0) => { const n = new Set(s0); sel.forEach((a) => e.target.checked ? n.add(a.id) : n.delete(a.id)); return n; })} />
                          )}
                          {open ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                          <span className="font-medium text-slate-900">{catLabel(g.key)}</span>
                          <span className="text-xs text-slate-600 bg-white border border-slate-200 px-2 py-0.5">{g.items.length} {g.items.length !== 1 ? t("count_assets") : t("count_asset")}</span>
                        </div>
                      </td>
                    </tr>
                    {open && g.items.map((a) => {
                const cls = STATUS_CLS[a.status] || STATUS_CLS.active;
                    const dot = CAMPUS_DOT[a.campus];
                    return (
                      <tr key={a.id} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" data-testid={`asset-row-${a.id}`}>
                        {isAdmin && (
                          <td className="py-3 px-4" onClick={(e) => e.stopPropagation()}>
                            <input type="checkbox" data-testid={`asset-select-${a.id}`} checked={selected.has(a.id)} disabled={!!a.pending_assignment}
                              title={a.pending_assignment ? t("pending_banner").replace("{name}", a.pending_assignment.to_name) : undefined}
                              onChange={() => setSelected((s) => { const n = new Set(s); n.has(a.id) ? n.delete(a.id) : n.add(a.id); return n; })} />
                          </td>
                        )}
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
                              {campusLabel(a.campus)}
                            </span>
                          ) : "—"}
                        </td>
                        <td className="py-3 px-4 text-slate-700">{a.location}</td>
                        <td className="py-3 px-4 text-slate-700">
                          {ownerName(a.assigned_to_name) || "—"}
                          {a.handover_flag === "discrepancy" && (
                            <div className="mt-1"><span className="inline-flex items-center px-2 py-0.5 text-xs border bg-rose-50 text-rose-700 border-rose-200">{t("cr_discrepancy")}</span></div>
                          )}
                          {a.pending_assignment && (
                            <div className="mt-1" data-testid={`awaiting-${a.id}`}>
                              <span className="inline-flex items-center px-2 py-0.5 text-xs border bg-amber-50 text-amber-800 border-amber-300"
                                title={t("pending_banner").replace("{name}", a.pending_assignment.to_name)}>
                                {t("awaiting_confirmation")} · {ownerName(a.pending_assignment.to_name)}
                              </span>
                            </div>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <span className={`inline-flex items-center px-2 py-0.5 text-xs border ${cls}`}>
                            {t(STATUS_KEYS[a.status] || "status_active")}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-slate-700 text-sm">{a.asset_type || "—"}</td>
                      </tr>
                    );
                        })}
                  </Fragment>
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

      {isAdmin && (
        <BulkTransferDialog open={showBulk} onOpenChange={setShowBulk} t={t}
          assets={assets.filter((a) => selected.has(a.id))}
          onDone={() => { setSelected(new Set()); load(); }} />
      )}

      {showImport && (
        <ImportModal
          onClose={() => setShowImport(false)}
          onImported={() => { load(); }}
        />
      )}
    </div>
  );
}
