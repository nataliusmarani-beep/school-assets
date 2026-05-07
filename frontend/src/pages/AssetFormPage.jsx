import { useEffect, useState } from "react";
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

const CATEGORIES = [
  "IT Equipment", "AV Equipment", "Furniture", "Lab Equipment",
  "Vehicles", "Books", "Sports", "Music Equipment", "Other",
];

export default function AssetFormPage() {
  const { id } = useParams();
  const isEdit = !!id;
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [photoUploading, setPhotoUploading] = useState(false);
  const [pdfUploading, setPdfUploading] = useState(false);
  const [photoPreview, setPhotoPreview] = useState(null);

  const [form, setForm] = useState({
    name: "", asset_tag: "", category: "IT Equipment", description: "",
    location: "", status: "active", purchase_price: "",
    purchase_date: new Date().toISOString().split("T")[0],
    useful_life_years: 5, warranty_end_date: "", serial_number: "",
    supplier: "", assigned_to_name: "", photo_path: null, documents: [],
  });

  useEffect(() => {
    if (isEdit) {
      api.get(`/assets/${id}`).then((r) => {
        const a = r.data;
        setForm({
          ...a,
          purchase_price: String(a.purchase_price),
          warranty_end_date: a.warranty_end_date ? a.warranty_end_date.split("T")[0] : "",
          purchase_date: a.purchase_date ? a.purchase_date.split("T")[0] : "",
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

  const handlePhoto = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPhotoUploading(true);
    try {
      const r = await uploadFile(file);
      update("photo_path", r.path);
      toast.success("Photo uploaded");
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      setPhotoUploading(false);
    }
  };

  const handlePdf = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPdfUploading(true);
    try {
      const r = await uploadFile(file);
      update("documents", [...form.documents, r]);
      toast.success("Document attached");
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      setPdfUploading(false);
      e.target.value = "";
    }
  };

  const removeDoc = (path) =>
    update("documents", form.documents.filter((d) => d.path !== path));

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
      };
      let res;
      if (isEdit) {
        res = await api.put(`/assets/${id}`, payload);
      } else {
        res = await api.post("/assets", payload);
      }
      toast.success(isEdit ? "Asset updated" : "Asset created");
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
        <ArrowLeft className="w-3.5 h-3.5" /> Back
      </button>

      <div className="label-mono mb-2">{isEdit ? "Edit asset" : "New asset"}</div>
      <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900 mb-8">
        {isEdit ? form.name : "Register a new asset"}
      </h1>

      <form onSubmit={submit} className="space-y-8">
        {/* Section 1: Basic Info */}
        <section className="bg-white border border-slate-200 p-6">
          <div className="label-mono mb-5 text-blue-800">01 — Basic Information</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="md:col-span-2">
              <Label className="label-mono">Asset name</Label>
              <Input value={form.name} onChange={(e)=>update("name",e.target.value)}
                required className="mt-2 rounded-none border-slate-300" data-testid="asset-name-input"/>
            </div>
            <div>
              <Label className="label-mono">Asset tag</Label>
              <Input value={form.asset_tag} onChange={(e)=>update("asset_tag",e.target.value)}
                required placeholder="e.g. IT-LAP-0001" className="mt-2 rounded-none border-slate-300 font-mono"
                data-testid="asset-tag-input"/>
            </div>
            <div>
              <Label className="label-mono">Category</Label>
              <Select value={form.category} onValueChange={(v)=>update("category",v)}>
                <SelectTrigger className="mt-2 rounded-none border-slate-300" data-testid="asset-category-select">
                  <SelectValue/>
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c)=>(<SelectItem key={c} value={c}>{c}</SelectItem>))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="label-mono">Location</Label>
              <Input value={form.location} onChange={(e)=>update("location",e.target.value)}
                required placeholder="e.g. Computer Lab A" className="mt-2 rounded-none border-slate-300"
                data-testid="asset-location-input"/>
            </div>
            <div>
              <Label className="label-mono">Status</Label>
              <Select value={form.status} onValueChange={(v)=>update("status",v)}>
                <SelectTrigger className="mt-2 rounded-none border-slate-300" data-testid="asset-status-select">
                  <SelectValue/>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="in_repair">In Repair</SelectItem>
                  <SelectItem value="retired">Retired</SelectItem>
                  <SelectItem value="lost">Lost</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-2">
              <Label className="label-mono">Description</Label>
              <Textarea value={form.description} onChange={(e)=>update("description",e.target.value)}
                rows={3} className="mt-2 rounded-none border-slate-300"
                data-testid="asset-description-input"/>
            </div>
            <div>
              <Label className="label-mono">Serial number</Label>
              <Input value={form.serial_number} onChange={(e)=>update("serial_number",e.target.value)}
                className="mt-2 rounded-none border-slate-300 font-mono" data-testid="asset-serial-input"/>
            </div>
            <div>
              <Label className="label-mono">Initial owner / location</Label>
              <Input value={form.assigned_to_name} onChange={(e)=>update("assigned_to_name",e.target.value)}
                placeholder="e.g. Maria Hernandez" className="mt-2 rounded-none border-slate-300"
                data-testid="asset-assigned-input"/>
            </div>
          </div>
        </section>

        {/* Section 2: Financial */}
        <section className="bg-white border border-slate-200 p-6">
          <div className="label-mono mb-5 text-blue-800">02 — Financials & Warranty</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div>
              <Label className="label-mono">Purchase price (USD)</Label>
              <Input type="number" step="0.01" value={form.purchase_price}
                onChange={(e)=>update("purchase_price",e.target.value)}
                required className="mt-2 rounded-none border-slate-300 font-mono"
                data-testid="asset-price-input"/>
            </div>
            <div>
              <Label className="label-mono">Purchase date</Label>
              <Input type="date" value={form.purchase_date}
                onChange={(e)=>update("purchase_date",e.target.value)}
                required className="mt-2 rounded-none border-slate-300"
                data-testid="asset-purchase-date-input"/>
            </div>
            <div>
              <Label className="label-mono">Useful life (years)</Label>
              <Input type="number" min="1" value={form.useful_life_years}
                onChange={(e)=>update("useful_life_years",e.target.value)}
                required className="mt-2 rounded-none border-slate-300"
                data-testid="asset-life-input"/>
            </div>
            <div>
              <Label className="label-mono">Warranty end date</Label>
              <Input type="date" value={form.warranty_end_date}
                onChange={(e)=>update("warranty_end_date",e.target.value)}
                className="mt-2 rounded-none border-slate-300"
                data-testid="asset-warranty-input"/>
            </div>
            <div className="md:col-span-2">
              <Label className="label-mono">Supplier</Label>
              <Input value={form.supplier} onChange={(e)=>update("supplier",e.target.value)}
                className="mt-2 rounded-none border-slate-300" data-testid="asset-supplier-input"/>
            </div>
          </div>
        </section>

        {/* Section 3: Media */}
        <section className="bg-white border border-slate-200 p-6">
          <div className="label-mono mb-5 text-blue-800">03 — Photo & Documents</div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Photo */}
            <div>
              <Label className="label-mono">Asset photo</Label>
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
                    {photoUploading ? "Uploading…" : "Click to upload photo"}
                    <input type="file" accept="image/*" onChange={handlePhoto} className="hidden"
                      data-testid="photo-upload-input"/>
                  </label>
                )}
              </div>
            </div>

            {/* PDFs */}
            <div>
              <Label className="label-mono">Documents (PDF, etc.)</Label>
              <label className="mt-2 border border-dashed border-slate-300 aspect-video flex flex-col items-center justify-center bg-slate-50 cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                <Upload className="w-6 h-6" strokeWidth={1.5}/>
                <div className="mt-2">{pdfUploading ? "Uploading…" : "Attach a document"}</div>
                <input type="file" onChange={handlePdf} className="hidden" data-testid="document-upload-input"/>
              </label>
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
            {submitting ? "Saving…" : (isEdit ? "Save changes" : "Create asset")}
          </Button>
          <Button type="button" variant="outline" onClick={()=>navigate(-1)}
            className="rounded-none h-11">
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}
