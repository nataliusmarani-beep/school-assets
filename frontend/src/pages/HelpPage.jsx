import { useLang } from "../context/LangContext";

export default function HelpPage() {
  const { t } = useLang();

  const sections = [
    {
      title: t("help_s1_title"),
      items: [
        { q: t("help_q1"), a: t("help_a1") },
        { q: t("help_q2"), a: t("help_a2") },
        { q: t("help_q3"), a: t("help_a3") },
      ],
    },
    {
      title: t("help_s2_title"),
      items: [
        { q: t("help_q4"), a: t("help_a4") },
        { q: t("help_q5"), a: t("help_a5") },
      ],
    },
    {
      title: t("help_s3_title"),
      items: [
        { q: t("help_q6"), a: t("help_a6") },
      ],
    },
  ];

  return (
    <div className="p-6 lg:p-10 max-w-[900px] mx-auto">
      <div className="label-mono mb-2">{t("support")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-8">
        {t("help_guide")}
      </h1>
      <div className="space-y-8">
        {sections.map((s) => (
          <div key={s.title} className="bg-white border border-slate-200">
            <div className="px-6 py-4 border-b border-slate-100 label-mono">{s.title}</div>
            <div className="divide-y divide-slate-100">
              {s.items.map((item) => (
                <div key={item.q} className="px-6 py-4">
                  <div className="font-medium text-slate-900 mb-1">{item.q}</div>
                  <div className="text-sm text-slate-600">{item.a}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
