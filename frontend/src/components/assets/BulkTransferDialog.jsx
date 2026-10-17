import { useEffect, useState } from "react";
import api, { formatErr } from "../../lib/api";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { toast } from "sonner";
import { ownerName } from "../../lib/format";

const SEL = "mt-2 w-full h-10 px-3 text-sm border border-slate-300 bg-white rounded-none";

// Admin: transfer the ticked assets from the Assets list to one registered user (recipient confirms).
export default function BulkTransferDialog({ open, onOpenChange, t, assets, onDone }) {
  const [users, setUsers] = useState([]);
  const [toId, setToId] = useState("");
  const [kind, setKind] = useState("personal");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.get("/users").then((r) => setUsers(r.data)).catch(() => {});
  }, [open]);

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post("/assignments/bulk", { to_user_id: toId, asset_ids: assets.map((a) => a.id), kind, note });
      let msg = t("ho_result").replace("{n}", r.data.created);
      if (r.data.skipped.length) msg += " · " + t("ho_skipped").replace("{n}", r.data.skipped.length);
      toast.success(msg);
      onOpenChange(false);
      setToId(""); setNote("");
      onDone && onDone(r.data);
    } catch (e) { toast.error(formatErr(e)); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none max-w-xl" data-testid="bulk-transfer-dialog">
        <DialogHeader><DialogTitle>{t("bt_title").replace("{n}", assets.length)}</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-500">{t("bt_hint")}</p>
        <div className="space-y-4">
          <div>
            <label className="label-mono">{t("ho_recipient")}</label>
            <select value={toId} onChange={(e) => setToId(e.target.value)} className={SEL} data-testid="bt-recipient">
              <option value="">{t("ho_recipient_ph")}</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}{u.department ? ` — ${u.department}` : ""}</option>)}
            </select>
          </div>
          <div>
            <label className="label-mono">{t("ho_kind")}</label>
            <select value={kind} onChange={(e) => setKind(e.target.value)} className={SEL} data-testid="bt-kind">
              <option value="personal">{t("ma_kind_personal")}</option>
              <option value="class">{t("ma_kind_class")}</option>
            </select>
          </div>
          <div className="border border-slate-200 max-h-48 overflow-y-auto" data-testid="bt-list">
            {assets.map((a) => (
              <div key={a.id} className="flex items-center justify-between px-3 py-1.5 text-sm border-b border-slate-100 last:border-0">
                <span><span className="font-mono text-xs text-slate-500 mr-2">{a.asset_tag}</span>{a.name}</span>
                <span className="text-xs text-slate-500">{ownerName(a.assigned_to_name) || "—"}</span>
              </div>
            ))}
          </div>
          <div>
            <label className="label-mono">{t("ho_note")}</label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} className="mt-2 rounded-none" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" className="rounded-none" onClick={() => onOpenChange(false)}>{t("cancel")}</Button>
          <Button className="rounded-none" disabled={!toId || busy || assets.length === 0} onClick={submit} data-testid="bt-submit">
            {t("ho_submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
