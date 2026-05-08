import { useState } from "react";
import { useLang } from "../context/LangContext";
import {
  ScrollText, Monitor, Package, ArrowRightLeft, BookOpen,
  ShieldCheck, ChevronDown, ChevronUp,
} from "lucide-react";

const POLICIES = [
  {
    id: "rup",
    icon: Monitor,
    color: "bg-blue-50 border-blue-200 text-blue-700",
    dot: "bg-blue-500",
    titleKey: "pol_rup_title",
    tagKey: "pol_tag_ict",
    sections: [
      { headingKey: "pol_rup_purpose_h",   bodyKey: "pol_rup_purpose" },
      { headingKey: "pol_rup_scope_h",      bodyKey: "pol_rup_scope" },
      { headingKey: "pol_rup_acceptable_h", bodyKey: "pol_rup_acceptable", list: true },
      { headingKey: "pol_rup_prohibited_h", bodyKey: "pol_rup_prohibited", list: true },
      { headingKey: "pol_rup_breach_h",     bodyKey: "pol_rup_breach" },
    ],
  },
  {
    id: "asset-care",
    icon: Package,
    color: "bg-amber-50 border-amber-200 text-amber-700",
    dot: "bg-amber-500",
    titleKey: "pol_care_title",
    tagKey: "pol_tag_asset",
    sections: [
      { headingKey: "pol_care_purpose_h",    bodyKey: "pol_care_purpose" },
      { headingKey: "pol_care_obligations_h", bodyKey: "pol_care_obligations", list: true },
      { headingKey: "pol_care_damage_h",      bodyKey: "pol_care_damage" },
      { headingKey: "pol_care_reporting_h",   bodyKey: "pol_care_reporting" },
    ],
  },
  {
    id: "loan-transfer",
    icon: ArrowRightLeft,
    color: "bg-emerald-50 border-emerald-200 text-emerald-700",
    dot: "bg-emerald-500",
    titleKey: "pol_loan_title",
    tagKey: "pol_tag_asset",
    sections: [
      { headingKey: "pol_loan_purpose_h",    bodyKey: "pol_loan_purpose" },
      { headingKey: "pol_loan_eligibility_h", bodyKey: "pol_loan_eligibility", list: true },
      { headingKey: "pol_loan_process_h",     bodyKey: "pol_loan_process", list: true },
      { headingKey: "pol_loan_return_h",      bodyKey: "pol_loan_return" },
    ],
  },
  {
    id: "data-privacy",
    icon: ShieldCheck,
    color: "bg-purple-50 border-purple-200 text-purple-700",
    dot: "bg-purple-500",
    titleKey: "pol_privacy_title",
    tagKey: "pol_tag_data",
    sections: [
      { headingKey: "pol_privacy_purpose_h",     bodyKey: "pol_privacy_purpose" },
      { headingKey: "pol_privacy_principles_h",  bodyKey: "pol_privacy_principles", list: true },
      { headingKey: "pol_privacy_access_h",       bodyKey: "pol_privacy_access" },
      { headingKey: "pol_privacy_breach_h",       bodyKey: "pol_privacy_breach" },
    ],
  },
  {
    id: "inventory",
    icon: BookOpen,
    color: "bg-slate-50 border-slate-200 text-slate-700",
    dot: "bg-slate-500",
    titleKey: "pol_inv_title",
    tagKey: "pol_tag_admin",
    sections: [
      { headingKey: "pol_inv_purpose_h",    bodyKey: "pol_inv_purpose" },
      { headingKey: "pol_inv_register_h",   bodyKey: "pol_inv_register", list: true },
      { headingKey: "pol_inv_audit_h",      bodyKey: "pol_inv_audit" },
      { headingKey: "pol_inv_disposal_h",   bodyKey: "pol_inv_disposal" },
    ],
  },
];

function PolicyCard({ policy, t }) {
  const [open, setOpen] = useState(false);
  const Icon = policy.icon;

  return (
    <div id={policy.id} className="bg-white border border-slate-200 scroll-mt-8 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-4 p-6 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-4">
          <div className={`w-10 h-10 flex-shrink-0 border flex items-center justify-center ${policy.color}`}>
            <Icon className="w-5 h-5" strokeWidth={1.5} />
          </div>
          <div>
            <div className="font-display text-lg font-semibold text-slate-900">{t(policy.titleKey)}</div>
            <span className={`inline-block mt-1 text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-sm ${policy.color} border`}>
              {t(policy.tagKey)}
            </span>
          </div>
        </div>
        {open
          ? <ChevronUp className="w-4 h-4 text-slate-400 flex-shrink-0" strokeWidth={1.75} />
          : <ChevronDown className="w-4 h-4 text-slate-400 flex-shrink-0" strokeWidth={1.75} />}
      </button>

      {open && (
        <div className="border-t border-slate-100 px-6 pb-6 pt-5 space-y-5">
          {policy.sections.map((sec) => (
            <div key={sec.headingKey}>
              <h3 className="label-mono text-slate-700 mb-2">{t(sec.headingKey)}</h3>
              {sec.list ? (
                <ul className="space-y-1.5 pl-1">
                  {t(sec.bodyKey).split("||").map((item, i) => (
                    <li key={i} className="flex gap-2 text-sm text-slate-600 leading-relaxed">
                      <span className={`mt-2 w-1.5 h-1.5 rounded-full flex-shrink-0 ${policy.dot}`} />
                      <span>{item.trim()}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-600 leading-relaxed">{t(sec.bodyKey)}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function PoliciesPage() {
  const { t } = useLang();

  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto">
      <div className="label-mono mb-2">{t("pol_section")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-2">
        {t("pol_title")}
      </h1>
      <p className="text-sm text-slate-500 mb-8 max-w-xl">{t("pol_subtitle")}</p>

      <div className="flex gap-8 items-start">
        {/* TOC — desktop */}
        <aside className="hidden lg:block w-56 flex-shrink-0 sticky top-20">
          <div className="label-mono text-slate-500 mb-3">{t("pol_toc")}</div>
          <nav className="space-y-1">
            {POLICIES.map((p) => (
              <a
                key={p.id}
                href={`#${p.id}`}
                className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900 py-1.5 border-l-2 border-transparent hover:border-slate-400 pl-3 transition-colors"
              >
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${p.dot}`} />
                {t(p.titleKey)}
              </a>
            ))}
          </nav>

          <div className="mt-8 p-4 bg-slate-50 border border-slate-200 text-xs text-slate-500 leading-relaxed">
            <div className="font-semibold text-slate-700 mb-1">{t("pol_effective")}</div>
            {t("pol_effective_date")}
          </div>
        </aside>

        {/* Policy cards */}
        <div className="flex-1 space-y-3 min-w-0">
          {POLICIES.map((p) => (
            <PolicyCard key={p.id} policy={p} t={t} />
          ))}

          <div className="mt-6 bg-slate-900 text-white p-6">
            <div className="label-mono text-slate-400 mb-1">{t("pol_questions")}</div>
            <p className="text-sm text-slate-300">{t("pol_questions_body")}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
