import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { toast } from "sonner";
import QrScanner from "../components/loans/QrScanner";
import { campusLabel } from "../lib/campus";

/* Asset check / registration: scan a label to open the asset, or start a new asset when the code is not registered yet. */
const codeOf = (text) => String(text || "").trim().split("=").pop().split("/").pop().trim();

export default function AssetScanPage() {
  const { t } = useLang();
  const [found, setFound] = useState(null);       // { asset, state } of a registered asset
  const [unknown, setUnknown] = useState("");     // code that is not registered
  const [busy, setBusy] = useState(false);

  const onScan = useCallback(async (text) => {
    const code = codeOf(text);
    if (!code) return;
    setBusy(true); setFound(null); setUnknown("");
    try { const r = await api.get("/loans/scan", { params: { code } }); setFound(r.data); }
    catch (e) {
      if (e?.response?.status === 404) setUnknown(code);
      else toast.error(formatErr(e));
    } finally { setBusy(false); }
  }, []);

  const a = found?.asset;
  return (
    <div className="p-6 lg:p-10 max-w-[760px] mx-auto" data-testid="asset-scan-page">
      <div className="label-mono mb-2">{t("qr_asset_kicker")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">{t("qr_asset_title")}</h1>
      <p className="text-sm text-slate-500 mt-2">{t("qr_asset_subtitle")}</p>
      <div className="mt-6"><QrScanner onScan={onScan} t={t} /></div>
      {busy && <div className="text-xs text-slate-400 mt-2">…</div>}

      {a && (
        <div className="mt-6 bg-white border border-slate-200 p-5" data-testid="asset-scan-found">
          <div className="font-semibold text-slate-900 text-lg">{a.name}</div>
          <div className="text-xs text-slate-500">{[a.brand, a.model].filter(Boolean).join(" ") || a.category} · {campusLabel(a.campus)}{a.location ? ` · ${a.location}` : ""}</div>
          <div className="font-mono text-xs text-slate-400 mt-1">{a.asset_tag}{a.serial_number ? ` · SN ${a.serial_number}` : ""}</div>
          <div className="flex gap-2 mt-4 flex-wrap">
            <Link to={`/assets/${a.id}`}><Button className="rounded-none" data-testid="asset-scan-open">{t("qr_open_asset")}</Button></Link>
            <Link to={`/assets/${a.id}/edit`}><Button variant="outline" className="rounded-none">{t("edit")}</Button></Link>
          </div>
        </div>)}

      {unknown && (
        <div className="mt-6 bg-white border border-amber-200 p-5" data-testid="asset-scan-unknown">
          <div className="font-semibold text-slate-900">{t("qr_asset_unknown")}</div>
          <div className="font-mono text-sm text-slate-600 mt-1">{unknown}</div>
          <div className="mt-4"><Link to={`/assets/new?tag=${encodeURIComponent(unknown)}`}>
            <Button className="rounded-none" data-testid="asset-scan-register">{t("qr_asset_register")}</Button></Link></div>
        </div>)}
    </div>
  );
}
