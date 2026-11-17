"""Load the fixed class schedule of "D5 | Laptop Cart SMP #2" (from "Booking Laptop SMP Cart 2 laptop.pdf").

Settings (school year, semester, validity dates, campus) are copied from the schedule of the reference cart
"E5 | Laptop Cart SMP #1", so both carts behave the same. Every row goes through the same validation as the
schedule form (periods exist, units fit the cart, no clash). Dry run by default; add --apply to save.

    cd backend && python import_cart_d5_schedule.py            # check only
    cd backend && python import_cart_d5_schedule.py --apply    # save

Refuses to run when the cart already has schedules, so it can never double up.
"""
import argparse
import sys
from collections import Counter

import server
from server import booking_engine as be

TARGET = "D5 | Laptop Cart SMP #2"
REFERENCE = "E5 | Laptop Cart SMP #1"

MATELDA, DENNY = "Matelda Alfonsina Ibo, S.Pd.", "Denny Paluruan, S.Si."
JUNICHE, KARTIKA = "Juniche Anggelique Tnunay, S.Pd., B.Ed.", "Kartika Rachma, S.S., M.M."
VISKA, ELIA, FIRDAUS, MARYADI = "Viska Lali", "Elia Suwi, S.Pd.", "Firdaus, S.Pd.", "Maryadi, S.Pd."
BI, IPA, IPS, DD = "Bahasa Indonesia", "Ilmu Pengetahuan Alam", "Ilmu Pengetahuan Sosial", "Digital Desain"
MAT, SB, PJOK = "Matematika", "Seni Budaya", "Pendidikan Jasmani Olahraga dan Kesehatan"

# weekday (0 = Monday): (class, subject, teacher, laptops, period_from, period_to)
SCHEDULE = {
    0: [("8C", BI, MATELDA, 11, 1, 4), ("8C", IPA, DENNY, 5, 3, 4), ("8A", BI, MATELDA, 11, 6, 7), ("8A", IPA, JUNICHE, 12, 8, 9)],
    1: [("7A", IPA, JUNICHE, 12, 1, 2), ("8A", DD, KARTIKA, 13, 1, 2), ("8C", DD, KARTIKA, 13, 3, 4),
        ("7C", IPA, JUNICHE, 12, 5, 6), ("8B", DD, KARTIKA, 13, 5, 6), ("9A", PJOK, FIRDAUS, 6, 7, 7), ("7B", IPA, JUNICHE, 12, 8, 9)],
    2: [("9A", DD, VISKA, 12, 1, 2), ("7A", MAT, ELIA, 10, 1, 2), ("9A", SB, MATELDA, 5, 3, 4), ("9B", DD, VISKA, 12, 5, 6),
        ("8C", IPA, DENNY, 5, 5, 6), ("9C", DD, VISKA, 12, 7, 8), ("7C", MAT, ELIA, 10, 7, 8)],
    3: [("9B", IPA, DENNY, 5, 1, 2), ("9C", PJOK, FIRDAUS, 6, 4, 4), ("9A", IPA, DENNY, 5, 5, 6), ("7A", PJOK, FIRDAUS, 6, 5, 5),
        ("8A", IPS, MARYADI, 13, 7, 8), ("7B", PJOK, FIRDAUS, 6, 7, 7), ("9C", IPA, DENNY, 5, 8, 9), ("7B", MAT, ELIA, 5, 8, 9)],
    4: [("9C", SB, MATELDA, 5, 1, 2), ("7C", PJOK, FIRDAUS, 6, 1, 1)],
}
DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat"]


def find_cart(conn, name):
    rows = conn.execute("SELECT * FROM resources WHERE name = ? AND active = 1", (name,)).fetchall()
    if len(rows) != 1:
        sys.exit(f"Cart '{name}' harus ada tepat satu (ditemukan {len(rows)}).")
    return dict(rows[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="save (default: check only)")
    args = ap.parse_args()
    conn = server.get_conn()
    target, ref = find_cart(conn, TARGET), find_cart(conn, REFERENCE)
    if conn.execute("SELECT 1 FROM fixed_schedules WHERE resource_id = ? LIMIT 1", (target["id"],)).fetchone():
        sys.exit(f"{TARGET} sudah punya jadwal tetap; tidak ada yang diubah. Hapus/ubah lewat halaman Jadwal & lab.")
    refs = conn.execute("""SELECT academic_year, semester, valid_from, valid_to FROM fixed_schedules
                           WHERE resource_id = ? AND status = 'active'""", (ref["id"],)).fetchall()
    if not refs:
        sys.exit(f"{REFERENCE} belum punya jadwal untuk dijadikan acuan.")
    (year, sem, vfrom, vto), _ = Counter(tuple(r) for r in refs).most_common(1)[0]
    print(f"Acuan {REFERENCE}: {year} {sem}, berlaku {vfrom} s/d {vto}; kapasitas {TARGET}: {be.resource_capacity(conn, target['id'])} unit\n")

    problems, rows = 0, []
    for wd, items in SCHEDULE.items():
        for cls, subj, teacher, units, p1, p2 in items:
            data = {"resource_id": target["id"], "campus": target["campus"], "academic_year": year, "semester": sem, "class_name": cls,
                    "subject": subj, "teacher_user_id": None, "teacher_name": teacher, "weekday": wd, "period_from": p1, "period_to": p2,
                    "units": units, "valid_from": vfrom, "valid_to": vto, "status": "active"}
            # rows of this import are checked against each other too (validate_schedule only sees saved rows)
            errs = be.validate_schedule(conn, data, now=server._local_now()) if args.apply else _check_dry(conn, data, rows)
            print(f"{'OK ' if not errs else 'ERR'} {DAYS[wd]:6} jam {p1}-{p2}  {cls:3} {subj[:24]:24} {units:>2} laptop  {teacher}" + (f"  <- {' '.join(errs)}" if errs else ""))
            problems += bool(errs)
            rows.append(data)
            if args.apply and not errs:
                _insert(conn, data)
    print(f"\n{len(rows)} sesi, {problems} bermasalah.")
    if args.apply:
        if problems:
            conn.rollback()
            sys.exit("Ada baris bermasalah: semua dibatalkan, tidak ada yang tersimpan.")
        conn.commit()
        print("Tersimpan.")
    else:
        print("Dry run: belum ada yang disimpan. Tambahkan --apply untuk menyimpan.")
    conn.close()


def _check_dry(conn, data, earlier):
    """Same checks as validate_schedule, plus clashes with the rows of this import that are not saved yet."""
    errs = be.validate_schedule(conn, data, now=server._local_now())
    cap = be.resource_capacity(conn, data["resource_id"])
    for o in earlier:
        if o["weekday"] == data["weekday"] and o["period_from"] <= data["period_to"] and o["period_to"] >= data["period_from"] \
                and o["units"] + data["units"] > cap:
            errs.append(f"Bentrok dengan {o['class_name']} ({o['teacher_name']}) pada jam yang sama.")
    return errs


def _insert(conn, d):
    conn.execute("""INSERT INTO fixed_schedules (id, campus, academic_year, semester, resource_id, class_name, subject, teacher_user_id, teacher_name,
                    weekday, period_from, period_to, units, valid_from, valid_to, status, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (be.new_id(), d["campus"], d["academic_year"], d["semester"], d["resource_id"], d["class_name"], d["subject"], None,
                  d["teacher_name"], d["weekday"], d["period_from"], d["period_to"], d["units"], d["valid_from"], d["valid_to"], "active",
                  "import-d5", server.now_iso()))


if __name__ == "__main__":
    main()
