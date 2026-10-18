import { useEffect, useState } from "react";
import api, { formatErr } from "../../lib/api";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { toast } from "sonner";
import { ownerName } from "../../lib/format";
import { campusLabel } from "../../lib/campus";

const SEL = "mt-2 w-full h-10 px-3 text-sm border border-slate-300 bg-white rounded-none";

// Admin: change the responsible teacher of a classroom. The new teacher checks every asset (accept /
// missing-or-damaged); the change only takes effect once all items are checked.
export default function HandoverDialog({ open, onOpenChange, t, onDone, classroomId }) {
  const [users, setUsers] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [roomId, setRoomId] = useState(classroomId || "");
  const [room, setRoom] = useState(null);
  const [toId, setToId] = useState("");
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setRoomId(classroomId || "");
    api.get("/users").then((r) => setUsers(r.data)).catch(() => {});
    if (!classroomId) api.get("/classrooms").then((r) => setRooms(r.data)).catch(() => {});
  }, [open, classroomId]);

  useEffect(() => {
    if (!open || !roomId) { setRoom(null); return; }
    api.get(`/classrooms/${roomId}`).then((r) => setRoom(r.data)).catch((e) => toast.error(formatErr(e)));
  }, [open, roomId]);

  const active = (room?.assets || []).filter((a) => !["retired", "lost"].includes(a.status));
  const isBlocked = (a) => !!a.pending_assignment || !a.is_class_asset || (a.assigned_to_user_id && a.assigned_to_user_id === toId);
  const selectable = active.filter((a) => !isBlocked(a));

  useEffect(() => { setChecked(new Set(selectable.map((a) => a.id))); }, [room, toId]); // eslint-disable-line

  const toggle = (id) => setChecked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allOn = selectable.length > 0 && selectable.every((a) => checked.has(a.id));

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/classrooms/${roomId}/handover`, { to_user_id: toId, asset_ids: [...checked], note });
      let msg = t("ho_result").replace("{n}", r.data.created);
      if (r.data.skipped.length) msg += " · " + t("ho_skipped").replace("{n}", r.data.skipped.length);
      toast.success(msg);
      onOpenChange(false);
      setToId(""); setNote("");
      if (!classroomId) setRoomId("");
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
          {!classroomId && (
            <div>
              <label className="label-mono">{t("ho_room")}</label>
              <select value={roomId} onChange={(e) => setRoomId(e.target.value)} className={SEL} data-testid="ho-room">
                <option value="">{t("ho_room_ph")}</option>
                {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}{r.campus ? ` — ${campusLabel(r.campus)}` : ""}</option>)}
              </select>
            </div>
          )}
          {room && (
            <div className="text-xs text-slate-500">
              {t("cr_responsible")}: <span className="text-slate-800 font-medium">{room.responsible_name ? ownerName(room.responsible_name) : t("cr_none_resp")}</span>
            </div>
          )}
          <div>
            <label className="label-mono">{t("ho_recipient")}</label>
            <select value={toId} onChange={(e) => setToId(e.target.value)} className={SEL} data-testid="ho-recipient">
              <option value="">{t("ho_recipient_ph")}</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}{u.department ? ` — ${u.department}` : ""}</option>)}
            </select>
          </div>
          {room && (
            <div className="border border-slate-200 max-h-64 overflow-y-auto" data-testid="ho-list">
              {active.length === 0 ? (
                <div className="p-4 text-sm text-slate-500">{t("ho_none")}</div>
              ) : (
                <>
                  <label className="flex items-center gap-3 px-3 py-2 bg-slate-50 border-b border-slate-200 text-sm">
                    <input type="checkbox" checked={allOn}
                      onChange={() => setChecked(allOn ? new Set() : new Set(selectable.map((a) => a.id)))} />
                    {t("ho_select_all")} ({checked.size}/{selectable.length})
                  </label>
                  {active.map((a) => {
                    const blocked = isBlocked(a);
                    return (
                      <label key={a.id} className={`flex items-center gap-3 px-3 py-2 border-b border-slate-100 last:border-0 text-sm ${blocked ? "opacity-50" : ""}`}>
                        <input type="checkbox" disabled={blocked} checked={checked.has(a.id)} onChange={() => toggle(a.id)} />
                        <span className="flex-1">
                          {a.name} <span className="font-mono text-xs text-slate-500">({a.asset_tag})</span>
                        </span>
                        <span className="text-xs text-slate-500">
                          {a.pending_assignment ? t("ho_waiting")
                            : !a.is_class_asset ? t("cr_personal_stays")
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
          <Button disabled={busy || !roomId || !toId || checked.size === 0} onClick={submit} className="rounded-none bg-slate-900" data-testid="ho-submit">
            {t("ho_submit")} ({checked.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
