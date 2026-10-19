import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useLang } from "../context/LangContext";
import {
  HelpCircle, LayoutDashboard, Plus, Search, ArrowLeftRight,
  Wrench, ShieldCheck, TrendingDown, Users, Upload,
  FileSignature, BookOpen, CalendarDays, ScanLine, Laptop,
} from "lucide-react";

const SECTION_IDS = [
  { id: "getting-started",  icon: HelpCircle,      titleKey: "help_s1_title" },
  { id: "policies",         icon: FileSignature,   titleKey: "help_s11_title" },
  { id: "dashboard",        icon: LayoutDashboard, titleKey: "help_s2_title" },
  { id: "register-asset",   icon: Plus,            titleKey: "help_s3_title" },
  { id: "find-filter",      icon: Search,          titleKey: "help_s4_title" },
  { id: "transfer",         icon: ArrowLeftRight,  titleKey: "help_s5_title" },
  { id: "loans",            icon: BookOpen,        titleKey: "help_s12_title" },
  { id: "schedule",         icon: CalendarDays,    titleKey: "help_s13_title" },
  { id: "qr",               icon: ScanLine,        titleKey: "help_s14_title" },
  { id: "byod",             icon: Laptop,          titleKey: "help_s15_title" },
  { id: "faults",           icon: Wrench,          titleKey: "help_s6_title" },
  { id: "compliance",       icon: ShieldCheck,     titleKey: "help_s7_title" },
  { id: "depreciation",     icon: TrendingDown,    titleKey: "help_s8_title" },
  { id: "users",            icon: Users,           titleKey: "help_s9_title" },
  { id: "attachments",      icon: Upload,          titleKey: "help_s10_title" },
];

function SectionHeader({ id, icon: Icon, title }) {
  return (
    <div id={id} className="flex items-center gap-4 mb-5 scroll-mt-8">
      <div className="w-11 h-11 flex-shrink-0 border border-blue-200 bg-blue-50 flex items-center justify-center">
        <Icon className="w-5 h-5 text-blue-700" strokeWidth={1.5} />
      </div>
      <h2 className="font-display text-2xl font-semibold text-slate-900">{title}</h2>
    </div>
  );
}

function P({ children }) {
  return <p className="text-slate-700 leading-relaxed mb-4">{children}</p>;
}

