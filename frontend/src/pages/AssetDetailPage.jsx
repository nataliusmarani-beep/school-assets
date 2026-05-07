import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { fmtCurrency, fmtDate, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "../components/ui/dialog";
import { useAuth } from "../context/AuthContext";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRightLeft, Wrench, Edit, Trash2, Download,
  FileText, Calendar, ShieldCheck, Building2, User as UserIcon, Tag,
} from "lucide-react";

export default function AssetDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [asset, setAsset] = useState(null);
  const [loading, setLoading] = useState(true);
  const [photoUrl, setPhotoUrl] = useState(null);

  // Transfer dialog
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferTo, setTransferTo] = useState("");
  const [transferNote, setTransferNote] = useState("");

  // Fault dialog
  const [faultOpen, setFaultOpen] = useState(false);
  const [faultTitle, setFaultTitle] = useState("");
  const [faultDesc, setFaultDesc] = useState("");
  const [faultSev, setFaultSev] = useState("medium");

  const load = () => {
    setLoading(true);
    api.get(`/assets/${id}`)
      .then((r) => setAsset(r.data))
      .catch(() => toast.error("Failed to load asset"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  useEffect(() => {
    if (!asset?.photo_path) { setPhotoUrl(null); return; }
    let url = null;
    api.get(`/files/${asset.photo_path}`, { responseType: "blob" })
      .then((r) => { url = URL.createObjectURL(r.data); setPhotoUrl(url); });
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [asset?.photo_path]);

  const downloadDoc = async (doc) => {
    try {
      const r = await api.get(`/files/${doc.path}`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = doc.name; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 100);
    } catch (e) {
      toast.error(formatErr(e));
    }
  };

  const submitTransfer = async () => {
    try {
      await api.post(`/assets/${id}/transfer`, {
        new_owner_name: transferTo, note: transferNote,
      });
      toast.success("Asset transferred");
      setTransferOpen(false); setTransferTo(""); setTransferNote("");
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const submitFault = async () => {
    try {
      await api.post(`/faults`, {
        asset_id: id, title: faultTitle, description: faultDesc, severity: faultSev,
      });
      toast.success("Fault reported");
      setFaultOpen(false); setFaultTitle(""); setFaultDesc("");
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const handleDelete = async () => {
    if (!window.confirm("Delete this asset? This cannot be undone.")) return;
    try {
      await api.delete(`/assets/${id}`);
      toast.success("Asset deleted");
      navigate("/assets");
    } catch (e) { toast.error(formatErr(e)); }
  };

  if (loading) return <div className="p-8 text-sm text-slate-500">Loading…</div>;
  if (!asset) return <div className="p-8 text-sm text-slate-500">Asset not found.</div>;

  const dep = asset.depreciation || {};

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="asset-detail-page">
      <button onClick={() => navigate("/assets")}
        className="text-xs text-slate-500 hover:text-slate-900 inline-flex items-center gap-1.5 mb-6"
        data-testid="back-to-assets">
        <ArrowLeft className="w-3.5 h-3.5"/> Back to assets
      </button>

      <div className="flex items-start justify-between flex-wrap gap-4 mb-8">
        <div>
          <div className="label-mono mb-2 flex items-center gap-2">
            <Tag className="w-3 h-3"/> {asset.asset_tag}
          </div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            {asset.name}
          </h1>
          <div className="text-sm text-slate-500 mt-2">{asset.description}</div>
        </div>
        <div className="flex items-center gap-2">
          <Dialog open={faultOpen} onOpenChange={setFaultOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="rounded-none" data-testid="report-fault-button">
                <Wrench className="w-4 h-4 mr-2" strokeWidth={1.75}/> Report fault
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none">
              <DialogHeader><DialogTitle>Report a fault</DialogTitle></DialogHeader>
              <div className="space-y-4">
                <div><Label className="label-mono">Title</Label>
                  <Input value={faultTitle} onChange={(e)=>setFaultTitle(e.target.value)}
                    className="mt-2 rounded-none" data-testid="fault-title-input"/></div>
                <div><Label className="label-mono">Description</Label>
                  <Textarea value={faultDesc} onChange={(e)=>setFaultDesc(e.target.value)}
                    rows={3} className="mt-2 rounded-none" data-testid="fault-desc-input"/></div>
                <div><Label className="label-mono">Severity</Label>
                  <Select value={faultSev} onValueChange={setFaultSev}>
                    <SelectTrigger className="mt-2 rounded-none" data-testid="fault-severity-select"><SelectValue/></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                    </SelectContent>
                  </Select></div>
              </div>
              <DialogFooter>
                <Button onClick={submitFault} className="rounded-none bg-slate-900" data-testid="submit-fault-button">Submit</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={transferOpen} onOpenChange={setTransferOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="rounded-none" data-testid="transfer-button">
                <ArrowRightLeft className="w-4 h-4 mr-2" strokeWidth={1.75}/> Transfer
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none">
              <DialogHeader><DialogTitle>Transfer ownership</DialogTitle></DialogHeader>
              <div className="space-y-4">
                <div><Label className="label-mono">New owner / location</Label>
                  <Input value={transferTo} onChange={(e)=>setTransferTo(e.target.value)}
                    placeholder="e.g. James Park, Room 105"
                    className="mt-2 rounded-none" data-testid="transfer-to-input"/></div>
                <div><Label className="label-mono">Note</Label>
                  <Textarea value={transferNote} onChange={(e)=>setTransferNote(e.target.value)}
                    rows={2} className="mt-2 rounded-none" data-testid="transfer-note-input"/></div>
              </div>
              <DialogFooter>
                <Button onClick={submitTransfer} className="rounded-none bg-slate-900" data-testid="submit-transfer-button">Confirm transfer</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Link to={`/assets/${id}/edit`}>
            <Button variant="outline" className="rounded-none" data-testid="edit-asset-button">
              <Edit className="w-4 h-4 mr-2" strokeWidth={1.75}/> Edit
            </Button>
          </Link>
          {user?.role === "admin" && (
            <Button variant="outline" onClick={handleDelete}
              className="rounded-none text-rose-600 hover:text-rose-700"
              data-testid="delete-asset-button">
              <Trash2 className="w-4 h-4" strokeWidth={1.75}/>
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Photo + specs */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-white border border-slate-200 aspect-video overflow-hidden">
            {photoUrl ? (
              <img src={photoUrl} alt={asset.name} className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full flex items-center justify-center bg-slate-50 text-xs text-slate-400">
                No photo
              </div>
            )}
          </div>

          <div className="bg-white border border-slate-200 p-6 space-y-4">
            <div className="label-mono">Quick facts</div>
            <Detail icon={Building2} label="Location" value={asset.location}/>
            <Detail icon={UserIcon} label="Assigned to" value={asset.assigned_to_name || "—"}/>
            <Detail icon={Calendar} label="Purchased" value={fmtDate(asset.purchase_date)}/>
            <Detail icon={ShieldCheck} label="Warranty until" value={fmtDate(asset.warranty_end_date)}/>
          </div>

          <div className="bg-white border border-slate-200 p-6">
            <div className="label-mono mb-4">Depreciation</div>
            <div className="space-y-3">
              <Row label="Purchase price" value={fmtCurrency(asset.purchase_price)}/>
              <Row label="Annual depreciation" value={fmtCurrency(dep.annual)}/>
              <Row label="Accumulated" value={fmtCurrency(dep.accumulated)}/>
              <div className="border-t border-slate-200 pt-3">
                <Row label="Current book value" value={fmtCurrency(dep.current_value)} bold/>
              </div>
              <div className="text-xs text-slate-500">Age: {dep.age_years} yrs · Useful life: {asset.useful_life_years} yrs</div>
            </div>
          </div>
        </div>

        {/* Right: Tabs */}
        <div className="lg:col-span-2">
          <Tabs defaultValue="overview" className="bg-white border border-slate-200">
            <TabsList className="w-full justify-start rounded-none bg-slate-50 border-b border-slate-200 p-0 h-auto">
              <TabsTrigger value="overview" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-overview">Overview</TabsTrigger>
              <TabsTrigger value="history" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-history">Ownership</TabsTrigger>
              <TabsTrigger value="faults" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-faults">Faults ({asset.faults?.length || 0})</TabsTrigger>
              <TabsTrigger value="docs" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-docs">Documents</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="p-6">
              <dl className="grid grid-cols-2 gap-y-4">
                <Field label="Category" value={asset.category}/>
                <Field label="Status" value={asset.status.replace("_", " ")}/>
                <Field label="Serial number" value={asset.serial_number || "—"} mono/>
                <Field label="Supplier" value={asset.supplier || "—"}/>
                <Field label="Useful life" value={`${asset.useful_life_years} years`}/>
                <Field label="Created" value={fmtDate(asset.created_at)}/>
              </dl>
            </TabsContent>

            <TabsContent value="history" className="p-6">
              {(!asset.ownership_history || asset.ownership_history.length === 0) ? (
                <div className="text-sm text-slate-500">No ownership records.</div>
              ) : (
                <ol className="relative border-l-2 border-slate-200 ml-2 space-y-6">
                  {asset.ownership_history.map((h) => (
                    <li key={h.id} className="pl-6 relative">
                      <div className="absolute -left-[7px] top-1 w-3 h-3 bg-blue-700"/>
                      <div className="text-sm font-medium text-slate-900">
                        Transferred to <span className="text-blue-800">{h.to_name}</span>
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        From: {h.from_name || "—"} · By {h.by_name} · {fmtDate(h.at)}
                      </div>
                      {h.note && <div className="text-sm text-slate-600 mt-2 italic">"{h.note}"</div>}
                    </li>
                  ))}
                </ol>
              )}
            </TabsContent>

            <TabsContent value="faults" className="p-6">
              {(!asset.faults || asset.faults.length === 0) ? (
                <div className="text-sm text-slate-500">No fault reports.</div>
              ) : (
                <div className="space-y-4">
                  {asset.faults.map((f) => (
                    <div key={f.id} className="border border-slate-200 p-4">
                      <div className="flex items-start justify-between">
                        <div className="font-medium text-slate-900">{f.title}</div>
                        <span className={`text-xs px-2 py-0.5 border ${
                          f.status === "resolved" ? "bg-blue-50 text-blue-800 border-blue-200" :
                          f.status === "in_progress" ? "bg-blue-50 text-blue-700 border-blue-200" :
                          "bg-amber-50 text-amber-700 border-amber-200"
                        }`}>{f.status.replace("_", " ")}</span>
                      </div>
                      <div className="text-sm text-slate-600 mt-2">{f.description}</div>
                      <div className="text-xs text-slate-500 mt-3">
                        Reported by {f.reported_by_name} · {fmtDate(f.created_at)} · Severity: {f.severity}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            <TabsContent value="docs" className="p-6">
              {(!asset.documents || asset.documents.length === 0) ? (
                <div className="text-sm text-slate-500">No documents attached.</div>
              ) : (
                <div className="space-y-2">
                  {asset.documents.map((d) => (
                    <div key={d.path} className="flex items-center gap-3 p-3 border border-slate-200 hover:bg-slate-50">
                      <FileText className="w-4 h-4 text-slate-500"/>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{d.name}</div>
                        <div className="text-xs text-slate-500">{(d.size/1024).toFixed(1)} KB</div>
                      </div>
                      <Button variant="outline" size="sm" className="rounded-none"
                        onClick={()=>downloadDoc(d)} data-testid={`download-doc-${d.path}`}>
                        <Download className="w-3.5 h-3.5"/>
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}

function Detail({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-3">
      <Icon className="w-4 h-4 text-slate-400 mt-0.5" strokeWidth={1.75}/>
      <div>
        <div className="label-mono mb-0.5">{label}</div>
        <div className="text-sm text-slate-900">{value}</div>
      </div>
    </div>
  );
}

function Row({ label, value, bold = false }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-600">{label}</span>
      <span className={`font-mono ${bold ? "text-blue-800 font-semibold text-base" : "text-slate-900"}`}>{value}</span>
    </div>
  );
}

function Field({ label, value, mono = false }) {
  return (
    <div>
      <dt className="label-mono mb-1">{label}</dt>
      <dd className={`text-sm text-slate-900 capitalize ${mono ? "font-mono normal-case" : ""}`}>{value}</dd>
    </div>
  );
}
