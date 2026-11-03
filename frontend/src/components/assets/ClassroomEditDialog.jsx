import { useEffect, useState } from "react";
import api, { formatErr } from "../../lib/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { Search, X } from "lucide-react";
import { toast } from "sonner";

const TYPES = ["kelas", "lab", "kantor", "lainnya"];
const SEL = "mt-2 w-full h-10 px-3 text-sm border border-slate-300 bg-white rounded-none";

// Admin: rename a room / change its type. Assets in the room follow the new name (their location text).
export default function ClassroomEditDialog({ open, onOpenChange, t, room, onDone }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("kelas");
  const [busy, setBusy] = useState(false);
  const [mergeTo, setMergeTo] = useState("");
  const [mergeQ, setMergeQ] = useState("");
  const [rooms, setRooms] = useState([]);

  useEffect(() => {
    if (!open || !room) return;
    setName(room.name); setType(room.room_type); setMergeTo(""); setMergeQ("");
    api.get("/rooms", { params: room.campus ? { campus: room.campus } : {} }).then((r) => setRooms(r.data)).catch(() => setRooms([]));
  }, [open, room]);

  const candidates = rooms.filter((r) => room && r.id !== room.id && (r.campus || "") === (room.campus || ""));
  const norm = (x) => (x || "").toLowerCase().replace(/[^0-9a-z]/g, "");
  const typed = name.trim();
  // registered rooms that match what is typed (searchable, so a name that already exists is spotted before saving)
  const nameMatches = typed && typed !== room?.name
    ? candidates.filter((r) => r.name.toLowerCase().includes(typed.toLowerCase()) || (norm(r.name) && (norm(r.name).includes(norm(typed)) || norm(typed).includes(norm(r.name))))).slice(0, 5)
    : [];
  const clash = candidates.find((r) => r.name.toLowerCase() === typed.toLowerCase().replace(/\s+/g, " "));
  const mergeOptions = candidates.filter((r) => !mergeQ.trim() || r.name.toLowerCase().includes(mergeQ.trim().toLowerCase())).slice(0, 8);
  const mergeTarget = candidates.find((r) => r.id === mergeTo);

  const merge = async () => {
    const target = candidates.find((r) => r.id === mergeTo);
    if (!target || !window.confirm(t("cr_merge_confirm").replace("{from}", room.name).replace("{to}", target.name))) return;
    setBusy(true);
    try {
      const r = await api.post(`/classrooms/${room.id}/merge`, { target_id: target.id });
      toast.success(t("cr_merged").replace("{n}", r.data.moved_assets).replace("{to}", target.name));
      onOpenChange(false);
      onDone && onDone();
    } catch (e) { toast.error(formatErr(e)); }
    finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/classrooms/${room.id}`, { name, room_type: type });
      toast.success(t("cr_saved"));
      onOpenChange(false);
      onDone && onDone();
    } catch (e) { toast.error(formatErr(e)); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none" data-testid="classroom-edit-dialog">
        <DialogHeader><DialogTitle>{t("cr_edit_title")}</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-500">{t("cr_edit_hint")}</p>
        <div className="space-y-4">
          <div>
            <label className="label-mono">{t("cr_name")}</label>
            <div className="relative mt-2">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
              <Input value={name} onChange={(e) => setName(e.target.value)} className="pl-9 rounded-none" data-testid="classroom-edit-name" autoComplete="off" />
            </div>
            {clash && <p className="mt-1.5 text-xs text-rose-700" data-testid="classroom-edit-clash">{t("cr_name_taken").replace("{name}", clash.name)}</p>}
            {nameMatches.length > 0 && (
              <div className="mt-2 border border-slate-200 bg-slate-50" data-testid="classroom-edit-matches">
                <div className="px-3 py-1.5 text-xs text-slate-500 border-b border-slate-200">{t("cr_registered_like")}</div>
                {nameMatches.map((r) => (
                  <button key={r.id} type="button" onClick={() => { setMergeTo(r.id); setMergeQ(""); }} data-testid="classroom-edit-match"
                    className="w-full text-left px-3 py-2 text-sm hover:bg-white border-b border-slate-100 last:border-0 flex justify-between gap-3">
                    <span>{r.name}</span><span className="text-xs text-blue-800 underline">{t("cr_merge_into_this")}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label className="label-mono">{t("cr_type")}</label>
            <select value={type} onChange={(e) => setType(e.target.value)} className={SEL} data-testid="classroom-edit-type">
              {TYPES.map((k) => <option key={k} value={k}>{t(`cr_type_${k}`)}</option>)}
            </select>
          </div>
          {candidates.length > 0 && (
            <div className="border-t border-slate-200 pt-4" data-testid="classroom-merge">
              <label className="label-mono">{t("cr_merge_title")}</label>
              <p className="text-xs text-slate-500 mt-1">{t("cr_merge_hint")}</p>
              {mergeTarget ? (
                <div className="mt-2 flex gap-2 items-center">
                  <div className="flex-1 h-10 px-3 text-sm border border-slate-300 bg-slate-50 flex items-center justify-between" data-testid="classroom-merge-selected">
                    <span className="font-medium">{mergeTarget.name}</span>
                    <button type="button" onClick={() => setMergeTo("")} aria-label="clear" className="text-slate-400 hover:text-slate-900"><X className="w-4 h-4" /></button>
                  </div>
                  <Button type="button" variant="outline" disabled={busy} onClick={merge} className="rounded-none" data-testid="classroom-merge-button">{t("cr_merge_btn")}</Button>
                </div>
              ) : (
                <div className="mt-2" data-testid="classroom-merge-select">
                  <div className="relative">
                    <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
                    <input value={mergeQ} onChange={(e) => setMergeQ(e.target.value)} placeholder={t("cr_merge_pick")} data-testid="classroom-merge-search"
                      className="w-full h-10 pl-9 pr-3 text-sm border border-slate-300 outline-none focus:border-slate-500" />
                  </div>
                  <div className="max-h-40 overflow-y-auto border border-t-0 border-slate-200">
                    {mergeOptions.length === 0 ? <div className="px-3 py-2 text-sm text-slate-500">{t("room_none")}</div> : mergeOptions.map((r) => (
                      <button key={r.id} type="button" onClick={() => setMergeTo(r.id)} data-testid="classroom-merge-option"
                        className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 border-b border-slate-100 last:border-0">{r.name}</button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button disabled={busy || !name.trim() || !!clash} onClick={save} className="rounded-none bg-slate-900" data-testid="classroom-edit-save">{t("cr_save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
