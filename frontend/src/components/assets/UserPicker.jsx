import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";

const label = (u) => `${u.name}${u.department ? ` — ${u.department}` : ""}`;

/** Searchable replacement for a user <select>: type part of a name, department or e-mail, then pick. */
export default function UserPicker({ users, value, onChange, placeholder, noResults = "—", testid }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef(null);
  const selected = users.find((u) => u.id === value);

  useEffect(() => {
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return users.filter((u) => !s || [u.name, u.department, u.email].some((x) => (x || "").toLowerCase().includes(s))).slice(0, 100);
  }, [users, q]);

  const pick = (id) => { onChange(id); setOpen(false); setQ(""); };

  return (
    <div className="relative mt-2" ref={box}>
      <div className="flex items-center border border-slate-300 bg-white h-10 px-3 focus-within:border-slate-900">
        <input
          value={open ? q : (selected ? label(selected) : "")}
          placeholder={placeholder}
          onFocus={() => { setOpen(true); setQ(""); }}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); if (shown[0]) pick(shown[0].id); }
            if (e.key === "Escape") setOpen(false);
          }}
          className="flex-1 min-w-0 outline-none text-sm bg-transparent"
          data-testid={testid}
          autoComplete="off"
        />
        {value && !open
          ? <button type="button" onClick={() => pick("")} aria-label="clear" className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
          : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </div>
      {open && (
        <ul className="absolute z-50 mt-1 w-full max-h-60 overflow-y-auto bg-white border border-slate-300 shadow-lg text-sm" data-testid={testid ? `${testid}-list` : undefined}>
          {shown.length === 0 && <li className="px-3 py-2 text-slate-400">{noResults}</li>}
          {shown.map((u) => (
            <li key={u.id}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(u.id)}
                className={`w-full text-left px-3 py-2 hover:bg-slate-100 ${u.id === value ? "bg-slate-50 font-medium" : ""}`}>
                {u.name}{u.department && <span className="text-slate-500"> — {u.department}</span>}
              </button>
            </li>))}
        </ul>)}
    </div>
  );
}
