"""Set who is told by WhatsApp about new loan requests for a cart / lab (same as the fields in Pengaturan > Cart & lab).

    cd backend && python set_cart_contact.py "D5 | Laptop Cart SMP #2" --name "Pak Yusriadi" --phone 08xxxxxxxxxx
    cd backend && python set_cart_contact.py "D5 | Laptop Cart SMP #2" --clear
"""
import argparse
import sys

import server


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cart", help="exact name of the cart / lab")
    ap.add_argument("--name", default="")
    ap.add_argument("--phone", default="")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()
    conn = server.get_conn()
    rows = conn.execute("SELECT id, name FROM resources WHERE name = ?", (a.cart,)).fetchall()
    if len(rows) != 1:
        sys.exit(f"Cart '{a.cart}' tidak ditemukan tepat satu (ditemukan {len(rows)}).")
    if not a.clear and not a.phone:
        sys.exit("Isi --phone, atau pakai --clear untuk menghapus.")
    phone = "" if a.clear else server.normalize_phone(a.phone)
    conn.execute("UPDATE resources SET notify_phone = ?, notify_name = ? WHERE id = ?", (phone, "" if a.clear else a.name.strip(), rows[0]["id"]))
    conn.commit()
    print(f"{rows[0]['name']}: " + (f"{a.name} +{phone}" if phone else "tanpa penerima WA"))


if __name__ == "__main__":
    main()
