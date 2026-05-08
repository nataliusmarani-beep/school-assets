import { useEffect, useState } from "react";
import api, { fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
import { Plus, Trash2, Pencil } from "lucide-react";

const EMPTY_FORM = { name: "", email: "", password: "", role: "staff", department: "", campus: "", supervisor_name: "", supervisor: "", employee_id: "" };
const EMPTY_EDIT = { name: "", email: "", role: "staff", department: "", campus: "", supervisor_name: "", supervisor: "", employee_id: "", password: "" };

/* Free-text field with dropdown suggestions from a string list */
function SuggestField({ value, onChange, suggestions, placeholder, className = "", required = false, testid }) {
  const [show, setShow] = useState(false);
  const results = suggestions.filter((s) => s.toLowerCase().includes(value.toLowerCase()) && s !== value).slice(0, 8);
  return (
    <div className="relative">
      <Input
        required={required}
        value={value}
        placeholder={placeholder}
        onChange={(e) => { onChange(e.target.value); setShow(true); }}
        onFocus={() => setShow(true)}
        onBlur={() => setTimeout(() => setShow(false), 150)}
        className={`mt-2 rounded-none ${className}`}
        autoComplete="off"
        data-testid={testid}
      />
      {show && results.length > 0 && (
        <div className="absolute z-50 left-0 right-0 bg-white border border-slate-200 shadow-md mt-1 max-h-40 overflow-y-auto">
          {results.map((s) => (
            <button key={s} type="button"
              className="w-full text-left px-3 py-2 text-sm text-slate-900 hover:bg-slate-50 border-b border-slate-100 last:border-0"
              onMouseDown={(e) => { e.preventDefault(); onChange(s); setShow(false); }}>
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* Supervisor name field — shows users, also fills email on select */
function SupervisorNameField({ value, onChangeName, onChangeEmail, users }) {
  const [show, setShow] = useState(false);
  const results = value ? users.filter((u) => u.name.toLowerCase().includes(value.toLowerCase())).slice(0, 8) : [];
  return (
    <div className="relative">
      <Input
        value={value}
        onChange={(e) => { onChangeName(e.target.value); setShow(true); }}
        onFocus={() => setShow(true)}
        onBlur={() => setTimeout(() => setShow(false), 150)}
        placeholder="Search by name…"
        className="mt-2 rounded-none"
        autoComplete="off"
      />
      {show && results.length > 0 && (
        <div className="absolute z-50 left-0 right-0 bg-white border border-slate-200 shadow-md mt-1 max-h-40 overflow-y-auto">
          {results.map((u) => (
            <button key={u.id} type="button"
              className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 border-b border-slate-100 last:border-0"
              onMouseDown={(e) => { e.preventDefault(); onChangeName(u.name); onChangeEmail(u.email); setShow(false); }}>
              <div className="font-medium text-slate-900">{u.name}</div>
              <div className="text-xs text-slate-500">{u.email}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function UsersPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editForm, setEditForm] = useState(EMPTY_EDIT);

  const load = () => {
    setLoading(true);
    api.get("/users").then((r) => setUsers(r.data)).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.post("/users", form);
      toast.success(t("user_created_ok"));
      setOpen(false);
      setForm(EMPTY_FORM);
      load();
    } catch (err) { toast.error(formatErr(err)); }
  };

  const openEdit = (u) => {
    setEditTarget(u);
    setEditForm({
      name: u.name, email: u.email, role: u.role,
      department: u.department || "", campus: u.campus || "",
      supervisor_name: u.supervisor_name || "",
      supervisor: u.supervisor || "",
      employee_id: u.employee_id || "",
      password: "",
    });
    setEditOpen(true);
  };

  const submitEdit = async (e) => {
    e.preventDefault();
    const payload = { ...editForm };
    if (!payload.password) delete payload.password;
    try {
      await api.put(`/users/${editTarget.id}`, payload);
      toast.success(t("user_updated_ok"));
      setEditOpen(false);
      load();
    } catch (err) { toast.error(formatErr(err)); }
  };

  const remove = async (u) => {
    if (u.id === user.id) return toast.error(t("cant_delete_self"));
    if (!window.confirm(t("delete_user_confirm").replace("{{name}}", u.name))) return;
    try { await api.delete(`/users/${u.id}`); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };

  const allNames = users.map((u) => u.name);
  const allDepts = [...new Set(users.map((u) => u.department).filter(Boolean))];

  const FormFields = ({ values, set, isEdit }) => (
    <div className="space-y-4">
      <div><Label className="label-mono">{t("full_name")}</Label>
        <SuggestField required value={values.name} onChange={(v) => set({ ...values, name: v })}
          suggestions={allNames} testid="user-name-input" /></div>

      <div><Label className="label-mono">{t("col_employee_id")}</Label>
        <Input value={values.employee_id} onChange={(e) => set({ ...values, employee_id: e.target.value })}
          placeholder="e.g. 0000910439" className="mt-2 rounded-none font-mono" /></div>

      <div><Label className="label-mono">{t("email")}</Label>
        <Input type="email" required placeholder="user@fmi.com" value={values.email}
          onChange={(e) => set({ ...values, email: e.target.value })}
          className="mt-2 rounded-none" data-testid="user-email-input" /></div>

      {!isEdit && (
        <div><Label className="label-mono">{t("password")}</Label>
          <Input type="password" required minLength={6} value={values.password}
            onChange={(e) => set({ ...values, password: e.target.value })}
            className="mt-2 rounded-none" data-testid="user-password-input" /></div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div><Label className="label-mono">{t("role")}</Label>
          <Select value={values.role} onValueChange={(v) => set({ ...values, role: v })}>
            <SelectTrigger className="mt-2 rounded-none"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="staff">{t("staff")}</SelectItem>
              <SelectItem value="admin">{t("admin")}</SelectItem>
            </SelectContent>
          </Select></div>
        <div><Label className="label-mono">{t("department")}</Label>
          <SuggestField value={values.department} onChange={(v) => set({ ...values, department: v })}
            suggestions={allDepts} /></div>
      </div>

      <div><Label className="label-mono">{t("col_campus")}</Label>
        <Select value={values.campus} onValueChange={(v) => set({ ...values, campus: v })}>
          <SelectTrigger className="mt-2 rounded-none"><SelectValue placeholder={t("select_campus")} /></SelectTrigger>
          <SelectContent>
            <SelectItem value="YPJ Kuala Kencana">YPJ Kuala Kencana</SelectItem>
            <SelectItem value="YPJ Tembagapura">YPJ Tembagapura</SelectItem>
          </SelectContent>
        </Select></div>

      <div><Label className="label-mono">{t("supervisor_name")}</Label>
        <SupervisorNameField
          value={values.supervisor_name}
          onChangeName={(v) => set({ ...values, supervisor_name: v })}
          onChangeEmail={(v) => set({ ...values, supervisor: v })}
          users={users}
        /></div>

      <div><Label className="label-mono">{t("supervisor_email")}</Label>
        <Input type="email" value={values.supervisor}
          onChange={(e) => set({ ...values, supervisor: e.target.value })}
          placeholder="@fmi.com" className="mt-2 rounded-none" /></div>

      {isEdit && (
        <div><Label className="label-mono">{t("new_password_optional")}</Label>
          <Input type="password" minLength={6} value={values.password}
            onChange={(e) => set({ ...values, password: e.target.value })}
            placeholder={t("leave_blank_unchanged")} className="mt-2 rounded-none" /></div>
      )}
    </div>
  );

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="users-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="label-mono mb-2">{t("access_control")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            {t("team_users")}
          </h1>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="rounded-none bg-slate-900 hover:bg-slate-800" data-testid="add-user-button">
              <Plus className="w-4 h-4 mr-2" strokeWidth={1.75} /> {t("add_user")}
            </Button>
          </DialogTrigger>
          <DialogContent className="rounded-none max-h-[90vh] overflow-y-auto">
            <DialogHeader><DialogTitle>{t("create_user")}</DialogTitle></DialogHeader>
            <form onSubmit={submit}>
              <FormFields values={form} set={setForm} isEdit={false} />
              <DialogFooter className="mt-6">
                <Button type="submit" className="rounded-none bg-slate-900" data-testid="submit-user-button">
                  {t("create_user")}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="bg-white border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left label-mono py-3 px-4">{t("col_employee_id")}</th>
                <th className="text-left label-mono py-3 px-4">{t("col_name")}</th>
                <th className="text-left label-mono py-3 px-4">{t("email")}</th>
                <th className="text-left label-mono py-3 px-4">{t("role")}</th>
                <th className="text-left label-mono py-3 px-4">{t("department")}</th>
                <th className="text-left label-mono py-3 px-4">{t("col_campus")}</th>
                <th className="text-left label-mono py-3 px-4">{t("col_joined")}</th>
                <th className="text-right label-mono py-3 px-4">{t("col_actions")}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="text-center text-slate-500 py-12">{t("loading")}</td></tr>
              ) : users.map((u) => (
                <tr key={u.id} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`user-row-${u.id}`}>
                  <td className="py-3 px-4 text-slate-600 font-mono text-xs">{u.employee_id || "—"}</td>
                  <td className="py-3 px-4 font-medium text-slate-900">{u.name}</td>
                  <td className="py-3 px-4 text-slate-700">{u.email}</td>
                  <td className="py-3 px-4">
                    <span className={`text-xs px-2 py-0.5 border capitalize ${
                      u.role === "admin" ? "bg-blue-50 text-blue-800 border-blue-200" : "bg-slate-100 text-slate-600 border-slate-200"
                    }`}>{u.role === "admin" ? t("admin") : t("staff")}</span>
                  </td>
                  <td className="py-3 px-4 text-slate-700">{u.department || "—"}</td>
                  <td className="py-3 px-4 text-slate-700">
                    {u.campus ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${u.campus === "YPJ Kuala Kencana" ? "bg-amber-400" : "bg-blue-500"}`} />
                        <span className="text-xs">{u.campus}</span>
                      </span>
                    ) : "—"}
                  </td>
                  <td className="py-3 px-4 text-slate-500 text-xs">{fmtDate(u.created_at)}</td>
                  <td className="py-3 px-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button onClick={() => openEdit(u)} className="text-slate-400 hover:text-slate-700" data-testid={`edit-user-${u.id}`}>
                        <Pencil className="w-4 h-4" />
                      </button>
                      {u.id !== user.id && (
                        <button onClick={() => remove(u)} className="text-rose-500 hover:text-rose-700" data-testid={`delete-user-${u.id}`}>
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Edit user dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="rounded-none max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{t("edit_user")}</DialogTitle></DialogHeader>
          <form onSubmit={submitEdit}>
            <FormFields values={editForm} set={setEditForm} isEdit={true} />
            <DialogFooter className="mt-6">
              <Button variant="outline" className="rounded-none" type="button" onClick={() => setEditOpen(false)}>{t("cancel")}</Button>
              <Button type="submit" className="rounded-none bg-slate-900">{t("save_changes")}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
