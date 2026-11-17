"""Reject pending laptop-cart loan requests that clash with a scheduled class on that cart.

Since the rule "a scheduled class holds the whole cart" was added, new requests are refused on submission; this
clears the ones that were submitted before. Dry run by default (only lists); add --apply to really reject them.

    cd backend && python reject_class_conflicts.py            # list only
    cd backend && python reject_class_conflicts.py --apply    # reject + e-mail the requesters

Uses the same database as the app (DATA_DIR / DB_FILE environment variables).
"""
import argparse

import server
from server import booking_engine as be

NOTE_TAIL = " Pengajuan ditolak otomatis; silakan ajukan ulang di jam lain."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="really reject (default: dry run)")
    args = ap.parse_args()

    conn = server.get_conn()
    now = server._local_now()
    rows = conn.execute("""SELECT b.*, r.name AS cart_name FROM bookings b JOIN resources r ON r.id = b.pool_resource_id
                           WHERE b.kind = 'pool' AND b.status IN ('pending_ict', 'submitted') AND b.end_at > ?
                           ORDER BY b.start_at""", (now.strftime(be.FMT),)).fetchall()
    hits = 0
    for b in rows:
        occ = be.cart_class_conflict(conn, b["pool_resource_id"], be.parse_dt(b["start_at"]), be.parse_dt(b["end_at"]))
        if not occ:
            continue
        hits += 1
        note = be.class_conflict_message(occ, b["cart_name"]) + NOTE_TAIL
        print(f"{b['number']}  {b['cart_name']}  {b['start_at']}–{b['end_at'][11:]}  {b['requester_name']}  -> {note}")
        if not args.apply:
            continue
        done = be.decide(conn, booking_id=b["id"], decision="rejected", by_id="system", by_name="Sistem (jadwal kelas)", now=now, note=note)
        _, asset = server._loan_context(conn, b["id"])
        who = conn.execute("SELECT email FROM users WHERE id = ?", (b["requester_id"],)).fetchone()
        if who:
            server.queue_email(conn, who["email"], f'[YPJ Assets] Pengajuan Ditolak: {done["number"]}',
                               server._loan_mail(done, asset, "Pengajuan Ditolak", [("Diputuskan oleh", "Sistem (jadwal kelas)"), ("Catatan", note)], ""),
                               "loan_decided", b["id"])
        conn.commit()
    verb = "ditolak" if args.apply else "akan ditolak (dry run, tambahkan --apply)"
    print(f"\n{hits} dari {len(rows)} pengajuan pending {verb}.")
    conn.close()


if __name__ == "__main__":
    main()
