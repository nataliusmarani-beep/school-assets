import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Button } from "../components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Upload, X, FileText, ImageIcon, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { ICT_CATEGORIES } from "../lib/roles";
import { CATEGORY_VALUES, CATEGORY_KEYS } from "../i18n";
import { campusLabel } from "../lib/campus";

const CAMPUSES = ["YPJ Kuala Kencana", "YPJ TPRA"];

const UNIT_VALUES = ["paud", "sd", "smp", "admin", "shared"];
const CONDITION_VALUES = ["good", "fair", "poor", "damaged"];
const ACQ_VALUES = ["purchase", "donation", "transfer"];
const USER_TYPE_VALUES = ["employee", "shared", "classroom"];

const optionsFor = (prefix, values, t) =>
  values.map((v) => ({ value: v, label: t(`${prefix}_${v}`) }));

// Extended register fields (text unless noted)
const EXTRA_TEXT_KEYS = [
  "asset_code", "item_type", "brand", "model", "unit", "building", "department", "user_type",
  "acquisition_type", "po_number", "funding_source", "asset_condition", "condition_notes",
  "last_inspection_date", "next_inspection_date", "last_maintenance_date", "next_maintenance_date",
  "maintenance_provider", "maintenance_cost", "warranty_start_date", "warranty_provider", "residual_value",
];

const extrasFromAsset = (a) => {
  const out = { maintenance_required: !!a.maintenance_required };
  EXTRA_TEXT_KEYS.forEach((k) => { out[k] = a[k] == null ? "" : String(a[k]); });
  return out;
};

// Suggested useful life (years) per category - mirrors DEFAULT_USEFUL_LIFE in backend/server.py
const DEFAULT_USEFUL_LIFE = {
  "IT Equipment": 4, "AV Equipment": 5, "Furniture": 8, "Lab Equipment": 8, "Vehicles": 8,
  "Books": 5, "Sports": 5, "Music Equipment": 8, "Other": 5,
  "Learning Tools": 5, "ERG / Fire Drill Equipment": 5, "Housekeeping Equipment": 4, "First Aid / AED Equipment": 5, "Work Tools": 5,
};

const FIELD_CLS = "mt-2 rounded-none border-slate-300";

