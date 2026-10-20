import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { isCampusBound } from "../lib/roles";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { campusLabel } from "../lib/campus";

const CAMPUSES = ["YPJ Kuala Kencana", "YPJ TPRA"];
const KINDS = ["laptop_cart", "ipad_cart", "computer_lab", "room"];
const ICT_CATEGORIES = ["IT Equipment", "AV Equipment", "Music Equipment"];
const DAYS = ["sc_mon", "sc_tue", "sc_wed", "sc_thu", "sc_fri", "sc_sat", "sc_sun"];
const SEL = "mt-2 w-full border border-slate-200 bg-white px-3 py-2 text-sm rounded-none h-10";

function Section({ title, hint, children }) {
  return <div className="bg-white border border-slate-200 p-5 mb-6"><div className="label-mono mb-1">{title}</div>{hint && <p className="text-xs text-slate-500 mb-4">{hint}</p>}{children}</div>;
}

/* ---------- most laptops / iPads one teacher request may ask for ---------- */
function PoolLimit({ campus, t }) {
  const [policy, setPolicy] = useState(null);
  const [val, setVal] = useState("10");
  useEffect(() => {
    api.get("/loans/policies").then((r) => {
      const rows = r.data.filter((x) => x.category === "IT Equipment");
      const p = rows.find((x) => x.campus === campus) || rows.find((x) => x.campus === "") || null;
      setPolicy(p); setVal(String(p?.max_units ?? 10));
    }).catch(() => {});
  }, [campus]);
  const save = async () => {
    try {
      const base = policy || { max_loan_days: 1, requires_approval: 1, can_leave_campus: 0, min_notice_days: 1, max_advance_days: 14 };
      const r = await api.put("/loans/policies", {
        campus, category: "IT Equipment", max_loan_days: base.max_loan_days, requires_approval: !!base.requires_approval,
        can_leave_campus: !!base.can_leave_campus, min_notice_days: base.min_notice_days, max_advance_days: base.max_advance_days, max_units: Number(val),
      });
      setPolicy(r.data); toast.success(t("ln_saved"));
    } catch (e) { toast.error(formatErr(e)); }
  };
  return (
    <Section title={t("pool_limit_title")} hint={t("pool_limit_hint")}>
      <div className="flex items-end gap-3">
        <div><Label className="label-mono">{t("pool_max_per_request")}</Label>
          <Input type="number" min="1" className="mt-2 rounded-none w-32" value={val} onChange={(e) => setVal(e.target.value)} data-testid="pool-limit-input" /></div>
        <Button className="rounded-none" disabled={!(Number(val) >= 1)} onClick={save} data-testid="pool-limit-save">{t("save_changes")}</Button>
      </div>
    </Section>
  );
}

