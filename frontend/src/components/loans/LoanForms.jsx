import { useRef, useState } from "react";
import api, { API, formatErr } from "../../lib/api";
import { compressImage } from "../../lib/image";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { toast } from "sonner";
import { Camera, Check, X } from "lucide-react";

export const PHYSICAL = ["baik", "lecet", "retak", "lainnya"];
export const FUNCTIONS = ["normal", "masalah"];
export const RESULTS = ["ok", "changed", "damaged", "lost"];

export const fileSrc = (path) => (path ? `${API}/files/${path}` : "");

export const fmtDateTime = (v) => (v ? v.replace("T", " ").slice(0, 16) : "—");

/* Photo picker: compresses, uploads right away and keeps the stored path in `value`. */
export function PhotoField({ label, value, onChange, hint, required }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  const pick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const small = await compressImage(file);
      const fd = new FormData();
      fd.append("file", small);
      const r = await api.post("/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      onChange(r.data.path);
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = "";
    }
  };
  return (
    <div>
      <Label className="label-mono">{label}{required ? " *" : ""}</Label>
      <div className="mt-2 border-2 border-dashed border-slate-200 p-3 flex items-center gap-3 cursor-pointer hover:border-slate-400"
        onClick={() => ref.current?.click()} data-testid="loan-photo-field">
        {value ? <img src={fileSrc(value)} alt="" className="h-20 w-28 object-cover border border-slate-200" />
          : <Camera className="w-7 h-7 text-slate-300" strokeWidth={1.5} />}
        <span className="text-xs text-slate-500">{busy ? "…" : hint}</span>
        <input ref={ref} type="file" accept="image/*" capture="environment" className="sr-only" onChange={pick} />
      </div>
    </div>
  );
}