function TextField({ label, value, onChange, testid, mono, required, placeholder, type = "text", span2, step, min, hint }) {
  return (
    <div className={span2 ? "md:col-span-2" : ""}>
      <Label className="label-mono">{label}</Label>
      <Input type={type} step={step} min={min} value={value ?? ""} required={required}
        placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
        className={`${FIELD_CLS} ${mono ? "font-mono" : ""}`} data-testid={testid} />
      {hint && <p className="mt-1.5 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

// Money input. The form holds Rupiah (what the API stores). In ID the user types Rupiah directly;
// in EN the user types USD, which is converted to Rupiah with the current rate on the way in.
function MoneyField({ label, idr, onChangeIdr, required, testid, min, span2 }) {
  const { lang, fx } = useLang();
  const rupiah = lang === "ID";
  const toText = (v) => {
    if (v === "" || v == null || Number.isNaN(Number(v))) return "";
    const n = Number(v);
    return rupiah ? String(Math.round(n)) : String(Math.round((n / fx.rate) * 100) / 100);
  };
  const [text, setText] = useState(() => toText(idr));
  const last = useRef(idr);

  // value changed from outside (e.g. asset loaded for editing)
  useEffect(() => {
    if (idr !== last.current) { last.current = idr; setText(toText(idr)); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idr]);
  // language or rate changed -> show the same stored Rupiah amount in the other currency
  useEffect(() => {
    setText(toText(idr));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rupiah, fx.rate]);

  const onChange = (e) => {
    const v = e.target.value;
    setText(v);
    const n = parseFloat(v);
    const out = v === "" || Number.isNaN(n) ? "" : (rupiah ? n : Math.round(n * fx.rate));
    last.current = out;
    onChangeIdr(out);
  };

  return (
    <div className={span2 ? "md:col-span-2" : ""}>
      <Label className="label-mono">{label}</Label>
      <Input type="number" step={rupiah ? "1" : "0.01"} min={min} value={text} required={required}
        onChange={onChange} className={`${FIELD_CLS} font-mono`} data-testid={testid} />
    </div>
  );
}

function SelectField({ label, value, onChange, options, placeholder, testid }) {
  return (
    <div>
      <Label className="label-mono">{label}</Label>
      <Select value={value || ""} onValueChange={onChange}>
        <SelectTrigger className={FIELD_CLS} data-testid={testid}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (<SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="bg-white border border-slate-200 p-6">
      <div className="label-mono mb-5 text-blue-800">{title}</div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">{children}</div>
    </section>
  );
}

export default function AssetFormPage() {
  const { id } = useParams();
  const isEdit = !!id;
  const navigate = useNavigate();
  const { t } = useLang();
  const { user } = useAuth();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [photoUploading, setPhotoUploading] = useState(false);
  const [pdfUploading, setPdfUploading] = useState(false);
  const [photoPreview, setPhotoPreview] = useState(null);
  // Once the user types a useful life themselves, changing the category no longer overrides it
  const lifeTouched = useRef(false);

  const [form, setForm] = useState({
    name: "", asset_tag: "", category: user?.role === "admin" ? "Furniture" : "IT Equipment", asset_type: "School Asset", description: "",
    campus: "", location: "", status: "active", purchase_price: "",
    purchase_date: new Date().toISOString().split("T")[0],
    useful_life_years: DEFAULT_USEFUL_LIFE[user?.role === "admin" ? "Furniture" : "IT Equipment"], warranty_end_date: "", serial_number: "",
    supplier: "", assigned_to_name: "", assigned_to_user_id: null, photo_path: null, documents: [],
    ...extrasFromAsset({}),
  });

  const [owners, setOwners] = useState([]);
  useEffect(() => {
    if (!isEdit) api.get("/users").then((r) => setOwners(r.data)).catch(() => {});
  }, [isEdit]);

  useEffect(() => {
    if (isEdit) {
      api.get(`/assets/${id}`).then((r) => {
        const a = r.data;
        setForm({
          ...a,
          purchase_price: String(a.purchase_price),
          warranty_end_date: a.warranty_end_date ? a.warranty_end_date.split("T")[0] : "",
          purchase_date: a.purchase_date ? a.purchase_date.split("T")[0] : "",
          assigned_to_name: a.assigned_to_name || "",
          ...extrasFromAsset(a),
        });
      }).catch((e) => setError(formatErr(e)));
    }
  }, [id, isEdit]);

  // Load photo preview when photo_path changes
  useEffect(() => {
    if (!form.photo_path) {
      setPhotoPreview(null);
      return;
    }
    let revoked = null;
    api.get(`/files/${form.photo_path}`, { responseType: "blob" })
      .then((r) => {
        const url = URL.createObjectURL(r.data);
        revoked = url;
        setPhotoPreview(url);
      })
      .catch(() => setPhotoPreview(null));
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  }, [form.photo_path]);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const uploadFile = async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await api.post("/upload", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return res.data;
  };

  const MAX_PHOTO_BYTES = 100 * 1024;       // 100 KB
  const MAX_DOC_BYTES   = 1024 * 1024;     // 1 MB

  const handlePhoto = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      toast.error(t("photo_too_large"));
      e.target.value = "";
      return;
    }
    setPhotoUploading(true);
    try {
      const r = await uploadFile(file);
      update("photo_path", r.path);
      toast.success(t("photo_uploaded"));
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      setPhotoUploading(false);
      e.target.value = "";
    }
  };

  const handlePdf = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_DOC_BYTES) {
      toast.error(t("doc_too_large"));
      e.target.value = "";
      return;
    }
    setPdfUploading(true);
    try {
      const r = await uploadFile(file);
      update("documents", [...form.documents, { ...r, type: "supporting" }]);
      toast.success(t("doc_attached"));
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      setPdfUploading(false);
      e.target.value = "";
    }
  };

  const removeDoc = (path) =>
    update("documents", form.documents.filter((d) => d.path !== path));

  const setDocType = (path, type) =>
    update("documents", form.documents.map((d) => (d.path === path ? { ...d, type } : d)));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const payload = {
        ...form,
        purchase_price: parseFloat(form.purchase_price),
        useful_life_years: parseInt(form.useful_life_years, 10),
        warranty_end_date: form.warranty_end_date || null,
        maintenance_cost: parseFloat(form.maintenance_cost) || 0,
        residual_value: parseFloat(form.residual_value) || 0,
      };
      let res;
      if (isEdit) {
        res = await api.put(`/assets/${id}`, payload);
      } else {
        res = await api.post("/assets", payload);
      }
      if (!isEdit && res.data.pending_assignment) {
        toast.success(t("asset_created_pending").replace("{name}", res.data.pending_assignment.to_name));
      } else {
        toast.success(isEdit ? "Asset updated" : "Asset created");
      }
      navigate(`/assets/${res.data.id}`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 lg:p-10 max-w-3xl mx-auto" data-testid="asset-form-page">
      <button
        onClick={() => navigate(-1)}
        className="text-xs text-slate-500 hover:text-slate-900 inline-flex items-center gap-1.5 mb-6"
        data-testid="back-button"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> {t("back")}
      </button>

      <div className="label-mono mb-2">{isEdit ? t("edit_asset") : t("new_asset")}</div>
      <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900 mb-8">
        {isEdit ? form.name : t("register_asset")}
      </h1>

      <form onSubmit={submit} className="space-y-8">
        {/* Section 1: Identity */}
        <Section title={t("section_basic")}>
          <TextField label={t("asset_code")} value={form.asset_code} onChange={(v)=>update("asset_code",v)}
            placeholder={t("asset_code_placeholder")} mono testid="asset-code-input"/>
          <TextField label={t("asset_tag")} value={form.asset_tag} onChange={(v)=>update("asset_tag",v)}
            required placeholder={t("asset_tag_placeholder")} mono testid="asset-tag-input"/>
          <TextField label={t("asset_name")} value={form.name} onChange={(v)=>update("name",v)}
            required span2 testid="asset-name-input"/>
          <div>
            <Label className="label-mono">{t("col_category")}</Label>
            <Select value={form.category} onValueChange={(v)=>{
              update("category", v);
              if (!isEdit && !lifeTouched.current) update("useful_life_years", DEFAULT_USEFUL_LIFE[v] ?? 5);
            }}>
              <SelectTrigger className={FIELD_CLS} data-testid="asset-category-select">
                <SelectValue/>
              </SelectTrigger>
              <SelectContent>
                {CATEGORY_VALUES.map((c, i)=>({ c, i }))
                  .filter(({ c }) => !(user?.role === "admin" && ICT_CATEGORIES.includes(c)))   // Resources Admin: no ICT / media categories
                  .map(({ c, i })=>(<SelectItem key={c} value={c}>{t(CATEGORY_KEYS[i])}</SelectItem>))}
              </SelectContent>
            </Select>
          </div>
          <TextField label={t("item_type")} value={form.item_type} onChange={(v)=>update("item_type",v)}
            placeholder={t("item_type_placeholder")} testid="asset-item-type-input"/>
          <TextField label={t("brand")} value={form.brand} onChange={(v)=>update("brand",v)}
            placeholder={t("brand_placeholder")} testid="asset-brand-input"/>
          <TextField label={t("model")} value={form.model} onChange={(v)=>update("model",v)}
            placeholder={t("model_placeholder")} testid="asset-model-input"/>
          <TextField label={t("serial_number")} value={form.serial_number} onChange={(v)=>update("serial_number",v)}
            mono testid="asset-serial-input"/>
          <div>
            <Label className="label-mono">{t("asset_property_by")}</Label>
            <Select value={form.asset_type || "School Asset"} onValueChange={(v)=>update("asset_type",v)}>
              <SelectTrigger className={FIELD_CLS} data-testid="asset-type-select">
                <SelectValue/>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="School Asset">{t("asset_type_school")}</SelectItem>
                <SelectItem value="Company Asset">{t("asset_type_company")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2">
            <Label className="label-mono">{t("description")}</Label>
            <Textarea value={form.description || ""} onChange={(e)=>update("description",e.target.value)}
              rows={3} className={FIELD_CLS} data-testid="asset-description-input"/>
          </div>
        </Section>

        {/* Section 2: Location & Custodian */}
        <Section title={t("section_location")}>
          <div>
            <Label className="label-mono">{t("campus")}</Label>
            <Select value={form.campus || ""} onValueChange={(v)=>update("campus",v)}>
              <SelectTrigger className={FIELD_CLS} data-testid="asset-campus-select">
                <SelectValue placeholder={t("select_campus")}/>
              </SelectTrigger>
              <SelectContent>
                {CAMPUSES.map((c)=>(<SelectItem key={c} value={c}>{campusLabel(c)}</SelectItem>))}
              </SelectContent>
            </Select>
          </div>
          <SelectField label={t("unit")} value={form.unit} onChange={(v)=>update("unit",v)}
            options={optionsFor("unit", UNIT_VALUES, t)} placeholder={t("select_generic")} testid="asset-unit-select"/>
          <TextField label={t("building")} value={form.building} onChange={(v)=>update("building",v)}
            placeholder={t("building_placeholder")} testid="asset-building-input"/>
          <TextField label={t("room_location")} value={form.location} onChange={(v)=>update("location",v)}
            required placeholder={t("room_placeholder")} testid="asset-location-input"/>
          <div>
            <Label className="label-mono">{t("initial_owner")}</Label>
            {isEdit ? (
              <>
                <div className="mt-2 px-3 py-2 border border-slate-200 bg-slate-50 text-sm text-slate-700" data-testid="asset-assigned-readonly">
                  {form.assigned_to_name || "—"}
                </div>
                <p className="mt-1.5 text-xs text-slate-400">{t("owner_edit_hint")}</p>
              </>
            ) : (
              <>
                <select value={form.assigned_to_user_id || ""} data-testid="asset-assigned-input"
                  className="mt-2 w-full h-10 px-3 text-sm border border-slate-300 bg-white rounded-none"
                  onChange={(e) => {
                    const u = owners.find((x) => x.id === e.target.value);
                    setForm((f) => ({ ...f, assigned_to_user_id: u ? u.id : null, assigned_to_name: u ? u.name : "" }));
                  }}>
                  <option value="">{t("owner_none")}</option>
                  {owners.map((u) => <option key={u.id} value={u.id}>{u.name}{u.department ? ` — ${u.department}` : ""}</option>)}
                </select>
                <p className="mt-1.5 text-xs text-slate-400">{t("owner_confirm_hint")}</p>
              </>
            )}
          </div>
          <TextField label={t("asset_department")} value={form.department} onChange={(v)=>update("department",v)}
            placeholder={t("asset_department_placeholder")} testid="asset-department-input"/>
          <SelectField label={t("user_type")} value={form.user_type} onChange={(v)=>update("user_type",v)}
            options={optionsFor("ut", USER_TYPE_VALUES, t)} placeholder={t("select_generic")} testid="asset-user-type-select"/>
        </Section>

        {/* Section 3: Acquisition */}
        <Section title={t("section_acquisition")}>
          <TextField label={t("purchase_date")} type="date" value={form.purchase_date}
            onChange={(v)=>update("purchase_date",v)} required testid="asset-purchase-date-input"/>
          <SelectField label={t("acquisition_type")} value={form.acquisition_type} onChange={(v)=>update("acquisition_type",v)}
            options={optionsFor("acq", ACQ_VALUES, t)} placeholder={t("select_generic")} testid="asset-acq-type-select"/>
          <TextField label={t("supplier")} value={form.supplier} onChange={(v)=>update("supplier",v)}
            testid="asset-supplier-input"/>
          <TextField label={t("po_number")} value={form.po_number} onChange={(v)=>update("po_number",v)}
            placeholder={t("po_placeholder")} mono testid="asset-po-input"/>
          <MoneyField label={t("purchase_price")} idr={form.purchase_price}
            onChangeIdr={(v)=>update("purchase_price",v)} required testid="asset-price-input"/>
          <TextField label={t("funding_source")} value={form.funding_source} onChange={(v)=>update("funding_source",v)}
            placeholder={t("funding_placeholder")} testid="asset-funding-input"/>
        </Section>

        {/* Section 4: Condition & Inspection */}
        <Section title={t("section_condition")}>
          <div>
            <Label className="label-mono">{t("status")}</Label>
            <Select value={form.status} onValueChange={(v)=>update("status",v)}>
              <SelectTrigger className={FIELD_CLS} data-testid="asset-status-select">
                <SelectValue/>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">{t("status_active")}</SelectItem>
                <SelectItem value="in_repair">{t("status_in_repair")}</SelectItem>
                <SelectItem value="retired">{t("status_retired")}</SelectItem>
                <SelectItem value="lost">{t("status_lost")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <SelectField label={t("asset_condition")} value={form.asset_condition} onChange={(v)=>update("asset_condition",v)}
            options={optionsFor("cond", CONDITION_VALUES, t)} placeholder={t("select_generic")} testid="asset-condition-select"/>
          <TextField label={t("condition_notes")} value={form.condition_notes} onChange={(v)=>update("condition_notes",v)}
            span2 testid="asset-condition-notes-input"/>
          <TextField label={t("last_inspection")} type="date" value={form.last_inspection_date}
            onChange={(v)=>update("last_inspection_date",v)} testid="asset-last-inspection-input"/>
          <TextField label={t("next_inspection")} type="date" value={form.next_inspection_date}
            onChange={(v)=>update("next_inspection_date",v)} testid="asset-next-inspection-input"/>
        </Section>

        {/* Section 5: Maintenance */}
        <Section title={t("section_maintenance")}>
          <SelectField label={t("maintenance_required")} value={form.maintenance_required ? "yes" : "no"}
            onChange={(v)=>update("maintenance_required", v === "yes")}
            options={[{ value: "no", label: t("opt_no") }, { value: "yes", label: t("opt_yes") }]}
            testid="asset-maintenance-required-select"/>
          <TextField label={t("maintenance_provider")} value={form.maintenance_provider}
            onChange={(v)=>update("maintenance_provider",v)} placeholder={t("maintenance_provider_placeholder")}
            testid="asset-maintenance-provider-input"/>
          <TextField label={t("last_maintenance")} type="date" value={form.last_maintenance_date}
            onChange={(v)=>update("last_maintenance_date",v)} testid="asset-last-maintenance-input"/>
          <TextField label={t("next_maintenance")} type="date" value={form.next_maintenance_date}
            onChange={(v)=>update("next_maintenance_date",v)} testid="asset-next-maintenance-input"/>
          <MoneyField label={t("maintenance_cost")} idr={form.maintenance_cost} min="0"
            onChangeIdr={(v)=>update("maintenance_cost",v)} testid="asset-maintenance-cost-input"/>
        </Section>

        {/* Section 6: Warranty */}
        <Section title={t("section_warranty")}>
          <TextField label={t("warranty_start")} type="date" value={form.warranty_start_date}
            onChange={(v)=>update("warranty_start_date",v)} testid="asset-warranty-start-input"/>
          <TextField label={t("warranty_end")} type="date" value={form.warranty_end_date}
            onChange={(v)=>update("warranty_end_date",v)} testid="asset-warranty-input"/>
          <TextField label={t("warranty_provider")} value={form.warranty_provider}
            onChange={(v)=>update("warranty_provider",v)} span2 testid="asset-warranty-provider-input"/>
        </Section>

        {/* Section 7: Financials */}
        <Section title={t("section_financials")}>
          <TextField label={t("useful_life")} type="number" min="1" value={form.useful_life_years}
            onChange={(v)=>{ lifeTouched.current = true; update("useful_life_years", v); }} required testid="asset-life-input"
            hint={t("life_hint").replace("{n}", DEFAULT_USEFUL_LIFE[form.category] ?? 5)}/>
          <MoneyField label={t("residual_value")} idr={form.residual_value} min="0"
            onChangeIdr={(v)=>update("residual_value",v)} testid="asset-residual-input"/>
        </Section>

        {/* Section 8: Media */}
        <section className="bg-white border border-slate-200 p-6">
          <div className="label-mono mb-5 text-blue-800">{t("section_media")}</div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Photo */}
            <div>
              <Label className="label-mono">{t("asset_photo")}</Label>
              <div className="mt-2 border border-dashed border-slate-300 aspect-video flex items-center justify-center bg-slate-50 relative overflow-hidden">
                {photoPreview ? (
                  <>
                    <img src={photoPreview} alt="" className="w-full h-full object-cover" />
                    <button type="button" onClick={()=>update("photo_path",null)}
                      className="absolute top-2 right-2 bg-white border border-slate-300 p-1 hover:bg-rose-50">
                      <X className="w-3 h-3"/>
                    </button>
                  </>
                ) : (
                  <label className="flex flex-col items-center gap-2 cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                    <ImageIcon className="w-6 h-6" strokeWidth={1.5}/>
                    {photoUploading ? t("uploading") : t("click_upload_photo")}
                    <input type="file" accept="image/*" onChange={handlePhoto} className="hidden"
                      data-testid="photo-upload-input"/>
                  </label>
                )}
              </div>
              <p className="mt-1.5 text-xs text-slate-400">{t("upload_size_limit")}</p>
            </div>

            {/* PDFs */}
            <div>
              <Label className="label-mono">{t("documents_label")}</Label>
              <label className="mt-2 border border-dashed border-slate-300 aspect-video flex flex-col items-center justify-center bg-slate-50 cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                <Upload className="w-6 h-6" strokeWidth={1.5}/>
                <div className="mt-2">{pdfUploading ? t("uploading") : t("attach_doc")}</div>
                <input type="file" onChange={handlePdf} className="hidden" data-testid="document-upload-input"/>
              </label>
              <p className="mt-1.5 text-xs text-slate-400">{t("upload_doc_size_limit")}</p>
            </div>
          </div>

          {form.documents.length > 0 && (
            <div className="mt-5 space-y-2">
              {form.documents.map((d) => (
                <div key={d.path} className="flex items-center gap-3 p-3 border border-slate-200 bg-slate-50">
                  <FileText className="w-4 h-4 text-slate-500" strokeWidth={1.5}/>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate">{d.name}</div>
                    <div className="text-xs text-slate-500">{(d.size/1024).toFixed(1)} KB</div>
                  </div>
                  <select value={d.type || "supporting"} onChange={(e)=>setDocType(d.path, e.target.value)}
                    className="text-xs border border-slate-300 bg-white px-2 py-1" data-testid="document-type-select">
                    <option value="invoice">{t("doc_invoice")}</option>
                    <option value="warranty">{t("doc_warranty")}</option>
                    <option value="supporting">{t("doc_supporting")}</option>
                  </select>
                  <button type="button" onClick={()=>removeDoc(d.path)}
                    className="text-slate-400 hover:text-rose-600">
                    <X className="w-4 h-4"/>
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {error && (
          <Alert variant="destructive" data-testid="form-error">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={submitting}
            className="rounded-none bg-slate-900 hover:bg-slate-800 h-11 px-6"
            data-testid="submit-asset-button">
            {submitting ? t("saving") : (isEdit ? t("save_changes") : t("create_asset"))}
          </Button>
          <Button type="button" variant="outline" onClick={()=>navigate(-1)}
            className="rounded-none h-11">
            {t("cancel")}
          </Button>
        </div>
      </form>
    </div>
  );
}
