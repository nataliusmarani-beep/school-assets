import { useEffect, useMemo, useState } from "react";
import api, { formatErr } from "../../lib/api";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { toast } from "sonner";
import { ownerName } from "../../lib/format";

const SEL = "mt-2 w-full h-10 px-3 text-sm border border-slate-300 bg-white rounded-none";

// Admin: hand over several assets (a whole classroom) to one person, who confirms item by item.
export default function HandoverDialog({ open, onOpenChange, t, onDone }) {
  const [users, setUsers] = useState([]);
  const [assets, setAssets] = useState([]);
  const [pendingIds, setPendingIds] = useState(new Set());
  const [toId, setToId] = useState("");
  const [room, setRoom] = useState("");
  const [kind, setKind] = useState("class");
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.get("/users").then((r) => setUsers(r.data)).catch(() => {});
    api.get("/assets").then((r) => setAssets(r.data)).catch(() => {});
    api.get("/assignments", { params: { status: "pending" } })
      .then((r) => setPendingIds(new Set(r.data.map((a) => a.asset_id)))).catch(() => {});
  }, [open]);

  const rooms = useMemo(
    () => [...new Set(assets.filter((a) => !["retired", "lost"].includes(a.status)).map((a) => a.location).filter(Boolean))].sort(),
    [assets]);
  const inRoom = useMemo(
    () => assets.filter((a) => a.location === room && !["retired", "lost"].includes(a.status)),
    [assets, room]);
  const selectable = inRoom.filter((a) => !pendingIds.has(a.id) && a.assigned_to_user_id !== toId);

  // default: every selectable item in the chosen room is ticked
  useEffect(() => { setChecked(new Set(selectable.map((a) => a.id))); }, [room, toId, assets, pendingIds]); // eslint-disable-line

  const toggle = (id) => setChecked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allOn = selectable.length > 0 && selectable.every((a) => checked.has(a.id));

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post("/assignments/bulk", { to_user_id: toId, asset_ids: [...checked], kind, note });
      let msg = t("ho_result").replace("{n}", r.data.created);
      if (r.data.skipped.length) msg += " · " + t("ho_skipped").replace("{n}", r.data.skipped.length);
      toast.success(msg);
      onOpenChange(false);
      setRoom(""); setToId(""); setNote("");
      onDone && onDone();
    } catch (e) { toast.error(formatErr(e)); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none max-w-xl" data-testid="handover-dialog">
        <DialogHeader><DialogTitle>{t("ho_title")}</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-500">{t("ho_hint")}</p>
        <div className="space-y-4">
          <div>
            <label className="label-mono">{t("ho_recipient")}</label>
            <select value={toId} onChange={(e) => setToId(e.target.value)} className={SEL} data-testid="ho-recipient">
              <option value="">{t("ho_recipient_ph")}</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}{u.department ? ` — ${u.department}` : ""}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label-mono">{t("ho_room")}</label>
              <select value={room} onChange={(e) => setRoom(e.target.value)} className={SEL} data-testid="ho-room">
                <option value="">{t("ho_room_ph")}</option>
                {rooms.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className="label-mono">{t("ho_kind")}</label>
              <select value={kind} onChange={(e) => setKind(e.target.value)} className={SEL} data-testid="ho-kind">
                <option value="class">{t("ma_kind_class")}</option>
                <option value="personal">{t("ma_kind_personal")}</option>
              </select>
            </div>
          </div>
          {room && (
            <div className="border border-slate-200 max-h-64 overflow-y-auto" data-testid="ho-list">
              {inRoom.length === 0 ? (
                <div className="p-4 text-sm text-slate-500">{t("ho_none")}</div>
              ) : (
                <>
                  <label className="flex items-center gap-3 px-3 py-2 bg-slate-50 border-b border-slate-200 text-sm">
                    <input type="checkbox" checked={allOn}
                      onChange={() => setChecked(allOn ? new Set() : new Set(selectable.map((a) => a.id)))} />
                    {t("ho_select_all")} ({checked.size}/{selectable.length})
                  </label>
                  {inRoom.map((a) => {
                    const blocked = pendingIds.has(a.id) || a.assigned_to_user_id === toId;
                    return (
                      <label key={a.id} className={`flex items-center gap-3 px-3 py-2 border-b border-slate-100 last:border-0 text-sm ${blocked ? "opacity-50" : ""}`}>
                        <input type="checkbox" disabled={blocked} checked={checked.has(a.id)} onChange={() => toggle(a.id)} />
                        <span className="flex-1">
                          {a.name} <span className="font-mono text-xs text-slate-500">({a.asset_tag})</span>
                        </span>
                        <span className="text-xs text-slate-500">
                          {pendingIds.has(a.id) ? t("ho_waiting")
                            : a.assigned_to_name ? t("ho_current").replace("{name}", ownerName(a.assigned_to_name)) : ""}
                        </span>
                      </label>
                    );
                  })}
                </>
              )}
            </div>
          )}
          <div>
            <label className="label-mono">{t("ho_note")}</label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="mt-2 rounded-none" />
          </div>
        </div>
        <DialogFooter>
          <Button disabled={busy || !toId || checked.size === 0} onClick={submit} className="rounded-none bg-slate-900" data-testid="ho-submit">
            {t("ho_submit")} ({checked.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