/* ---------- carts & labs ---------- */
function ResourcesTab({ campus, t, load, resources }) {
  const empty = { name: "", kind: "laptop_cart", category: "IT Equipment", capacity: 30, location: "", unit: "SD", active: true };
  const [form, setForm] = useState(empty);
  const [edit, setEdit] = useState(null);
  const [members, setMembers] = useState(null);     // { resource, assets, selected:Set, q }

  const create = async () => {
    try { await api.post("/loans/resources", { ...form, campus, capacity: Number(form.capacity) }); setForm(empty); toast.success(t("ln_saved")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };
  const saveEdit = async () => {
    try { await api.put(`/loans/resources/${edit.id}`, { ...edit, capacity: Number(edit.capacity) }); setEdit(null); toast.success(t("ln_saved")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };
  const openMembers = async (r) => {
    try {
      const [all, cur] = await Promise.all([api.get("/assets", { params: { campus: r.campus, category: r.category } }), api.get(`/loans/resources/${r.id}/units`)]);
      setMembers({ resource: r, assets: all.data, selected: new Set(cur.data.map((u) => u.id)), q: "" });
    } catch (e) { toast.error(formatErr(e)); }
  };
  const saveMembers = async () => {
    try { await api.put(`/loans/resources/${members.resource.id}/units`, { asset_ids: [...members.selected] }); setMembers(null); toast.success(t("ln_saved")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };
  const shown = members ? members.assets.filter((a) => `${a.name} ${a.asset_tag}`.toLowerCase().includes(members.q.toLowerCase())) : [];

  return (
    <>
      <PoolLimit campus={campus} t={t} />
      <Section title={t("su_add_resource")} hint={t("su_resource_hint")}>
        <div className="grid sm:grid-cols-6 gap-3">
          <div className="sm:col-span-2"><Label className="label-mono">{t("su_name")}</Label><Input className="mt-2 rounded-none" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Laptop Cart A" data-testid="resource-name" /></div>
          <div><Label className="label-mono">{t("su_kind")}</Label><select className={SEL} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{t(`su_kind_${k}`)}</option>)}</select></div>
          <div><Label className="label-mono">{t("su_category")}</Label><select className={SEL} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{ICT_CATEGORIES.map((k) => <option key={k}>{k}</option>)}</select></div>
          <div><Label className="label-mono">{t("su_school_unit")}</Label><select className={SEL} value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} data-testid="resource-unit">{SCHOOL_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select></div>
          <div><Label className="label-mono">{t("su_capacity")}</Label><Input type="number" min="1" className="mt-2 rounded-none" value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} /></div>
        </div>
        <Button className="rounded-none mt-4" disabled={!form.name.trim()} onClick={create} data-testid="resource-create"><Plus className="w-4 h-4 mr-1" /> {t("su_add")}</Button>
      </Section>
      <div className="bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm"><thead><tr className="border-b border-slate-200 text-left">
          {["su_name", "su_kind", "su_school_unit", "su_category", "su_units", "su_capacity", ""].map((k, i) => <th key={i} className="label-mono py-3 px-4">{k && t(k)}</th>)}</tr></thead>
          <tbody>{resources.map((r) => (
            <tr key={r.id} className="border-b border-slate-100" data-testid={`resource-${r.name}`}>
              <td className="py-3 px-4 font-medium">{r.name}{!r.active && <span className="ml-2 text-xs text-slate-400">({t("su_inactive")})</span>}</td>
              <td className="py-3 px-4">{t(`su_kind_${r.kind}`)}</td><td className="py-3 px-4">{r.unit || "—"}</td><td className="py-3 px-4">{r.category}</td>
              <td className="py-3 px-4">{r.unit_count}</td><td className="py-3 px-4">{r.effective_capacity}</td>
              <td className="py-3 px-4 text-right whitespace-nowrap">
                <Button size="sm" variant="outline" className="rounded-none mr-2" onClick={() => openMembers(r)} data-testid={`resource-units-${r.name}`}>{t("su_units_edit")}</Button>
                <Button size="sm" variant="outline" className="rounded-none" onClick={() => setEdit({ ...r })}>{t("edit")}</Button></td>
            </tr>))}
            {resources.length === 0 && <tr><td colSpan="7" className="py-8 text-center text-slate-500">{t("sc_no_resources")}</td></tr>}</tbody></table>
      </div>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent className="rounded-none max-w-md"><DialogHeader><DialogTitle>{t("edit")}</DialogTitle></DialogHeader>
          {edit && <div className="space-y-3">
            <div><Label className="label-mono">{t("su_name")}</Label><Input className="mt-2 rounded-none" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label className="label-mono">{t("su_kind")}</Label><select className={SEL} value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{t(`su_kind_${k}`)}</option>)}</select></div>
              <div><Label className="label-mono">{t("su_school_unit")}</Label><select className={SEL} value={edit.unit || ""} onChange={(e) => setEdit({ ...edit, unit: e.target.value })}><option value="">—</option>{SCHOOL_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select></div>
              <div><Label className="label-mono">{t("su_capacity")}</Label><Input type="number" min="1" className="mt-2 rounded-none" value={edit.capacity} onChange={(e) => setEdit({ ...edit, capacity: e.target.value })} /></div>
            </div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} /> {t("su_active")}</label>
          </div>}
          <DialogFooter><Button className="rounded-none" onClick={saveEdit}>{t("save_changes")}</Button></DialogFooter></DialogContent>
      </Dialog>

      <Dialog open={!!members} onOpenChange={(o) => !o && setMembers(null)}>
        <DialogContent className="rounded-none max-w-lg max-h-[90vh] overflow-y-auto" data-testid="units-dialog">
          <DialogHeader><DialogTitle>{t("su_units_edit")}: {members?.resource.name}</DialogTitle></DialogHeader>
          {members && <>
            <Input className="rounded-none" placeholder={t("ln_search")} value={members.q} onChange={(e) => setMembers({ ...members, q: e.target.value })} />
            <div className="text-xs text-slate-500">{members.selected.size} {t("su_selected")}</div>
            <div className="border border-slate-200 max-h-72 overflow-y-auto divide-y divide-slate-100">
              {shown.map((a) => (
                <label key={a.id} className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer hover:bg-slate-50">
                  <input type="checkbox" checked={members.selected.has(a.id)} data-testid={`unit-${a.asset_tag}`} onChange={(e) => {
                    const s = new Set(members.selected); e.target.checked ? s.add(a.id) : s.delete(a.id); setMembers({ ...members, selected: s });
                  }} /> <span className="flex-1 truncate">{a.name}</span><span className="font-mono text-xs text-slate-400">{a.asset_tag}</span>
                </label>))}
              {shown.length === 0 && <div className="p-4 text-sm text-slate-500">{t("ln_empty")}</div>}
            </div>
          </>}
          <DialogFooter><Button className="rounded-none" onClick={saveMembers} data-testid="units-save">{t("save_changes")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/* ---------- lesson periods ---------- */
const SCHOOL_UNITS = ["PAUD", "SD", "SMP"];
function PeriodsTab({ campus, t }) {
  const [unit, setUnit] = useState("SD");
  const [rows, setRows] = useState([]);
  const load = useCallback(() => {
    api.get("/loans/periods", { params: { campus } }).then((r) => setRows(r.data.filter((p) => p.campus === campus && (p.unit || "") === unit))).catch((e) => toast.error(formatErr(e)));
  }, [campus, unit]);
  useEffect(() => { load(); }, [load]);
  const upd = (i, patch) => setRows(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const save = async () => {
    try { await api.put("/loans/periods", { campus, unit, periods: rows.map((r) => ({ period_no: Number(r.period_no), start_time: r.start_time, end_time: r.end_time })) }); toast.success(t("ln_saved")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };
  return (
    <Section title={t("su_tab_periods")} hint={t("su_periods_hint")}>
      <div className="flex gap-1 mb-4" data-testid="period-unit-tabs">
        {SCHOOL_UNITS.map((u) => <button key={u} onClick={() => setUnit(u)} data-testid={`period-unit-${u}`}
          className={`px-4 py-1.5 text-sm border ${unit === u ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>{u}</button>)}
      </div>
      <div className="space-y-2 max-w-xl">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input type="number" min="1" className="w-20 rounded-none" value={r.period_no} onChange={(e) => upd(i, { period_no: e.target.value })} data-testid={`period-no-${i}`} />
            <Input type="time" className="rounded-none" value={r.start_time} onChange={(e) => upd(i, { start_time: e.target.value })} data-testid={`period-start-${i}`} />
            <span>–</span>
            <Input type="time" className="rounded-none" value={r.end_time} onChange={(e) => upd(i, { end_time: e.target.value })} data-testid={`period-end-${i}`} />
            <Button size="icon" variant="ghost" onClick={() => setRows(rows.filter((_, k) => k !== i))}><Trash2 className="w-4 h-4 text-slate-400" /></Button>
          </div>))}
      </div>
      <div className="flex gap-2 mt-4">
        <Button variant="outline" className="rounded-none" data-testid="period-add" onClick={() => setRows([...rows, { period_no: (rows.at(-1)?.period_no || 0) + 1, start_time: rows.at(-1)?.end_time || "07:30", end_time: "" }])}><Plus className="w-4 h-4 mr-1" /> {t("su_add")}</Button>
        <Button className="rounded-none" onClick={save} data-testid="periods-save">{t("save_changes")}</Button>
      </div>
    </Section>
  );
}

/* ---------- holidays ---------- */
const dayAfter = (iso) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10); };
function HolidaysTab({ campus, t, canAll }) {
  const [rows, setRows] = useState([]);
  const [f, setF] = useState({ date: "", end_date: "", name: "", all: false });
  const load = useCallback(() => { api.get("/loans/holidays", { params: { campus } }).then((r) => setRows(r.data)).catch((e) => toast.error(formatErr(e))); }, [campus]);
  useEffect(() => { load(); }, [load]);
  // one row per day in the database; consecutive days with the same name and campus are shown as one range
  const ranges = useMemo(() => {
    const out = [];
    [...rows].sort((a, b) => a.date.localeCompare(b.date)).forEach((h) => {
      const last = out[out.length - 1];
      if (last && last.campus === h.campus && last.name === h.name && dayAfter(last.end) === h.date) { last.end = h.date; last.ids.push(h.id); }
      else out.push({ campus: h.campus, name: h.name, start: h.date, end: h.date, ids: [h.id] });
    });
    return out;
  }, [rows]);
  const add = async () => {
    try { await api.post("/loans/holidays", { campus: f.all ? "" : campus, date: f.date, end_date: f.end_date || null, name: f.name }); setF({ date: "", end_date: "", name: "", all: false }); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };
  const del = async (ids) => { try { await Promise.all(ids.map((id) => api.delete(`/loans/holidays/${id}`))); load(); } catch (e) { toast.error(formatErr(e)); load(); } };
  return (
    <Section title={t("su_tab_holidays")} hint={t("su_holidays_hint")}>
      <div className="flex gap-2 flex-wrap items-end mb-4">
        <div><Label className="label-mono">{t("su_start_date")}</Label><Input type="date" className="mt-2 rounded-none" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value, end_date: f.end_date && f.end_date < e.target.value ? e.target.value : f.end_date })} data-testid="holiday-date" /></div>
        <div><Label className="label-mono">{t("su_end_date")}</Label><Input type="date" className="mt-2 rounded-none" min={f.date} value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} data-testid="holiday-end-date" /></div>
        <div className="flex-1 min-w-[180px]"><Label className="label-mono">{t("su_name")}</Label><Input className="mt-2 rounded-none" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="holiday-name" /></div>
        {canAll && <label className="flex items-center gap-2 text-sm pb-2"><input type="checkbox" checked={f.all} onChange={(e) => setF({ ...f, all: e.target.checked })} /> {t("su_all_campuses")}</label>}
        <Button className="rounded-none" disabled={!f.date} onClick={add} data-testid="holiday-add"><Plus className="w-4 h-4 mr-1" /> {t("su_add")}</Button>
      </div>
      <div className="divide-y divide-slate-100 border border-slate-200">
        {ranges.map((h) => (
          <div key={h.ids[0]} className="flex items-center justify-between px-3 py-2 text-sm"><span><span className="font-mono">{h.start === h.end ? h.start : `${h.start} → ${h.end}`}</span> · {h.name || "—"} {!h.campus && <span className="text-xs text-slate-400">({t("su_all_campuses")})</span>}</span>
            <Button size="icon" variant="ghost" onClick={() => del(h.ids)}><Trash2 className="w-4 h-4 text-slate-400" /></Button></div>))}
        {ranges.length === 0 && <div className="p-4 text-sm text-slate-500">{t("ln_empty")}</div>}
      </div>
    </Section>
  );
}

/* ---------- fixed schedules ---------- */
function SchedulesTab({ campus, t, resources }) {
  const empty = { resource_id: "", academic_year: "2026-2027", semester: "Ganjil", class_name: "", subject: "", teacher_name: "", weekday: 0, period_from: 1, period_to: 1, units: 1, valid_from: "", valid_to: "" };
  const [rows, setRows] = useState([]);
  const [f, setF] = useState(empty);
  const [err, setErr] = useState("");
  const load = useCallback(() => { api.get("/loans/schedules", { params: { campus } }).then((r) => setRows(r.data)).catch((e) => toast.error(formatErr(e))); }, [campus]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!f.resource_id && resources.length) setF((p) => ({ ...p, resource_id: resources[0].id })); }, [resources]);   // eslint-disable-line react-hooks/exhaustive-deps
  const num = (v) => Number(v);
  const body = (x) => ({ ...x, weekday: num(x.weekday), period_from: num(x.period_from), period_to: num(x.period_to), units: num(x.units) });
  const add = async () => {
    setErr("");
    try { await api.post("/loans/schedules", body(f)); toast.success(t("ln_saved")); setF({ ...empty, resource_id: f.resource_id, valid_from: f.valid_from, valid_to: f.valid_to }); load(); }
    catch (e) { setErr(formatErr(e)); }
  };
  const cancel = async (s) => {
    try { await api.put(`/loans/schedules/${s.id}`, body({ ...s, status: "cancelled" })); load(); } catch (e) { toast.error(formatErr(e)); }
  };
  const delEx = async (s, e) => { try { await api.delete(`/loans/schedules/${s.id}/exceptions/${e.id}`); load(); } catch (er) { toast.error(formatErr(er)); } };
  return (
    <>
      <Section title={t("su_add_schedule")} hint={t("su_schedule_hint")}>
        <div className="grid sm:grid-cols-4 gap-3">
          <div className="sm:col-span-2"><Label className="label-mono">{t("su_resource")}</Label><select className={SEL} value={f.resource_id} onChange={(e) => setF({ ...f, resource_id: e.target.value })} data-testid="sch-resource">{resources.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select></div>
          <div><Label className="label-mono">{t("su_year")}</Label><Input className="mt-2 rounded-none" value={f.academic_year} onChange={(e) => setF({ ...f, academic_year: e.target.value })} /></div>
          <div><Label className="label-mono">{t("su_semester")}</Label><select className={SEL} value={f.semester} onChange={(e) => setF({ ...f, semester: e.target.value })}><option>Ganjil</option><option>Genap</option></select></div>
          <div><Label className="label-mono">{t("ln_class")} *</Label><Input className="mt-2 rounded-none" value={f.class_name} onChange={(e) => setF({ ...f, class_name: e.target.value })} data-testid="sch-class" /></div>
          <div><Label className="label-mono">{t("ln_subject")}</Label><Input className="mt-2 rounded-none" value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} /></div>
          <div className="sm:col-span-2"><Label className="label-mono">{t("su_teacher")}</Label><Input className="mt-2 rounded-none" value={f.teacher_name} onChange={(e) => setF({ ...f, teacher_name: e.target.value })} data-testid="sch-teacher" /></div>
          <div><Label className="label-mono">{t("su_weekday")}</Label><select className={SEL} value={f.weekday} onChange={(e) => setF({ ...f, weekday: e.target.value })} data-testid="sch-weekday">{DAYS.map((d, i) => <option key={d} value={i}>{t(d)}</option>)}</select></div>
          <div><Label className="label-mono">{t("su_period_from")}</Label><Input type="number" min="1" className="mt-2 rounded-none" value={f.period_from} onChange={(e) => setF({ ...f, period_from: e.target.value })} data-testid="sch-from" /></div>
          <div><Label className="label-mono">{t("su_period_to")}</Label><Input type="number" min="1" className="mt-2 rounded-none" value={f.period_to} onChange={(e) => setF({ ...f, period_to: e.target.value })} data-testid="sch-to" /></div>
          <div><Label className="label-mono">{t("ln_units")}</Label><Input type="number" min="1" className="mt-2 rounded-none" value={f.units} onChange={(e) => setF({ ...f, units: e.target.value })} data-testid="sch-units" /></div>
          <div><Label className="label-mono">{t("su_valid_from")}</Label><Input type="date" className="mt-2 rounded-none" value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} data-testid="sch-valid-from" /></div>
          <div><Label className="label-mono">{t("su_valid_to")}</Label><Input type="date" className="mt-2 rounded-none" value={f.valid_to} onChange={(e) => setF({ ...f, valid_to: e.target.value })} data-testid="sch-valid-to" /></div>
        </div>
        {err && <div className="mt-3 text-sm text-rose-700 border border-rose-200 bg-rose-50 p-3" data-testid="sch-error">{err}</div>}
        <Button className="rounded-none mt-4" disabled={!f.resource_id || !f.class_name.trim() || !f.valid_from || !f.valid_to} onClick={add} data-testid="sch-add"><Plus className="w-4 h-4 mr-1" /> {t("su_add")}</Button>
      </Section>
      <div className="bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm"><thead><tr className="border-b border-slate-200 text-left">
          {["su_resource", "ln_class", "su_teacher", "su_weekday", "sc_period", "ln_units", "su_valid", ""].map((k, i) => <th key={i} className="label-mono py-3 px-4">{k && t(k)}</th>)}</tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.id} className={`border-b border-slate-100 align-top ${s.status === "cancelled" ? "opacity-50" : ""}`}>
              <td className="py-3 px-4">{s.resource_name}</td>
              <td className="py-3 px-4">{s.class_name}<div className="text-xs text-slate-500">{s.subject}</div></td>
              <td className="py-3 px-4">{s.teacher_name}</td><td className="py-3 px-4">{t(DAYS[s.weekday])}</td>
              <td className="py-3 px-4">{s.period_from}–{s.period_to}</td><td className="py-3 px-4">{s.units}</td>
              <td className="py-3 px-4 text-xs">{s.valid_from} → {s.valid_to}
                {s.exceptions.map((e) => <div key={e.id} className="text-slate-500">{t("sc_holiday")} {e.date} <button className="underline ml-1" onClick={() => delEx(s, e)}>{t("su_restore")}</button></div>)}</td>
              <td className="py-3 px-4 text-right">{s.status === "active" ? <Button size="sm" variant="outline" className="rounded-none" onClick={() => cancel(s)}>{t("ln_act_cancel")}</Button> : <span className="text-xs text-slate-400">{t("ln_st_cancelled")}</span>}</td>
            </tr>))}
            {rows.length === 0 && <tr><td colSpan="8" className="py-8 text-center text-slate-500">{t("ln_empty")}</td></tr>}</tbody></table>
      </div>
    </>
  );
}

/* ---------- unit <-> student pairing ---------- */
function PairingsTab({ t, resources }) {
  const [rid, setRid] = useState("");
  const [year, setYear] = useState("2026-2027");
  const [semester, setSemester] = useState("Ganjil");
  const [units, setUnits] = useState([]);
  const [pairs, setPairs] = useState({});
  const [paste, setPaste] = useState("");
  useEffect(() => { if (!rid && resources.length) setRid(resources[0].id); }, [resources, rid]);
  const load = useCallback(async () => {
    if (!rid) return;
    try {
      const [u, p] = await Promise.all([api.get(`/loans/resources/${rid}/units`), api.get(`/loans/resources/${rid}/pairings`, { params: { academic_year: year, semester } })]);
      setUnits(u.data);
      setPairs(Object.fromEntries(p.data.map((x) => [x.asset_id, x])));
    } catch (e) { toast.error(formatErr(e)); }
  }, [rid, year, semester]);
  useEffect(() => { load(); }, [load]);
  const upd = (aid, patch) => setPairs({ ...pairs, [aid]: { ...(pairs[aid] || { asset_id: aid, class_name: "", student_name: "", student_no: "" }), ...patch } });
  const save = async () => {
    try { await api.put(`/loans/resources/${rid}/pairings`, { academic_year: year, semester, items: units.map((u) => ({ asset_id: u.id, class_name: "", student_name: "", student_no: "", ...(pairs[u.id] || {}) })) }); toast.success(t("ln_saved")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };
  // pasted lines "class,no,name" are matched to units in tag order
  const applyPaste = () => {
    const lines = paste.split("\n").map((l) => l.trim()).filter(Boolean);
    const next = { ...pairs };
    lines.forEach((line, i) => {
      const [cls, no, ...nm] = line.split(/[,;\t]/).map((x) => x.trim());
      if (units[i]) next[units[i].id] = { asset_id: units[i].id, class_name: cls || "", student_no: no || "", student_name: nm.join(" ") };
    });
    setPairs(next); setPaste("");
  };
  return (
    <Section title={t("su_tab_pairings")} hint={t("su_pairings_hint")}>
      <div className="flex gap-3 flex-wrap mb-4">
        <select className={`${SEL} !w-64`} value={rid} onChange={(e) => setRid(e.target.value)} data-testid="pair-resource">{resources.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select>
        <Input className="w-32 rounded-none mt-2" value={year} onChange={(e) => setYear(e.target.value)} />
        <select className={`${SEL} !w-32`} value={semester} onChange={(e) => setSemester(e.target.value)}><option>Ganjil</option><option>Genap</option></select>
      </div>
      <details className="mb-4 text-sm"><summary className="cursor-pointer text-blue-700">{t("su_paste")}</summary>
        <textarea className="w-full border border-slate-200 p-2 mt-2 text-xs font-mono" rows={4} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder={"7A, 1, Ani\n7A, 2, Budi"} />
        <Button size="sm" variant="outline" className="rounded-none mt-2" onClick={applyPaste}>{t("su_apply")}</Button></details>
      <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left border-b border-slate-200">
        {["ln_asset", "ln_class", "su_roll", "su_student"].map((k) => <th key={k} className="label-mono py-2 px-2">{t(k)}</th>)}</tr></thead>
        <tbody>{units.map((u) => { const p = pairs[u.id] || {}; return (
          <tr key={u.id} className="border-b border-slate-100">
            <td className="py-2 px-2 whitespace-nowrap">{u.name} <span className="font-mono text-xs text-slate-400">{u.asset_tag}</span></td>
            <td className="py-1 px-2"><Input className="rounded-none h-8 w-24" value={p.class_name || ""} onChange={(e) => upd(u.id, { class_name: e.target.value })} /></td>
            <td className="py-1 px-2"><Input className="rounded-none h-8 w-20" value={p.student_no || ""} onChange={(e) => upd(u.id, { student_no: e.target.value })} data-testid={`pair-no-${u.asset_tag}`} /></td>
            <td className="py-1 px-2"><Input className="rounded-none h-8" value={p.student_name || ""} onChange={(e) => upd(u.id, { student_name: e.target.value })} data-testid={`pair-name-${u.asset_tag}`} /></td>
          </tr>); })}
          {units.length === 0 && <tr><td colSpan="4" className="py-6 text-center text-slate-500">{t("su_no_units")}</td></tr>}</tbody></table></div>
      <Button className="rounded-none mt-4" disabled={!units.length} onClick={save} data-testid="pairings-save">{t("save_changes")}</Button>
    </Section>
  );
}

export default function LoanSetupPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const own = user?.campus && CAMPUSES.includes(user.campus) ? user.campus : "";
  const fixedCampus = isCampusBound(user?.role);
  const [campus, setCampus] = useState(own || CAMPUSES[0]);
  const [tab, setTab] = useState("resources");
  const [resources, setResources] = useState([]);
  const loadRes = useCallback(() => { api.get("/loans/resources", { params: { campus } }).then((r) => setResources(r.data)).catch((e) => toast.error(formatErr(e))); }, [campus]);
  useEffect(() => { loadRes(); }, [loadRes]);
  const tabs = useMemo(() => [["resources", "su_tab_resources"], ["periods", "su_tab_periods"], ["holidays", "su_tab_holidays"], ["schedules", "su_tab_schedules"], ["pairings", "su_tab_pairings"]], []);
  const activeRes = resources.filter((r) => r.active);

  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto" data-testid="loan-setup-page">
      <Link to="/schedule" className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1 mb-4"><ArrowLeft className="w-4 h-4" /> {t("sc_title")}</Link>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div><div className="label-mono mb-2">{t("ln_kicker")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">{t("sc_setup")}</h1></div>
        <select className={`${SEL} !w-56`} value={campus} disabled={fixedCampus} onChange={(e) => setCampus(e.target.value)} data-testid="setup-campus">
          {CAMPUSES.map((c) => <option key={c} value={c}>{campusLabel(c)}</option>)}</select>
      </div>
      <div className="flex gap-1 border-b border-slate-200 mt-6 mb-6 overflow-x-auto">
        {tabs.map(([id, key]) => <button key={id} onClick={() => setTab(id)} data-testid={`setup-tab-${id}`}
          className={`px-4 py-2 text-sm border-b-2 -mb-px whitespace-nowrap ${tab === id ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{t(key)}</button>)}
      </div>
      {tab === "resources" && <ResourcesTab campus={campus} t={t} load={loadRes} resources={resources} />}
      {tab === "periods" && <PeriodsTab campus={campus} t={t} />}
      {tab === "holidays" && <HolidaysTab campus={campus} t={t} canAll={["super_admin", "admin"].includes(user?.role)} />}
      {tab === "schedules" && <SchedulesTab campus={campus} t={t} resources={activeRes} />}
      {tab === "pairings" && <PairingsTab t={t} resources={activeRes} />}
    </div>
  );
}
