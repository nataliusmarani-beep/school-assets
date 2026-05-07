import { useEffect, useState } from "react";
import api, { fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "../components/ui/dialog";
import { useAuth } from "../context/AuthContext";
import { toast } from "sonner";
import { Plus, ShieldCheck, Trash2 } from "lucide-react";

const STATUS_STYLES = {
  pending: "bg-amber-50 text-amber-700 border-amber-200",
  overdue: "bg-rose-50 text-rose-700 border-rose-200",
  completed: "bg-blue-50 text-blue-800 border-blue-200",
};

export default function CompliancePage() {
  const { t } = useLang();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const [form, setForm] = useState({
    title: "", description: "", category: "Safety",
    due_date: new Date().toISOString().split("T")[0], frequency: "annual",
  });

  const load = () => {
    setLoading(true);
    api.get("/compliance").then((r) => setItems(r.data)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.post("/compliance", { ...form, due_date: new Date(form.due_date).toISOString() });
      toast.success(t("compliance_created"));
      setOpen(false);
      setForm({ title: "", description: "", category: "Safety", due_date: new Date().toISOString().split("T")[0], frequency: "annual" });
      load();
    } catch (err) { toast.error(formatErr(err)); }
  };

  const markComplete = async (c) => {
    try {
      await api.put(`/compliance/${c.id}`, { status: "completed" });
      toast.success(t("completed"));
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const remove = async (c) => {
    if (!window.confirm(t("delete_compliance_confirm"))) return;
    try { await api.delete(`/compliance/${c.id}`); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };

  const grouped = {
    overdue: items.filter((c) => c.status === "overdue"),
    pending: items.filter((c) => c.status === "pending"),
    completed: items.filter((c) => c.status === "completed"),
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="compliance-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="label-mono mb-2">{t("regulatory")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            {t("compliance_checks")}
          </h1>
        </div>
        {isAdmin && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button className="rounded-none bg-slate-900 hover:bg-slate-800" data-testid="add-compliance-button">
                <Plus className="w-4 h-4 mr-2" strokeWidth={1.75}/> {t("add_check")}
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none max-w-md">
              <DialogHeader><DialogTitle>{t("new_check")}</DialogTitle></DialogHeader>
              <form onSubmit={submit} className="space-y-4">
                <div><Label className="label-mono">{t("title_label")}</Label>
                  <Input required value={form.title} onChange={(e)=>setForm({...form,title:e.target.value})}
                    className="mt-2 rounded-none" data-testid="compliance-title-input"/></div>
                <div><Label className="label-mono">{t("description")}</Label>
                  <Textarea value={form.description} onChange={(e)=>setForm({...form,description:e.target.value})}
                    rows={2} className="mt-2 rounded-none"/></div>
                <div className="grid grid-cols-2 gap-3">
                  <div><Label className="label-mono">{t("col_category")}</Label>
                    <Select value={form.category} onValueChange={(v)=>setForm({...form,category:v})}>
                      <SelectTrigger className="mt-2 rounded-none"><SelectValue/></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Safety">{t("cat_safety")}</SelectItem>
                        <SelectItem value="Inspection">{t("cat_inspection")}</SelectItem>
                        <SelectItem value="Certification">{t("cat_certification")}</SelectItem>
                        <SelectItem value="Audit">{t("cat_audit")}</SelectItem>
                      </SelectContent>
                    </Select></div>
                  <div><Label className="label-mono">{t("frequency")}</Label>
                    <Select value={form.frequency} onValueChange={(v)=>setForm({...form,frequency:v})}>
                      <SelectTrigger className="mt-2 rounded-none"><SelectValue/></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="once">{t("freq_once")}</SelectItem>
                        <SelectItem value="monthly">{t("freq_monthly")}</SelectItem>
                        <SelectItem value="quarterly">{t("freq_quarterly")}</SelectItem>
                        <SelectItem value="annual">{t("freq_annual")}</SelectItem>
                      </SelectContent>
                    </Select></div>
                </div>
                <div><Label className="label-mono">{t("due_date")}</Label>
                  <Input type="date" required value={form.due_date}
                    onChange={(e)=>setForm({...form,due_date:e.target.value})}
                    className="mt-2 rounded-none" data-testid="compliance-due-input"/></div>
                <DialogFooter>
                  <Button type="submit" className="rounded-none bg-slate-900" data-testid="submit-compliance-button">
                    {t("create")}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-slate-500">{t("loading")}</div>
      ) : items.length === 0 ? (
        <div className="bg-white border border-slate-200 p-12 text-center">
          <ShieldCheck className="w-8 h-8 text-slate-300 mx-auto mb-3" strokeWidth={1.5}/>
          <div className="font-display text-lg text-slate-700">{t("no_checks")}</div>
        </div>
      ) : (
        <div className="space-y-8">
          {grouped.overdue.length > 0 && (
            <Section title={t("overdue")} count={grouped.overdue.length} accent="text-rose-700" t={t}>
              {grouped.overdue.map((c) => <Item key={c.id} c={c} onComplete={markComplete} onDelete={remove} canModify={isAdmin} t={t}/>)}
            </Section>
          )}
          {grouped.pending.length > 0 && (
            <Section title={t("pending")} count={grouped.pending.length} accent="text-amber-700" t={t}>
              {grouped.pending.map((c) => <Item key={c.id} c={c} onComplete={markComplete} onDelete={remove} canModify={isAdmin} t={t}/>)}
            </Section>
          )}
          {grouped.completed.length > 0 && (
            <Section title={t("completed")} count={grouped.completed.length} accent="text-blue-800" t={t}>
              {grouped.completed.map((c) => <Item key={c.id} c={c} onComplete={markComplete} onDelete={remove} canModify={isAdmin} t={t}/>)}
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, count, accent, children }) {
  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <h2 className={`font-display text-lg font-medium ${accent}`}>{title}</h2>
        <span className="label-mono">{count}</span>
      </div>
      <div className="bg-white border border-slate-200 divide-y divide-slate-100">{children}</div>
    </section>
  );
}

function Item({ c, onComplete, onDelete, canModify, t }) {
  return (
    <div className="p-5 flex items-start gap-4 flex-wrap" data-testid={`compliance-row-${c.id}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="font-medium text-slate-900">{c.title}</div>
          <span className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 border ${STATUS_STYLES[c.status]}`}>
            {c.status}
          </span>
          <span className="label-mono">{c.category}</span>
        </div>
        {c.description && <div className="text-sm text-slate-600 mt-1">{c.description}</div>}
        <div className="text-xs text-slate-500 mt-2 flex items-center gap-3 flex-wrap">
          <span>{fmtDate(c.due_date)}</span>
          <span>·</span>
          <span className="capitalize">{c.frequency}</span>
          {c.asset_name && (<><span>·</span><span>{c.asset_name}</span></>)}
        </div>
      </div>
      {canModify && (
        <div className="flex items-center gap-2">
          {c.status !== "completed" && (
            <Button size="sm" variant="outline" className="rounded-none"
              onClick={() => onComplete(c)} data-testid={`compliance-complete-${c.id}`}>
              {t("mark_complete")}
            </Button>
          )}
          <Button size="sm" variant="outline" className="rounded-none text-rose-600"
            onClick={() => onDelete(c)} data-testid={`compliance-delete-${c.id}`}>
            <Trash2 className="w-3.5 h-3.5"/>
          </Button>
        </div>
      )}
    </div>
  );
}
