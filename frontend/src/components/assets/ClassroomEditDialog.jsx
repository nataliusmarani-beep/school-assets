import { useEffect, useState } from "react";
import api, { formatErr } from "../../lib/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { toast } from "sonner";

const TYPES = ["kelas", "lab", "kantor", "lainnya"];
const SEL = "mt-2 w-full h-10 px-3 text-sm border border-slate-300 bg-white rounded-none";

// Admin: rename a room / change its type. Assets in the room follow the new name (their location text).
export default function ClassroomEditDialog({ open, onOpenChange, t, room, onDone }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("kelas");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open && room) { setName(room.name); setType(room.room_type); } }, [open, room]);

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
            <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-2 rounded-none" data-testid="classroom-edit-name" />
          </div>
          <div>
            <label className="label-mono">{t("cr_type")}</label>
            <select value={type} onChange={(e) => setType(e.target.value)} className={SEL} data-testid="classroom-edit-type">
              {TYPES.map((k) => <option key={k} value={k}>{t(`cr_type_${k}`)}</option>)}
            </select>
          </div>
        </div>
        <DialogFooter>
          <Button disabled={busy || !name.trim()} onClick={save} className="rounded-none bg-slate-900" data-testid="classroom-edit-save">{t("cr_save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