function Ul({ items }) {
  return (
    <ul className="mb-4 space-y-1.5 pl-1">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2 text-slate-700 leading-relaxed">
          <span className="mt-2 w-1.5 h-1.5 rounded-full bg-slate-400 flex-shrink-0" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function Ol({ items }) {
  return (
    <ol className="mb-4 space-y-2 pl-1">
      {items.map((item, i) => (
        <li key={i} className="flex gap-3 text-slate-700 leading-relaxed">
          <span className="flex-shrink-0 font-medium text-slate-500">{i + 1}.</span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

function CodeBlock({ children }) {
  return (
    <pre className="mb-4 bg-white border border-slate-200 rounded-sm p-4 text-sm font-mono text-slate-700 overflow-x-auto leading-relaxed whitespace-pre">
      {children}
    </pre>
  );
}

function Bold({ children }) {
  return <span className="font-semibold text-slate-900">{children}</span>;
}


const helpImgs = require.context("../assets/help", false, /\.jpg$/);
const shot = (lang, name) => helpImgs(`./${lang.toLowerCase()}-${name}.jpg`);

/** Screenshot in a browser, phone or tablet frame; click to enlarge. */
function Shot({ name, kind = "browser", className = "" }) {
  const { lang, t } = useLang();
  const [open, setOpen] = useState(false);
  const src = shot(lang, name);
  const img = <img src={src} alt="" loading="lazy" draggable={false} className="block w-full h-auto" />;
  const frame = kind === "phone" ? (
    <div className="rounded-[1.6rem] bg-slate-900 p-2 shadow-xl ring-1 ring-slate-700">{<div className="rounded-[1.1rem] overflow-hidden bg-white">{img}</div>}</div>
  ) : kind === "tablet" ? (
    <div className="rounded-2xl bg-slate-900 p-2 shadow-xl ring-1 ring-slate-700"><div className="rounded-lg overflow-hidden bg-white">{img}</div></div>
  ) : (
    <div className="rounded-md bg-white border border-slate-300 shadow-xl overflow-hidden">
      <div className="h-6 bg-slate-100 border-b border-slate-200 flex items-center gap-1.5 px-3">
        <span className="w-2 h-2 rounded-full bg-rose-300" /><span className="w-2 h-2 rounded-full bg-amber-300" /><span className="w-2 h-2 rounded-full bg-emerald-300" />
      </div>
      {img}
    </div>
  );
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title={t("help_fig_zoom")} className={`block text-left cursor-zoom-in ${className}`}>{frame}</button>
      {open && (
        <div className="fixed inset-0 z-[120] bg-slate-900/85 flex items-center justify-center p-4 cursor-zoom-out" onClick={() => setOpen(false)} role="dialog" aria-modal="true">
          <button type="button" className="absolute top-4 right-4 text-white/80 hover:text-white" aria-label="Close"><X className="w-6 h-6" /></button>
          <img src={src} alt="" className={`max-h-[92vh] ${kind === "phone" ? "max-w-[min(92vw,420px)]" : "max-w-[96vw]"} object-contain shadow-2xl`} />
        </div>
      )}
    </>
  );
}

function Figure({ caption, children, className = "" }) {
  return (
    <figure className={`my-6 ${className}`}>
      {children}
      {caption && <figcaption className="mt-3 text-sm text-slate-500 text-center">{caption}</figcaption>}
    </figure>
  );
}

/** Laptop + phone side by side (stacked on small screens). */
function Pair({ laptop, phone, caption }) {
  return (
    <Figure caption={caption}>
      <div className="flex flex-col sm:flex-row gap-6 items-center sm:items-end">
        <div className="flex-1 min-w-0 w-full"><Shot name={laptop} /></div>
        <div className="w-[190px] flex-shrink-0"><Shot name={phone} kind="phone" /></div>
      </div>
    </Figure>
  );
}

function Hero({ caption }) {
  return (
    <figure className="mb-8 rounded-lg border border-slate-200 bg-gradient-to-br from-slate-50 to-blue-50 p-5 sm:p-8">
      <div className="flex items-end justify-center gap-3 sm:gap-6">
        <div className="flex-1 min-w-0 max-w-[560px]"><Shot name="dashboard" /></div>
        <div className="hidden sm:block w-[150px] flex-shrink-0"><Shot name="dashboard-tablet" kind="tablet" /></div>
        <div className="w-[84px] sm:w-[110px] flex-shrink-0"><Shot name="dashboard-phone" kind="phone" /></div>
      </div>
      <figcaption className="mt-4 text-sm text-slate-500 text-center">{caption}</figcaption>
    </figure>
  );
}

export default function HelpPage() {
  const { t } = useLang();
  const [active, setActive] = useState("getting-started");

  useEffect(() => {
    const ids = SECTION_IDS.map((s) => s.id);
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setActive(entry.target.id);
        });
      },
      { rootMargin: "-20% 0px -70% 0px" }
    );
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto">
      <div className="label-mono mb-2">{t("documentation")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-2">
        {t("help_guide")}
      </h1>
      <p className="text-slate-500 mb-10 max-w-xl">{t("help_subtitle")}</p>

      <div className="flex gap-10 items-start">
        {/* Sidebar TOC */}
        <aside className="hidden lg:block w-52 flex-shrink-0 sticky top-6">
          <div className="label-mono mb-3 text-slate-400">{t("help_toc_label")}</div>
          <nav className="space-y-0.5">
            {SECTION_IDS.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className={`block text-sm py-1.5 pl-3 border-l-2 transition-colors ${
                  active === s.id
                    ? "border-blue-600 text-blue-700 font-medium"
                    : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
                }`}
              >
                {t(s.titleKey)}
              </a>
            ))}
          </nav>

          <div className="mt-8 p-4 border border-slate-200 bg-slate-50">
            <div className="label-mono text-slate-400 mb-2">{t("help_need_help_title")}</div>
            <p className="text-xs text-slate-500 leading-relaxed">{t("help_need_help_body")}</p>
          </div>
        </aside>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-12">

          <section>
            <SectionHeader id="getting-started" icon={HelpCircle} title={t("help_s1_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s1_intro")}</P>
            <Hero caption={t("help_fig_hero")} />
            <P><Bold>{t("help_s1_roles_heading")}</Bold></P>
            <Ul items={[t("help_s1_role_admin"), t("help_s1_role_staff"), t("help_s1_role_ict"), t("help_s1_role_leader")]} />
          </section>

          <section>
            <SectionHeader id="policies" icon={FileSignature} title={t("help_s11_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s11_intro")}</P>
            <Figure caption={t("help_fig_policy")}><Shot name="policy" /></Figure>
            <Ol items={[t("help_s11_step1"), t("help_s11_step2"), t("help_s11_step3")]} />
            <P>{t("help_s11_note")}</P>
          </section>

          <section>
            <SectionHeader id="dashboard" icon={LayoutDashboard} title={t("help_s2_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s2_intro")}</P>
            <Figure caption={t("help_fig_dashboard")}><Shot name="dashboard" /></Figure>
            <Ul items={[t("help_s2_kpi1"), t("help_s2_kpi2"), t("help_s2_kpi3"), t("help_s2_kpi4")]} />
            <P>{t("help_s2_outro")}</P>
          </section>

          <section>
            <SectionHeader id="register-asset" icon={Plus} title={t("help_s3_title")} />
            <hr className="border-slate-200 mb-6" />
            <Figure caption={t("help_fig_asset_new")}><Shot name="asset-new" /></Figure>
            <Ol items={[
              t("help_s3_step1"), t("help_s3_step2"), t("help_s3_step3"),
              t("help_s3_step4"), t("help_s3_step5"),
            ]} />
          </section>

          <section>
            <SectionHeader id="find-filter" icon={Search} title={t("help_s4_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s4_intro")}</P>
            <Figure caption={t("help_fig_assets")}><Shot name="assets" /></Figure>
            <Ul items={[t("help_s4_tip1"), t("help_s4_tip2"), t("help_s4_tip3"), t("help_s4_tip4")]} />
            <P>{t("help_s4_outro")}</P>
          </section>

          <section>
            <SectionHeader id="transfer" icon={ArrowLeftRight} title={t("help_s5_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s5_intro")}</P>
            <Pair laptop="asset-detail" phone="my-assets" caption={t("help_fig_asset_detail") + " " + t("help_fig_my_assets")} />
            <Ol items={[t("help_s5_step1"), t("help_s5_step2"), t("help_s5_step3"), t("help_s5_step4")]} />
            <P>{t("help_s5_note")}</P>
          </section>

          <section>
            <SectionHeader id="loans" icon={BookOpen} title={t("help_s12_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s12_intro")}</P>
            <Pair laptop="loans-borrow" phone="borrow-dialog" caption={t("help_fig_borrow") + " " + t("help_fig_borrow_dialog")} />
            <Ol items={[t("help_s12_step1"), t("help_s12_step2"), t("help_s12_step3"), t("help_s12_step4"), t("help_s12_step5"), t("help_s12_step6")]} />
            <P>{t("help_s12_note")}</P>
            <P><Bold>{t("help_s12_ict")}</Bold></P>
            <Figure caption={t("help_fig_loan_detail")}><Shot name="loan-detail" /></Figure>
          </section>

          <section>
            <SectionHeader id="schedule" icon={CalendarDays} title={t("help_s13_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s13_intro")}</P>
            <Figure caption={t("help_fig_schedule")}><Shot name="schedule" /></Figure>
            <Ul items={[t("help_s13_tip1"), t("help_s13_tip2"), t("help_s13_tip3")]} />
          </section>

          <section>
            <SectionHeader id="qr" icon={ScanLine} title={t("help_s14_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s14_intro")}</P>
            <Figure caption={t("help_fig_scan")}><div className="max-w-[230px] mx-auto"><Shot name="scan" kind="phone" /></div></Figure>
            <Ul items={[t("help_s14_tip1"), t("help_s14_tip2"), t("help_s14_tip3")]} />
          </section>

          <section>
            <SectionHeader id="byod" icon={Laptop} title={t("help_s15_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s15_intro")}</P>
            <Pair laptop="byod-detail" phone="byod-sign" caption={t("help_fig_byod_detail") + " " + t("help_fig_byod_sign")} />
            <Ol items={[t("help_s15_step1"), t("help_s15_step2"), t("help_s15_step3"), t("help_s15_step4")]} />
            <P>{t("help_s15_note")}</P>
          </section>

          <section>
            <SectionHeader id="faults" icon={Wrench} title={t("help_s6_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s6_intro")}</P>
            <Figure caption={t("help_fig_faults")}><Shot name="faults" /></Figure>
            <P>{t("help_s6_workflow_heading")}</P>
            <Ul items={[t("help_s6_status1"), t("help_s6_status2"), t("help_s6_status3")]} />
            <P>{t("help_s6_actions")}</P>
          </section>

          <section>
            <SectionHeader id="compliance" icon={ShieldCheck} title={t("help_s7_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s7_intro")}</P>
            <Figure caption={t("help_fig_compliance")}><Shot name="compliance" /></Figure>
            <Ul items={[t("help_s7_tip1"), t("help_s7_tip2"), t("help_s7_tip3")]} />
          </section>

          <section>
            <SectionHeader id="depreciation" icon={TrendingDown} title={t("help_s8_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s8_warranty")}</P>
            <P>{t("help_s8_dep_intro")}</P>
            <CodeBlock>{`annual_depreciation = purchase_price / useful_life_years\ncurrent_book_value  = purchase_price − (annual × age_in_years)`}</CodeBlock>
            <P>{t("help_s8_outro")}</P>
          </section>

          <section>
            <SectionHeader id="users" icon={Users} title={t("help_s9_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s9_intro")}</P>
            <Figure caption={t("help_fig_users")}><Shot name="users" /></Figure>
            <Ol items={[t("help_s9_step1"), t("help_s9_step2"), t("help_s9_step3")]} />
            <P>{t("help_s9_note")}</P>
          </section>

          <section>
            <SectionHeader id="attachments" icon={Upload} title={t("help_s10_title")} />
            <hr className="border-slate-200 mb-6" />
            <P>{t("help_s10_intro")}</P>
            <Ul items={[t("help_s10_tip1"), t("help_s10_tip2"), t("help_s10_tip3")]} />
          </section>

        </div>
      </div>
    </div>
  );
}
