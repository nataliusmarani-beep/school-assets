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
import { Plus, Trash2 } from "lucide-react";

export default function UsersPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "staff", department: "", campus: "", supervisor: "" });

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
      setForm({ name: "", email: "", password: "", role: "staff", department: "", campus: "", supervisor: "" });
      load();
    } catch (err) { toast.error(formatErr(err)); }
  };

  const remove = async (u) => {
    if (u.id === user.id) return toast.error(t("cant_delete_self"));
    if (!window.confirm(t("delete_user_confirm").replace("{{name}}", u.name))) return;
    try { await api.delete(`/users/${u.id}`); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };

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
              <Plus className="w-4 h-4 mr-2" strokeWidth={1.75}/> {t("add_user")}
            </Button>
          </DialogTrigger>
          <DialogContent className="rounded-none">
            <DialogHeader><DialogTitle>{t("create_user")}</DialogTitle></DialogHeader>
            <form onSubmit={submit} className="space-y-4">
              <div><Label className="label-mono">{t("full_name")}</Label>
                <Input required value={form.name} onChange={(e)=>setForm({...form,name:e.target.value})}
                  className="mt-2 rounded-none" data-testid="user-name-input"/></div>
              <div><Label className="label-mono">{t("email")}</Label>
                <Input type="email" required value={form.email} onChange={(e)=>setForm({...form,email:e.target.value})}
                  className="mt-2 rounded-none" data-testid="user-email-input"/></div>
              <div><Label className="label-mono">{t("password")}</Label>
                <Input type="password" required minLength={6} value={form.password}
                  onChange={(e)=>setForm({...form,password:e.target.value})}
                  className="mt-2 rounded-none" data-testid="user-password-input"/></div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label className="label-mono">{t("role")}</Label>
                  <Select value={form.role} onValueChange={(v)=>setForm({...form,role:v})}>
                    <SelectTrigger className="mt-2 rounded-none" data-testid="user-role-select"><SelectValue/></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="staff">{t("staff")}</SelectItem>
                      <SelectItem value="admin">{t("admin")}</SelectItem>
                    </SelectContent>
                  </Select></div>
                <div><Label className="label-mono">{t("department")}</Label>
                  <Input value={form.department} onChange={(e)=>setForm({...form,department:e.target.value})}
                    className="mt-2 rounded-none"/></div>
              </div>
              <div><Label className="label-mono">{t("col_campus")}</Label>
                <Select value={form.campus} onValueChange={(v)=>setForm({...form,campus:v})}>
                  <SelectTrigger className="mt-2 rounded-none"><SelectValue placeholder={t("select_campus")}/></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="YPJ Kuala Kencana">YPJ Kuala Kencana</SelectItem>
                    <SelectItem value="YPJ Tembagapura">YPJ Tembagapura</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div><Label className="label-mono">{t("col_supervisor")}</Label>
                <Input value={form.supervisor} onChange={(e)=>setForm({...form,supervisor:e.target.value})}
                  placeholder={t("supervisor_placeholder")} className="mt-2 rounded-none"/>
              </div>
              <DialogFooter>
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
                <th className="text-left label-mono py-3 px-4">{t("col_name")}</th>
                <th className="text-left label-mono py-3 px-4">{t("email")}</th>
                <th className="text-left label-mono py-3 px-4">{t("role")}</th>
                <th className="text-left label-mono py-3 px-4">{t("department")}</th>
                <th className="text-left label-mono py-3 px-4">{t("col_campus")}</th>
                <th className="text-left label-mono py-3 px-4">{t("col_supervisor")}</th>
                <th className="text-left label-mono py-3 px-4">{t("col_joined")}</th>
                <th className="text-right label-mono py-3 px-4">{t("col_actions")}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="text-center text-slate-500 py-12">{t("loading")}</td></tr>
              ) : users.map((u) => (
                <tr key={u.id} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`user-row-${u.id}`}>
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
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${u.campus === "YPJ Kuala Kencana" ? "bg-amber-400" : "bg-blue-500"}`}/>
                        <span className="text-xs">{u.campus}</span>
                      </span>
                    ) : "—"}
                  </td>
                  <td className="py-3 px-4 text-slate-700 text-xs">{u.supervisor || "—"}</td>
                  <td className="py-3 px-4 text-slate-500 text-xs">{fmtDate(u.created_at)}</td>
                  <td className="py-3 px-4 text-right">
                    {u.id !== user.id && (
                      <button onClick={()=>remove(u)} className="text-rose-500 hover:text-rose-700" data-testid={`delete-user-${u.id}`}>
                        <Trash2 className="w-4 h-4"/>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
