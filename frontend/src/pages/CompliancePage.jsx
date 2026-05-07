import { useEffect, useState } from "react";
import api, { fmtDate, formatErr } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "../components/ui/dialog";
import { useAuth } from "../context/AuthContext";
import { toast } from "sonner";
import { Plus, ShieldCheck, Trash2 } from "lucide-react";

const STATUS_STYLES = {
  pending: "bg-amber-50 text-amber-700 border-amber-200",
  overdue: "bg-rose-50 text-rose-700 border-rose-200",
  completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

export default function CompliancePage() {
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
      toast.success("Compliance item created");
      setOpen(false);
      setForm({ title: "", description: "", category: "Safety", due_date: new Date().toISOString().split("T")[0], frequency: "annual" });
      load();
    } catch (err) { toast.error(formatErr(err)); }
  };

  const markComplete = async (c) => {
    try {
      await api.put(`/compliance/${c.id}`, { status: "completed" });
      toast.success("Marked complete");
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const remove = async (c) => {
    if (!window.confirm("Delete this compliance item?")) return;
    try {
      await api.delete(`/compliance/${c.id}`);
      load();
    } catch (e) { toast.error(formatErr(e)); }
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
          <div className="label-mono mb-2">Regulatory</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            Compliance checks
          </h1>
        </div>
        {isAdmin && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button className="rounded-none bg-slate-900 hover:bg-slate-800" data-testid="add-compliance-button">
                <Plus className="w-4 h-4 mr-2" strokeWidth={1.75}/> Add check
              </Button>
            </DialogTrigger>
            <DialogContent className="rounded-none max-w-md">
              <DialogHeader><DialogTitle>New compliance check</DialogTitle></DialogHeader>
              <form onSubmit={submit} className="space-y-4">
                <div><Label className="label-mono">Title</Label>
                  <Input required value={form.title} onChange={(e)=>setForm({...form, title: e.target.value})}
                    className="mt-2 rounded-none" data-testid="compliance-title-input"/></div>
                <div><Label className="label-mono">Description</Label>
                  <Textarea value={form.description} onChange={(e)=>setForm({...form, description: e.target.value})}
                    rows={2} className="mt-2 rounded-none"/></div>
                <div className="grid grid-cols-2 gap-3">
                  <div><Label className="label-mono">Category</Label>
                    <Select value={form.category} onValueChange={(v)=>setForm({...form, category: v})}>
                      <SelectTrigger className="mt-2 rounded-none"><SelectValue/></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Safety">Safety</SelectItem>
                        <SelectItem value="Inspection">Inspection</SelectItem>
                        <SelectItem value="Certification">Certification</SelectItem>
                        <SelectItem value="Audit">Audit</SelectItem>
                      </SelectContent>
                    </Select></div>
                  <div><Label className="label-mono">Frequency</Label>
                    <Select value={form.frequency} onValueChange={(v)=>setForm({...form, frequency: v})}>
                      <SelectTrigger className="mt-2 rounded-none"><SelectValue/></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="once">Once</SelectItem>
                        <SelectItem value="monthly">Monthly</SelectItem>
                        <SelectItem value="quarterly">Quarterly</SelectItem>
                        <SelectItem value="annual">Annual</SelectItem>
                      </SelectContent>
                    </Select></div>
                </div>
                <div><Label className="label-mono">Due date</Label>
                  <Input type="date" required value={form.due_date}
                    onChange={(e)=>setForm({...form, due_date: e.target.value})}
                    className="mt-2 rounded-none" data-testid="compliance-due-input"/></div>
                <DialogFooter>
                  <Button type="submit" className="rounded-none bg-slate-900" data-testid="submit-compliance-button">
                    Create
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : items.length === 0 ? (
        <div className="bg-white border border-slate-200 p-12 text-center">
          <ShieldCheck className="w-8 h-8 text-slate-300 mx-auto mb-3" strokeWidth={1.5}/>
          <div className="font-display text-lg text-slate-700">No compliance checks yet</div>
        </div>
      ) : (
        <div className="space-y-8">
          {grouped.overdue.length > 0 && (
            <Section title="Overdue" count={grouped.overdue.length} accent="text-rose-700">
              {grouped.overdue.map((c) => <Item key={c.id} c={c} onComplete={markComplete} onDelete={remove} canModify={isAdmin}/>)}
            </Section>
          )}
          {grouped.pending.length > 0 && (
            <Section title="Pending" count={grouped.pending.length} accent="text-amber-700">
              {grouped.pending.map((c) => <Item key={c.id} c={c} onComplete={markComplete} onDelete={remove} canModify={isAdmin}/>)}
            </Section>
          )}
          {grouped.completed.length > 0 && (
            <Section title="Completed" count={grouped.completed.length} accent="text-emerald-700">
              {grouped.completed.map((c) => <Item key={c.id} c={c} onComplete={markComplete} onDelete={remove} canModify={isAdmin}/>)}
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
        <span className="label-mono">{count} {count === 1 ? "item" : "items"}</span>
      </div>
      <div className="bg-white border border-slate-200 divide-y divide-slate-100">
        {children}
      </div>
    </section>
  );
}

function Item({ c, onComplete, onDelete, canModify }) {
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
          <span>Due {fmtDate(c.due_date)}</span>
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
              Mark complete
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
