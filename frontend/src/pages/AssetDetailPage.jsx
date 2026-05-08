import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { fmtCurrency, fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "../components/ui/dialog";
import { useAuth } from "../context/AuthContext";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRightLeft, Wrench, Edit, Trash2, Download,
  FileText, Calendar, ShieldCheck, Building2, User as UserIcon, Tag, BookOpen,
} from "lucide-react";

export default function AssetDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t } = useLang();
  const [asset, setAsset] = useState(null);
  const [loading, setLoading] = useState(true);
  const [photoUrl, setPhotoUrl] = useState(null);

  const [transferOpen, setTransferOpen] = useState(false);
  const [transferTo, setTransferTo] = useState("");
  const [transferNote, setTransferNote] = useState("");

  const [loanOpen, setLoanOpen] = useState(false);
  const [loanPurpose, setLoanPurpose] = useState("");
  const [loanStart, setLoanStart] = useState("");
  const [loanEnd, setLoanEnd] = useState("");
  const [transferCampus, setTransferCampus] = useState("");
  const [transferRoom, setTransferRoom] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [userResults, setUserResults] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const [allRooms, setAllRooms] = useState([]);
  const [roomResults, setRoomResults] = useState([]);
  const [showRoomDropdown, setShowRoomDropdown] = useState(false);

  const [faultOpen, setFaultOpen] = useState(false);
  const [faultTitle, setFaultTitle] = useState("");
  const [faultDesc, setFaultDesc] = useState("");
  const [faultSev, setFaultSev] = useState("medium");

  const load = () => {
    setLoading(true);
    api.get(`/assets/${id}`)
      .then((r) => setAsset(r.data))
      .catch(() => toast.error(t("asset_load_error")))
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
    } catch (e) { toast.error(formatErr(e)); }
  };

  const isAdmin = user?.role === "admin";
  // Staff can only act on assets in their own campus
  const canActOnAsset = isAdmin || !asset || !user?.campus || !asset.campus || user.campus === asset.campus;

  // Load users + rooms when transfer dialog opens; lock campus for staff
  useEffect(() => {
    if (!transferOpen) return;
    const campus = !isAdmin && user?.campus ? user.campus : (asset?.campus || "");
    if (!isAdmin && user?.campus) setTransferCampus(user.campus);
    api.get("/users").then((r) => setAllUsers(r.data)).catch(() => {});
    api.get("/assets", { params: campus ? { campus } : {} })
      .then((r) => {
        const rooms = [...new Set(r.data.map((a) => a.location).filter(Boolean))].sort();
        setAllRooms(rooms);
      }).catch(() => {});
  }, [transferOpen]); // eslint-disable-line

  const handleUserSearch = (val) => {
    setUserSearch(val);
    setTransferTo(val);
    if (val.trim().length === 0) { setUserResults([]); setShowUserDropdown(false); return; }
    const q = val.toLowerCase();
    const campusFilter = !isAdmin && user?.campus ? user.campus : null;
    const matches = allUsers.filter((u) => {
      if (campusFilter && u.campus !== campusFilter) return false;
      return u.name.toLowerCase().includes(q) || (u.department || "").toLowerCase().includes(q);
    });
    setUserResults(matches);
    setShowUserDropdown(matches.length > 0);
  };

  const selectUser = (u) => {
    setTransferTo(u.name);
    setUserSearch(u.name);
    if (u.campus) setTransferCampus(u.campus);
    setUserResults([]);
    setShowUserDropdown(false);
  };

  const buildOwnerLabel = () => {
    const parts = [transferTo.trim()];
    if (transferRoom.trim()) parts.push(transferRoom.trim());
    if (transferCampus) parts.push(transferCampus);
    return parts.join(" — ");
  };

  const handleRoomSearch = (val) => {
    setTransferRoom(val);
    if (!val.trim()) { setRoomResults([]); setShowRoomDropdown(false); return; }
    const q = val.toLowerCase();
    const matches = allRooms.filter((r) => r.toLowerCase().includes(q) && r !== val);
    setRoomResults(matches);
    setShowRoomDropdown(matches.length > 0);
  };

  const selectRoom = (r) => {
    setTransferRoom(r);
    setRoomResults([]);
    setShowRoomDropdown(false);
  };

  const resetTransferForm = () => {
    setTransferTo(""); setTransferNote(""); setTransferCampus("");
    setTransferRoom(""); setUserSearch(""); setUserResults([]);
    setShowUserDropdown(false); setRoomResults([]); setShowRoomDropdown(false);
  };

  const submitTransfer = async () => {
    const ownerLabel = buildOwnerLabel();
    if (!ownerLabel.trim()) return toast.error(t("transfer_owner_required"));
    try {
      if (isAdmin) {
        await api.post(`/assets/${id}/transfer`, { new_owner_name: ownerLabel, note: transferNote });
        toast.success(t("asset_transferred"));
      } else {
        await api.post(`/transfer-requests`, { new_owner_name: ownerLabel, note: transferNote }, {
          params: { asset_id: id },
        });
        toast.success(t("transfer_request_submitted"));
      }
      setTransferOpen(false); resetTransferForm();
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const submitLoanRequest = async () => {
    try {
      await api.post(`/assets/${id}/loan-request`, { purpose: loanPurpose, start_date: loanStart || null, end_date: loanEnd || null });
      toast.success(t("loan_request_submitted"));
      setLoanOpen(false); setLoanPurpose(""); setLoanStart(""); setLoanEnd("");
    } catch (e) { toast.error(formatErr(e)); }
  };

  const submitFault = async () => {
    try {
      await api.post(`/faults`, { asset_id: id, title: faultTitle, description: faultDesc, severity: faultSev });
      toast.success(t("fault_reported_ok"));
      setFaultOpen(false); setFaultTitle(""); setFaultDesc("");
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const handleDelete = async () => {
    if (!window.confirm(t("delete_asset_confirm"))) return;
    try {
      await api.delete(`/assets/${id}`);
      toast.success(t("asset_deleted"));
      navigate("/assets");
    } catch (e) { toast.error(formatErr(e)); }
  };

  if (loading) return <div className="p-8 text-sm text-slate-500">{t("loading")}</div>;
  if (!asset) return <div className="p-8 text-sm text-slate-500">{t("asset_not_found")}</div>;

  const dep = asset.depreciation || {};

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="asset-detail-page">
      <button onClick={() => navigate("/assets")}
        className="text-xs text-slate-500 hover:text-slate-900 inline-flex items-center gap-1.5 mb-6"
        data-testid="back-to-assets">
        <ArrowLeft className="w-3.5 h-3.5"/> {t("back_to_assets")}
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
          {canActOnAsset && <Dialog open={faultOpen} onOpenChange={setFaultOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="rounded-none" data-testid="report-fault-button">
                <Wrench className="w-4 h-4 mr-2" strokeWidth={1.75}/> {t("report_fault")}
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none">
              <DialogHeader><DialogTitle>{t("report_a_fault")}</DialogTitle></DialogHeader>
              <div className="space-y-4">
                <div><Label className="label-mono">{t("title_label")}</Label>
                  <Input value={faultTitle} onChange={(e)=>setFaultTitle(e.target.value)}
                    className="mt-2 rounded-none" data-testid="fault-title-input"/></div>
                <div><Label className="label-mono">{t("description")}</Label>
                  <Textarea value={faultDesc} onChange={(e)=>setFaultDesc(e.target.value)}
                    rows={3} className="mt-2 rounded-none" data-testid="fault-desc-input"/></div>
                <div><Label className="label-mono">{t("severity")}</Label>
                  <Select value={faultSev} onValueChange={setFaultSev}>
                    <SelectTrigger className="mt-2 rounded-none" data-testid="fault-severity-select"><SelectValue/></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">{t("sev_low")}</SelectItem>
                      <SelectItem value="medium">{t("sev_medium")}</SelectItem>
                      <SelectItem value="high">{t("sev_high")}</SelectItem>
                    </SelectContent>
                  </Select></div>
              </div>
              <DialogFooter>
                <Button onClick={submitFault} className="rounded-none bg-slate-900" data-testid="submit-fault-button">
                  {t("submit")}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>}

          {canActOnAsset && <Dialog open={transferOpen} onOpenChange={setTransferOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="rounded-none" data-testid="transfer-button">
                <ArrowRightLeft className="w-4 h-4 mr-2" strokeWidth={1.75}/> {t("transfer")}
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none">
              <DialogHeader>
                <DialogTitle>{isAdmin ? t("transfer_ownership") : t("request_transfer")}</DialogTitle>
              </DialogHeader>
              {!isAdmin && (
                <p className="text-sm text-slate-500">{t("transfer_request_hint")}</p>
              )}
              <div className="space-y-4">
                {/* Searchable user picker */}
                <div className="relative">
                  <Label className="label-mono">{t("new_owner_label")}</Label>
                  <Input
                    value={userSearch}
                    onChange={(e) => handleUserSearch(e.target.value)}
                    placeholder={t("new_owner_placeholder")}
                    className="mt-2 rounded-none"
                    data-testid="transfer-to-input"
                    autoComplete="off"
                  />
                  {showUserDropdown && (
                    <div className="absolute z-50 left-0 right-0 bg-white border border-slate-200 shadow-md mt-1 max-h-48 overflow-y-auto">
                      {userResults.map((u) => (
                        <button
                          key={u.id}
                          type="button"
                          className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 border-b border-slate-100 last:border-0"
                          onMouseDown={(e) => { e.preventDefault(); selectUser(u); }}
                        >
                          <div className="font-medium text-slate-900">{u.name}</div>
                          <div className="text-xs text-slate-500">{[u.department, u.campus].filter(Boolean).join(" · ")}</div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Campus — locked for staff, select for admin */}
                <div>
                  <Label className="label-mono">{t("campus")}</Label>
                  {!isAdmin && user?.campus ? (
                    <div className="mt-2 px-3 py-2 border border-slate-200 bg-slate-50 text-sm text-slate-700 rounded-none">
                      {user.campus}
                    </div>
                  ) : (
                    <Select value={transferCampus} onValueChange={setTransferCampus}>
                      <SelectTrigger className="mt-2 rounded-none">
                        <SelectValue placeholder={t("select_campus")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="YPJ Kuala Kencana">YPJ Kuala Kencana</SelectItem>
                        <SelectItem value="YPJ Tembagapura">YPJ Tembagapura</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                </div>

                {/* Room — searchable autocomplete */}
                <div className="relative">
                  <Label className="label-mono">{t("col_room")}</Label>
                  <Input
                    value={transferRoom}
                    onChange={(e) => handleRoomSearch(e.target.value)}
                    onFocus={() => { if (transferRoom.trim()) { const q = transferRoom.toLowerCase(); const m = allRooms.filter((r) => r.toLowerCase().includes(q) && r !== transferRoom); setRoomResults(m); setShowRoomDropdown(m.length > 0); } }}
                    onBlur={() => setTimeout(() => setShowRoomDropdown(false), 150)}
                    placeholder={t("room_placeholder")}
                    className="mt-2 rounded-none"
                    autoComplete="off"
                    data-testid="transfer-room-input"
                  />
                  {showRoomDropdown && (
                    <div className="absolute z-50 left-0 right-0 bg-white border border-slate-200 shadow-md mt-1 max-h-40 overflow-y-auto">
                      {roomResults.map((r) => (
                        <button key={r} type="button"
                          className="w-full text-left px-3 py-2 text-sm text-slate-900 hover:bg-slate-50 border-b border-slate-100 last:border-0"
                          onMouseDown={(e) => { e.preventDefault(); selectRoom(r); }}>
                          {r}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Note */}
                <div>
                  <Label className="label-mono">{t("note")}</Label>
                  <Textarea value={transferNote} onChange={(e)=>setTransferNote(e.target.value)}
                    rows={2} className="mt-2 rounded-none" data-testid="transfer-note-input"/>
                </div>
              </div>
              <DialogFooter>
                <Button onClick={submitTransfer} className="rounded-none bg-slate-900" data-testid="submit-transfer-button">
                  {isAdmin ? t("confirm_transfer") : t("submit_request")}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>}

          {canActOnAsset && <Dialog open={loanOpen} onOpenChange={setLoanOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="rounded-none" data-testid="loan-request-button">
                <BookOpen className="w-4 h-4 mr-2" strokeWidth={1.75}/> {t("loan_request")}
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none">
              <DialogHeader>
                <DialogTitle>{t("loan_request_title")}</DialogTitle>
              </DialogHeader>
              <p className="text-sm text-slate-500">{t("loan_request_hint")}</p>
              <div className="space-y-4">
                <div>
                  <Label className="label-mono">{t("loan_purpose")}</Label>
                  <Textarea value={loanPurpose} onChange={(e) => setLoanPurpose(e.target.value)}
                    placeholder={t("loan_purpose_placeholder")} rows={2}
                    className="mt-2 rounded-none" data-testid="loan-purpose-input"/>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label className="label-mono">{t("loan_from_label")}</Label>
                    <Input type="date" value={loanStart} onChange={(e) => setLoanStart(e.target.value)}
                      className="mt-2 rounded-none" data-testid="loan-start-input"/>
                  </div>
                  <div>
                    <Label className="label-mono">{t("loan_until_label")}</Label>
                    <Input type="date" value={loanEnd} onChange={(e) => setLoanEnd(e.target.value)}
                      className="mt-2 rounded-none" data-testid="loan-end-input"/>
                  </div>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" className="rounded-none" onClick={() => setLoanOpen(false)}>
                  {t("cancel")}
                </Button>
                <Button onClick={submitLoanRequest} className="rounded-none bg-slate-900" data-testid="submit-loan-button">
                  {t("submit_request")}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>}

          {user?.role === "admin" && (
            <Link to={`/assets/${id}/edit`}>
              <Button variant="outline" className="rounded-none" data-testid="edit-asset-button">
                <Edit className="w-4 h-4 mr-2" strokeWidth={1.75}/> {t("edit")}
              </Button>
            </Link>
          )}
          {user?.role === "admin" && (
            <Button variant="outline" onClick={handleDelete}
              className="rounded-none text-rose-600 hover:text-rose-700" data-testid="delete-asset-button">
              <Trash2 className="w-4 h-4" strokeWidth={1.75}/>
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
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
            <div className="label-mono">{t("quick_facts")}</div>
            <Detail icon={Building2} label={t("campus")} value={asset.campus || "—"}/>
            <Detail icon={Building2} label={t("col_room")} value={asset.location}/>
            <Detail icon={UserIcon} label={t("assigned_to")} value={asset.assigned_to_name || "—"}/>
            <Detail icon={Calendar} label={t("purchased")} value={fmtDate(asset.purchase_date)}/>
            <Detail icon={ShieldCheck} label={t("warranty_until")} value={fmtDate(asset.warranty_end_date)}/>
          </div>

          <div className="bg-white border border-slate-200 p-6">
            <div className="label-mono mb-4">{t("depreciation")}</div>
            <div className="space-y-3">
              <Row label={t("purchase_price")} value={fmtCurrency(asset.purchase_price)}/>
              <Row label={t("annual_dep")} value={fmtCurrency(dep.annual)}/>
              <Row label={t("accumulated")} value={fmtCurrency(dep.accumulated)}/>
              <div className="border-t border-slate-200 pt-3">
                <Row label={t("current_book_value")} value={fmtCurrency(dep.current_value)} bold/>
              </div>
              <div className="text-xs text-slate-500">Age: {dep.age_years} yrs · {t("useful_life")}: {asset.useful_life_years} yrs</div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-2">
          <Tabs defaultValue="overview" className="bg-white border border-slate-200">
            <TabsList className="w-full justify-start rounded-none bg-slate-50 border-b border-slate-200 p-0 h-auto">
              <TabsTrigger value="overview" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-overview">{t("tab_overview")}</TabsTrigger>
              <TabsTrigger value="history" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-history">{t("tab_ownership")}</TabsTrigger>
              <TabsTrigger value="faults" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-faults">{t("tab_faults")} ({asset.faults?.length || 0})</TabsTrigger>
              <TabsTrigger value="docs" className="rounded-none data-[state=active]:bg-white data-[state=active]:border-b-2 data-[state=active]:border-blue-800 px-6 py-3" data-testid="tab-docs">{t("tab_documents")}</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="p-6">
              <dl className="grid grid-cols-2 gap-y-4">
                <Field label={t("cat_label")} value={asset.category}/>
                <Field label={t("col_status")} value={asset.status.replace("_", " ")}/>
                <Field label={t("serial_number")} value={asset.serial_number || "—"} mono/>
                <Field label={t("supplier")} value={asset.supplier || "—"}/>
                <Field label={t("useful_life")} value={`${asset.useful_life_years} yrs`}/>
                <Field label={t("created_label")} value={fmtDate(asset.created_at)}/>
              </dl>
            </TabsContent>

            <TabsContent value="history" className="p-6">
              {(!asset.ownership_history || asset.ownership_history.length === 0) ? (
                <div className="text-sm text-slate-500">{t("no_ownership")}</div>
              ) : (
                <ol className="relative border-l-2 border-slate-200 ml-2 space-y-6">
                  {asset.ownership_history.map((h) => (
                    <li key={h.id} className="pl-6 relative">
                      <div className="absolute -left-[7px] top-1 w-3 h-3 bg-blue-700"/>
                      <div className="text-sm font-medium text-slate-900">
                        {t("transferred_to")} <span className="text-blue-800">{h.to_name}</span>
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        {h.from_name || "—"} · {h.by_name} · {fmtDate(h.at)}
                      </div>
                      {h.note && <div className="text-sm text-slate-600 mt-2 italic">"{h.note}"</div>}
                    </li>
                  ))}
                </ol>
              )}
            </TabsContent>

            <TabsContent value="faults" className="p-6">
              {(!asset.faults || asset.faults.length === 0) ? (
                <div className="text-sm text-slate-500">{t("no_faults")}</div>
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
                        {f.reported_by_name} · {fmtDate(f.created_at)} · {t("severity")}: {f.severity}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            <TabsContent value="docs" className="p-6">
              {(!asset.documents || asset.documents.length === 0) ? (
                <div className="text-sm text-slate-500">{t("no_documents")}</div>
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
