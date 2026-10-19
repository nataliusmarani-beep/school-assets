import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import QRCode from "qrcode";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { isCampusBound } from "../lib/roles";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { toast } from "sonner";
import { ArrowLeft, Printer } from "lucide-react";
import { campusLabel } from "../lib/campus";

const CAMPUSES = ["YPJ Kuala Kencana", "YPJ TPRA"];

export default function QrLabelsPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const [campus, setCampus] = useState(user?.campus && CAMPUSES.includes(user.campus) ? user.campus : CAMPUSES[0]);
  const [assets, setAssets] = useState([]);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(new Set());
  const [codes, setCodes] = useState({});

  useEffect(() => {
    api.get("/loans/assets", { params: { campus } }).then((r) => { setAssets(r.data); setSel(new Set(r.data.map((a) => a.id))); }).catch((e) => toast.error(formatErr(e)));
  }, [campus]);

  const shown = useMemo(() => assets.filter((a) => `${a.name} ${a.asset_tag}`.toLowerCase().includes(q.toLowerCase())), [assets, q]);
  const chosen = shown.filter((a) => sel.has(a.id));

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const next = {};
      for (const a of chosen) next[a.id] = await QRCode.toDataURL(`${window.location.origin}/scan?code=${encodeURIComponent(a.asset_tag)}`, { margin: 1, width: 220 });
      if (!cancelled) setCodes(next);
    })();
    return () => { cancelled = true; };
  }, [chosen.map((a) => a.id).join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-6 lg:p-10 max-w-[1100px] mx-auto" data-testid="qr-labels-page">
      <style>{`@media print { body * { visibility: hidden; } #qr-sheet, #qr-sheet * { visibility: visible; } #qr-sheet { position: absolute; left: 0; top: 0; width: 100%; } }`}</style>
      <Link to="/scan" className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1 mb-4"><ArrowLeft className="w-4 h-4" /> {t("qr_title")}</Link>
      <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">{t("qr_print_labels")}</h1>
      <p className="text-sm text-slate-500 mt-2">{t("qr_labels_hint")}</p>
      <div className="flex gap-3 flex-wrap items-center my-5">
        <select className="border border-slate-200 bg-white px-3 py-2 text-sm h-10" value={campus} disabled={isCampusBound(user?.role)} onChange={(e) => setCampus(e.target.value)}>
          {CAMPUSES.map((c) => <option key={c} value={c}>{campusLabel(c)}</option>)}</select>
        <Input className="w-64 rounded-none" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("ln_search")} />
        <Button variant="outline" className="rounded-none" onClick={() => setSel(new Set(shown.map((a) => a.id)))}>{t("qr_select_all")}</Button>
        <Button className="rounded-none ml-auto" onClick={() => window.print()} data-testid="qr-print"><Printer className="w-4 h-4 mr-2" /> {t("qr_print")} ({chosen.length})</Button>
      </div>
      <div className="border border-slate-200 bg-white p-3 mb-6 max-h-48 overflow-y-auto grid sm:grid-cols-2 gap-1 text-sm">
        {shown.map((a) => (
          <label key={a.id} className="flex items-center gap-2"><input type="checkbox" checked={sel.has(a.id)} onChange={(e) => { const s = new Set(sel); e.target.checked ? s.add(a.id) : s.delete(a.id); setSel(s); }} />
            <span className="truncate">{a.name}</span><span className="font-mono text-xs text-slate-400">{a.asset_tag}</span></label>))}
        {shown.length === 0 && <div className="text-slate-500 p-2">{t("ln_no_borrowable")}</div>}
      </div>
      <div id="qr-sheet" className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
        {chosen.map((a) => (
          <div key={a.id} className="border border-slate-300 p-2 text-center break-inside-avoid" data-testid={`qr-label-${a.asset_tag}`}>
            {codes[a.id] && <img src={codes[a.id]} alt={a.asset_tag} className="w-full max-w-[150px] mx-auto" />}
            <div className="font-mono text-sm font-semibold">{a.asset_tag}</div>
            <div className="text-[11px] text-slate-600 leading-tight">{a.name}</div>
            <div className="text-[10px] text-slate-400">YPJ School</div>
          </div>))}
      </div>
    </div>
  );
}