/* One unit's condition check, used for both check-out and check-in. */
export function UnitCheck({ t, mode, accessories, value, onChange, photoOptional = false }) {
  const v = value;
  const set = (patch) => onChange({ ...v, ...patch });
  const setAcc = (name, ok) => set({ accessories: v.accessories.map((a) => (a.name === name ? { ...a, ok } : a)) });
  const needsNote = v.physical !== "baik" || v.function !== "normal" || v.accessories.some((a) => !a.ok) || (mode === "in" && v.result !== "ok");
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="label-mono">{t("ln_physical")}</Label>
          <Select value={v.physical} onValueChange={(x) => set({ physical: x })}>
            <SelectTrigger className="mt-2 rounded-none" data-testid="loan-physical"><SelectValue /></SelectTrigger>
            <SelectContent>{PHYSICAL.map((p) => <SelectItem key={p} value={p}>{t(`ln_phys_${p}`)}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div>
          <Label className="label-mono">{t("ln_function")}</Label>
          <Select value={v.function} onValueChange={(x) => set({ function: x })}>
            <SelectTrigger className="mt-2 rounded-none" data-testid="loan-function"><SelectValue /></SelectTrigger>
            <SelectContent>{FUNCTIONS.map((p) => <SelectItem key={p} value={p}>{t(`ln_fn_${p}`)}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>

      {accessories.length > 0 && (
        <div>
          <Label className="label-mono">{t("ln_accessories")}</Label>
          <div className="mt-2 space-y-1">
            {v.accessories.map((a) => (
              <div key={a.name} className="flex items-center justify-between border border-slate-200 px-3 py-2 text-sm">
                <span>{a.name}</span>
                <span className="flex gap-1">
                  <button type="button" onClick={() => setAcc(a.name, true)} data-testid={`acc-ok-${a.name}`}
                    className={`px-2 py-1 border text-xs ${a.ok ? "bg-emerald-50 border-emerald-300 text-emerald-700" : "border-slate-200 text-slate-400"}`}>
                    <Check className="w-3.5 h-3.5 inline" /> {t("ln_present")}
                  </button>
                  <button type="button" onClick={() => setAcc(a.name, false)} data-testid={`acc-missing-${a.name}`}
                    className={`px-2 py-1 border text-xs ${!a.ok ? "bg-rose-50 border-rose-300 text-rose-700" : "border-slate-200 text-slate-400"}`}>
                    <X className="w-3.5 h-3.5 inline" /> {t("ln_missing")}
                  </button>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {mode === "in" && (
        <div>
          <Label className="label-mono">{t("ln_result")}</Label>
          <Select value={v.result} onValueChange={(x) => set({ result: x })}>
            <SelectTrigger className="mt-2 rounded-none" data-testid="loan-result"><SelectValue /></SelectTrigger>
            <SelectContent>{RESULTS.map((p) => <SelectItem key={p} value={p}>{t(`ln_res_${p}`)}</SelectItem>)}</SelectContent>
          </Select>
          {v.result !== "ok" && <p className="text-xs text-amber-700 mt-1">{t("ln_result_fault_hint")}</p>}
        </div>
      )}

      <div>
        <Label className="label-mono">{t(mode === "in" ? "ln_damage_note" : "ln_note")}{needsNote ? " *" : ""}</Label>
        <Textarea rows={2} value={v.note} onChange={(e) => set({ note: e.target.value })} className="mt-2 rounded-none" data-testid="loan-note" />
      </div>

      {!(mode === "in" && v.result === "lost") && (
        <PhotoField required={!photoOptional} label={t(mode === "in" ? "ln_photo_after" : "ln_photo_before")} value={v.photo}
          onChange={(p) => set({ photo: p })} hint={t("ln_photo_hint")} />
      )}
    </div>
  );
}

export const emptyUnit = (assetId, accessoryNames) => ({
  asset_id: assetId, physical: "baik", function: "normal", note: "", photo: "", result: "ok",
  accessories: accessoryNames.map((name) => ({ name, ok: true })),
});

/* Cart / lab hand-over: every unit at once. Untick a unit that is not handed over / not back; flag a unit that has a problem. */
export function CartCheck({ t, mode, units, value, onChange }) {
  const v = value;
  const toggleOut = (id, on) => { const ex = new Set(v.excluded); on ? ex.delete(id) : ex.add(id); onChange({ ...v, excluded: ex }); };
  const setProblem = (id, unit) => { const pr = { ...v.problems }; unit ? (pr[id] = unit) : delete pr[id]; onChange({ ...v, problems: pr }); };
  const present = units.filter((u) => !v.excluded.has(u.asset_id)).length;
  return (
    <div className="space-y-4" data-testid="cart-check">
      <PhotoField required label={t("ln_photo_cart")} value={v.groupPhoto} onChange={(p) => onChange({ ...v, groupPhoto: p })} hint={t("ln_photo_cart_hint")} />
      <div>
        <div className="flex items-center justify-between">
          <Label className="label-mono">{t(mode === "in" ? "ln_cart_units_back" : "ln_cart_units_out")}</Label>
          <span className="text-xs text-slate-500">{present}/{units.length}</span>
        </div>
        <div className="mt-2 border border-slate-200 max-h-72 overflow-y-auto divide-y divide-slate-100">
          {units.map((u) => {
            const off = v.excluded.has(u.asset_id);
            const pr = v.problems[u.asset_id];
            return (
              <div key={u.asset_id} className={`px-3 py-2 text-sm ${off ? "bg-amber-50" : ""}`}>
                <div className="flex items-center gap-3">
                  <input type="checkbox" checked={!off} onChange={(e) => toggleOut(u.asset_id, e.target.checked)} data-testid={`cart-unit-${u.tag}`} />
                  <span className="flex-1 truncate">{u.name} <span className="font-mono text-xs text-slate-400">{u.tag}</span>{u.who ? <span className="text-xs text-slate-500"> · {u.who}</span> : null}</span>
                  {off && <span className="text-xs text-amber-700">{t(mode === "in" ? "ln_not_returned" : "ln_not_handed")}</span>}
                  {!off && <button type="button" className={`text-xs underline ${pr ? "text-rose-600" : "text-slate-500"}`} data-testid={`cart-problem-${u.tag}`}
                    onClick={() => { if (pr) { setProblem(u.asset_id, null); } else { setProblem(u.asset_id, { ...emptyUnit(u.asset_id, []), result: mode === "in" ? "damaged" : "ok", physical: mode === "in" ? "retak" : "lecet" }); } }}>
                    {pr ? t("ln_problem_remove") : t("ln_problem_flag")}</button>}
                </div>
                {pr && !off && (
                  <div className="mt-3 border-l-2 border-rose-300 pl-3">
                    <UnitCheck t={t} mode={mode} accessories={[]} value={pr} onChange={(x) => setProblem(u.asset_id, x)} photoOptional />
                  </div>)}
              </div>);
          })}
        </div>
      </div>
    </div>
  );
}

export const emptyCart = () => ({ groupPhoto: "", excluded: new Set(), problems: {} });
export const cartBody = (v) => ({ all_units: true, group_photo: v.groupPhoto, exclude: [...v.excluded], units: Object.values(v.problems) });
