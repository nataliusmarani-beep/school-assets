import { useEffect, useState } from "react";
import { useLang } from "../context/LangContext";
import {
  HelpCircle, LayoutDashboard, Plus, Search, ArrowLeftRight,
  Wrench, ShieldCheck, TrendingDown, Users, Upload,
} from "lucide-react";

const SECTIONS = [
  { id: "getting-started",    icon: HelpCircle,      title: "Getting started" },
  { id: "dashboard",          icon: LayoutDashboard, title: "Reading the dashboard" },
  { id: "register-asset",     icon: Plus,            title: "Registering a new asset" },
  { id: "find-filter",        icon: Search,          title: "Finding & filtering assets" },
  { id: "transfer",           icon: ArrowLeftRight,  title: "Transferring ownership" },
  { id: "faults",             icon: Wrench,          title: "Reporting & resolving faults" },
  { id: "compliance",         icon: ShieldCheck,     title: "Tracking compliance" },
  { id: "depreciation",       icon: TrendingDown,    title: "Warranty & depreciation" },
  { id: "users",              icon: Users,           title: "Managing users (admin)" },
  { id: "attachments",        icon: Upload,          title: "Photos & PDF attachments" },
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

export default function HelpPage() {
  const { t } = useLang();
  const [active, setActive] = useState("getting-started");

  useEffect(() => {
    const ids = SECTIONS.map((s) => s.id);
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
      {/* Page title */}
      <div className="label-mono mb-2">{t("documentation")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-2">
        {t("help_guide")}
      </h1>
      <p className="text-slate-500 mb-10 max-w-xl">
        A quick reference for everyday tasks in the YPJ School Asset Registry. Click any topic in the contents to jump to the section.
      </p>

      <div className="flex gap-10 items-start">
        {/* Sidebar TOC */}
        <aside className="hidden lg:block w-52 flex-shrink-0 sticky top-6">
          <div className="label-mono mb-3 text-slate-400">On this page</div>
          <nav className="space-y-0.5">
            {SECTIONS.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className={`block text-sm py-1.5 pl-3 border-l-2 transition-colors ${
                  active === s.id
                    ? "border-blue-600 text-blue-700 font-medium"
                    : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
                }`}
              >
                {s.title}
              </a>
            ))}
          </nav>

          {/* Need more help */}
          <div className="mt-8 p-4 border border-slate-200 bg-slate-50">
            <div className="label-mono text-slate-400 mb-2">Need more help?</div>
            <p className="text-xs text-slate-500 leading-relaxed">
              Reach out to your school administrator or the operations team for account changes and policy questions.
            </p>
          </div>
        </aside>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-12">

          {/* Getting started */}
          <section>
            <SectionHeader id="getting-started" icon={HelpCircle} title="Getting started" />
            <hr className="border-slate-200 mb-6" />
            <P>
              Welcome to the YPJ School Asset Registry. The system gives every staff member a single, real-time view of every asset across campus — from laptops and projectors to furniture and vehicles — with depreciation, warranty and compliance tracked automatically.
            </P>
            <P><Bold>Two roles determine what you can do:</Bold></P>
            <Ul items={[
              "Admin — full access. Create/edit/delete assets, manage users, create compliance checks.",
              "Staff — read assets, transfer ownership, report faults, mark compliance complete.",
            ]} />
          </section>

          {/* Reading the dashboard */}
          <section>
            <SectionHeader id="dashboard" icon={LayoutDashboard} title="Reading the dashboard" />
            <hr className="border-slate-200 mb-6" />
            <P>The dashboard is the home page after login. It shows four KPI cards at the top:</P>
            <Ul items={[
              "Total Assets — count of every active record.",
              "Current Book Value — what your inventory is worth today, after depreciation.",
              "Accumulated Depreciation — how much value has been written off (straight-line method).",
              "Open Faults — fault reports that have not yet been resolved.",
            ]} />
            <P>
              The chart shows a 6-year forecast of book value. The right panel lists assets whose warranty is expiring (or already expired) within 60 days — click any item to open it.
            </P>
          </section>

          {/* Registering a new asset */}
          <section>
            <SectionHeader id="register-asset" icon={Plus} title="Registering a new asset" />
            <hr className="border-slate-200 mb-6" />
            <Ol items={[
              "Click Assets in the sidebar, then Add asset.",
              "Fill in Section 01 — Basic Information: name, asset tag, category, location, status, and the initial owner.",
              "In Section 02 — Financials & Warranty, enter the purchase price, purchase date, useful life (in years) and warranty end date. Depreciation is calculated automatically using the straight-line method.",
              "In Section 03 — Photo & Documents, click the photo box to upload an image of the asset, and the document box to attach PDFs (invoices, manuals, certificates).",
              "Click Create asset.",
            ]} />
          </section>

          {/* Finding & filtering assets */}
          <section>
            <SectionHeader id="find-filter" icon={Search} title="Finding & filtering assets" />
            <hr className="border-slate-200 mb-6" />
            <P>The Assets page supports advanced filtering:</P>
            <Ul items={[
              "The search box matches asset name, tag, or serial number (live, as you type).",
              "Use the Category dropdown to filter by IT Equipment, Furniture, Lab, Vehicles, etc.",
              "Use the Campus dropdown to show only one campus at a time.",
              "Use the Status dropdown to show only Active, In Repair, Retired or Lost items.",
            ]} />
            <P>Click any row to open the full asset detail page.</P>
          </section>

          {/* Transferring ownership */}
          <section>
            <SectionHeader id="transfer" icon={ArrowLeftRight} title="Transferring ownership" />
            <hr className="border-slate-200 mb-6" />
            <P>When a piece of equipment moves to a new owner, classroom or department:</P>
            <Ol items={[
              "Open the asset detail page.",
              "Click Transfer (top right).",
              "Type the new owner / location and an optional note.",
              "Click Confirm transfer.",
            ]} />
            <P>
              The full ownership trail is preserved on the Ownership tab — every transfer is timestamped, including who performed it.
            </P>
          </section>

          {/* Reporting & resolving faults */}
          <section>
            <SectionHeader id="faults" icon={Wrench} title="Reporting & resolving faults" />
            <hr className="border-slate-200 mb-6" />
            <P>
              Anyone can report a fault from an asset's detail page (Report fault button) or from the Faults page.
            </P>
            <P>Each fault has a status workflow:</P>
            <Ul items={[
              "Open — newly reported.",
              "In Progress — someone has started work on it.",
              "Resolved — fixed; a resolution note can be added.",
            ]} />
            <P>
              Faults page actions: Mark in progress moves an Open fault forward; Resolve closes it with an optional note.
            </P>
          </section>

          {/* Tracking compliance */}
          <section>
            <SectionHeader id="compliance" icon={ShieldCheck} title="Tracking compliance" />
            <hr className="border-slate-200 mb-6" />
            <P>
              Use the Compliance section for recurring regulatory requirements — fire-extinguisher recertifications, school-bus safety inspections, lab calibrations, audits, etc.
            </P>
            <Ul items={[
              "Admin creates checks with a title, category, due date and frequency (Once, Monthly, Quarterly, Annual).",
              "Items are grouped by status: Overdue, Pending, Completed.",
              "Overdue items are flagged automatically on the dashboard for action.",
            ]} />
          </section>

          {/* Warranty & depreciation */}
          <section>
            <SectionHeader id="depreciation" icon={TrendingDown} title="Warranty & depreciation" />
            <hr className="border-slate-200 mb-6" />
            <P>
              Warranty alerts appear on the dashboard for any asset whose warranty has expired or will expire within 60 days. Click an alert to open the asset and plan a renewal or replacement.
            </P>
            <P>Depreciation is calculated automatically using the straight-line method:</P>
            <CodeBlock>{`annual_depreciation = purchase_price / useful_life_years\ncurrent_book_value  = purchase_price − (annual × age_in_years)`}</CodeBlock>
            <P>
              You'll see the live numbers — annual, accumulated, and current book value — on every asset's detail page.
            </P>
          </section>

          {/* Managing users (admin) */}
          <section>
            <SectionHeader id="users" icon={Users} title="Managing users (admin)" />
            <hr className="border-slate-200 mb-6" />
            <P>Admins can invite unlimited users from the Users page:</P>
            <Ol items={[
              "Click Add user.",
              "Enter name, email, password, role (Staff or Admin), campus and department.",
              "Click Create. The user can immediately sign in with the credentials you set.",
            ]} />
            <P>
              To remove a user, click the trash icon on their row. You cannot delete your own account.
            </P>
          </section>

          {/* Photos & PDF attachments */}
          <section>
            <SectionHeader id="attachments" icon={Upload} title="Photos & PDF attachments" />
            <hr className="border-slate-200 mb-6" />
            <P>
              Each asset can have one photo and unlimited PDF/document attachments. Files are stored securely in cloud object storage and only authenticated users can access them.
            </P>
            <Ul items={[
              "Add — upload during Add/Edit asset (Section 03).",
              "View — photo appears in the Asset Detail header. Documents appear under the Documents tab.",
              "Download — click the download icon next to any document.",
            ]} />
          </section>

        </div>
      </div>
    </div>
  );
}
