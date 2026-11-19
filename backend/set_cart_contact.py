"""Set who is told by WhatsApp about new loan requests for a cart / lab (same as the fields in Pengaturan > Cart & lab).

One cart / lab by exact name:
    cd backend && python set_cart_contact.py "D5 | Laptop Cart SMP #2" --name "Pak Yusriadi" --phone 08xxxxxxxxxx
    cd backend && python set_cart_contact.py "D5 | Laptop Cart SMP #2" --clear

Every cart AND lab of one location at once (names start with the room code, e.g. "E5 |"); lists first, add --apply to save:
    cd backend && python set_cart_contact.py --prefix "E5 |" --name "Ibu Jeni" --phone 08xxxxxxxxxx
    cd backend && python set_cart_contact.py --prefix "E5 |" --name "Ibu Jeni" --phone 08xxxxxxxxxx --apply
"""
import argparse
import sys

import server


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cart", nargs="?", default="", help="exact name of the cart / lab")
    ap.add_argument("--prefix", default="", help="every cart / lab whose name starts with this (e.g. 'E5 |')")
    ap.add_argument("--name", default="")
    ap.add_argument("--phone", default="")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--apply", action="store_true", help="with --prefix: really save (default: only list)")
    a = ap.parse_args()
    if bool(a.cart) == bool(a.prefix):
        sys.exit("Isi nama cart/lab persis, atau --prefix (salah satu).")
    if not a.clear and not a.phone:
        sys.exit("Isi --phone, atau pakai --clear untuk menghapus.")
    conn = server.get_conn()
    if a.prefix:
        rows = conn.execute("SELECT id, name, kind, notify_name, notify_phone FROM resources WHERE name LIKE ? ESCAPE '\\' AND active = 1 ORDER BY name",
                            (a.prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)).fetchall()
        if not rows:
            sys.exit(f"Tidak ada cart/lab aktif yang namanya diawali '{a.prefix}'.")
    else:
        rows = conn.execute("SELECT id, name, kind, notify_name, notify_phone FROM resources WHERE name = ?", (a.cart,)).fetchall()
        if len(rows) != 1:
            sys.exit(f"Cart '{a.cart}' tidak ditemukan tepat satu (ditemukan {len(rows)}).")
    phone = "" if a.clear else server.normalize_phone(a.phone)
    name = "" if a.clear else a.name.strip()
    save = a.apply or not a.prefix
    for r in rows:
        before = f"{r['notify_name']} +{r['notify_phone']}" if r["notify_phone"] else "tanpa penerima"
        print(f"{r['name']} ({r['kind']}): {before} -> " + (f"{name} +{phone}" if phone else "tanpa penerima"))
        if save:
            conn.execute("UPDATE resources SET notify_phone = ?, notify_name = ? WHERE id = ?", (phone, name, r["id"]))
    if save:
        conn.commit()
        print("Tersimpan.")
    else:
        print("\nBelum disimpan. Tambahkan --apply untuk menyimpan.")


if __name__ == "__main__":
    main()
