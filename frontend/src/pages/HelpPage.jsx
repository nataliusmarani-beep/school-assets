const sections = [
  {
    title: "Getting started",
    items: [
      { q: "How do I add a new asset?", a: "Go to Assets → click \"+ Add asset\", fill in the details and save." },
      { q: "How do I assign an asset to a person?", a: "Open the asset detail page and use the \"Transfer / Assign\" button." },
      { q: "What is a campus?", a: "Campus identifies which YPJ school site (Kuala Kencana or Tembagapura) the asset belongs to." },
    ],
  },
  {
    title: "Faults & Compliance",
    items: [
      { q: "How do I report a fault?", a: "On the asset detail page, open the Faults tab and click \"Report fault\"." },
      { q: "What does the Compliance module track?", a: "Scheduled inspections, certifications, and maintenance deadlines linked to assets." },
    ],
  },
  {
    title: "Depreciation",
    items: [
      { q: "How is book value calculated?", a: "Straight-line depreciation: (Purchase price) ÷ (Useful life years), prorated by time elapsed." },
    ],
  },
];

export default function HelpPage() {
  return (
    <div className="p-6 lg:p-10 max-w-[900px] mx-auto">
      <div className="label-mono mb-2">Support</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-8">
        Help &amp; Guide
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
