export default function ReportsPage() {
  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto">
      <div className="label-mono mb-2">Analytics</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-8">
        Reports
      </h1>
      <div className="bg-white border border-slate-200 p-16 flex flex-col items-center justify-center text-center">
        <div className="w-12 h-12 bg-slate-100 flex items-center justify-center mb-4">
          <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
          </svg>
        </div>
        <div className="font-display text-lg text-slate-700 mb-1">Reports coming soon</div>
        <div className="text-sm text-slate-500">Asset summaries, depreciation reports and export tools will appear here.</div>
      </div>
    </div>
  );
}
