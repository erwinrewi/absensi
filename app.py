import sqlite3
from datetime import date, datetime
import pandas as pd
import streamlit as st

APP_TITLE = "Absensi Sederhana (Admin Manual)"
DB_PATH = "absensi.db"

# -----------------------
# DB helpers
# -----------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        employee_code TEXT UNIQUE,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)

    # Only store exceptions from default MASUK
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('LIBUR')),
        notes TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(employee_id, work_date),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()

def query_df(sql, params=None):
    conn = get_conn()
    df = pd.read_sql_query(sql, conn, params=params or [])
    conn.close()
    return df

def execute(sql, params=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit()
    conn.close()

# -----------------------
# Business logic
# -----------------------
def get_active_employees():
    return query_df("""
        SELECT id, full_name, employee_code
        FROM employees
        WHERE is_active = 1
        ORDER BY full_name
    """)

def get_all_employees():
    return query_df("""
        SELECT id, full_name, employee_code, is_active, created_at
        FROM employees
        ORDER BY full_name
    """)

def set_libur(employee_ids, work_date: date, notes=""):
    now = datetime.now().isoformat(timespec="seconds")
    for eid in employee_ids:
        execute("""
            INSERT INTO attendance_overrides(employee_id, work_date, status, notes, created_at)
            VALUES(?, ?, 'LIBUR', ?, ?)
            ON CONFLICT(employee_id, work_date) DO UPDATE SET
                status='LIBUR',
                notes=excluded.notes
        """, [eid, work_date.isoformat(), notes, now])

def clear_override(employee_ids, work_date: date):
    for eid in employee_ids:
        execute("""
            DELETE FROM attendance_overrides
            WHERE employee_id = ? AND work_date = ?
        """, [eid, work_date.isoformat()])

def build_report(start_date: date, end_date: date):
    employees = get_active_employees()
    if employees.empty:
        return pd.DataFrame()

    overrides = query_df("""
        SELECT employee_id, COUNT(*) AS libur_days
        FROM attendance_overrides
        WHERE work_date BETWEEN ? AND ?
        GROUP BY employee_id
    """, [start_date.isoformat(), end_date.isoformat()])

    total_days = (end_date - start_date).days + 1

    rep = employees.merge(overrides, how="left", left_on="id", right_on="employee_id")
    rep["libur_days"] = rep["libur_days"].fillna(0).astype(int)
    rep["total_days"] = total_days
    rep["masuk_days"] = rep["total_days"] - rep["libur_days"]

    rep = rep[["full_name", "employee_code", "total_days", "masuk_days", "libur_days"]]
    rep = rep.sort_values("full_name").reset_index(drop=True)
    return rep

def month_range(year: int, month: int):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - pd.Timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - pd.Timedelta(days=1)
    return start, end.to_pydatetime().date()

def year_range(year: int):
    return date(year, 1, 1), date(year, 12, 31)

# -----------------------
# UI
# -----------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
init_db()

st.title(APP_TITLE)
st.caption("Aturan: default = MASUK. Admin hanya menginput pengecualian: LIBUR. Jika tidak ada input, otomatis dianggap MASUK.")

tab1, tab2, tab3 = st.tabs(["1) Karyawan", "2) Input LIBUR", "3) Rekap & Export"])

# ---- TAB 1: Employees
with tab1:
    st.subheader("Master Karyawan")

    colA, colB = st.columns([1, 2], gap="large")

    with colA:
        st.markdown("### Tambah karyawan")
        full_name = st.text_input("Nama lengkap", placeholder="Contoh: Andi Pratama", key="emp_full_name")
        employee_code = st.text_input("Kode karyawan (opsional, unik)", placeholder="Contoh: EMP-001", key="emp_code")

        if st.button("Tambah", type="primary", key="btn_add_emp"):
            if not full_name.strip():
                st.error("Nama tidak boleh kosong.")
            else:
                try:
                    execute("""
                        INSERT INTO employees(full_name, employee_code, is_active, created_at)
                        VALUES(?, ?, 1, ?)
                    """, [full_name.strip(), employee_code.strip() or None, datetime.now().isoformat(timespec="seconds")])
                    st.success("Karyawan ditambahkan.")
                except sqlite3.IntegrityError as e:
                    st.error(f"Gagal: {e}")

    with colB:
        st.markdown("### Daftar karyawan")
        df_emp = get_all_employees()
        if df_emp.empty:
            st.info("Belum ada karyawan.")
        else:
            show = df_emp.copy()
            show["status"] = show["is_active"].map({1: "Aktif", 0: "Nonaktif"})
            show = show.drop(columns=["is_active"])
            st.dataframe(show, use_container_width=True, hide_index=True)

            st.markdown("### Aktif/Nonaktif")
            ids = df_emp["id"].tolist()
            selected_id = st.selectbox(
                "Pilih karyawan",
                options=ids,
                format_func=lambda x: df_emp.loc[df_emp["id"] == x, "full_name"].values[0],
                key="emp_select_status"
            )
            new_state = st.radio("Status", options=["Aktif", "Nonaktif"], horizontal=True, key="emp_radio_status")
            if st.button("Simpan status", key="btn_save_status"):
                execute("UPDATE employees SET is_active = ? WHERE id = ?", [1 if new_state == "Aktif" else 0, selected_id])
                st.success("Status diperbarui. Refresh halaman jika perlu.")

# ---- TAB 2: Input LIBUR
with tab2:
    st.subheader("Input LIBUR (pengecualian dari default MASUK)")
    df_active = get_active_employees()

    if df_active.empty:
        st.warning("Tambahkan karyawan aktif dulu di tab Karyawan.")
    else:
        col1, col2 = st.columns([1, 1], gap="large")

        with col1:
            st.markdown("### Set LIBUR")
            d = st.date_input("Tanggal", value=date.today(), key="libur_date")
            mode = st.radio("Untuk siapa?", ["Satu karyawan", "Semua karyawan aktif"], horizontal=True, key="libur_mode")
            notes = st.text_input("Catatan (opsional)", placeholder="Contoh: Cuti bersama / Izin pribadi", key="libur_notes")

            if mode == "Satu karyawan":
                emp_id = st.selectbox(
                    "Pilih karyawan",
                    options=df_active["id"].tolist(),
                    format_func=lambda x: df_active.loc[df_active["id"] == x, "full_name"].values[0],
                    key="libur_emp_one"
                )
                target_ids = [emp_id]
            else:
                target_ids = df_active["id"].tolist()

            if st.button("Tandai LIBUR", type="primary", key="btn_set_libur"):
                set_libur(target_ids, d, notes=notes.strip())
                st.success("LIBUR tersimpan.")

        with col2:
            st.markdown("### Batalkan LIBUR (kembali default MASUK)")
            d2 = st.date_input("Tanggal yang dibatalkan", value=date.today(), key="cancel_date")
            mode2 = st.radio("Untuk siapa dibatalkan?", ["Satu karyawan", "Semua karyawan aktif"], horizontal=True, key="cancel_mode")
            if mode2 == "Satu karyawan":
                emp_id2 = st.selectbox(
                    "Pilih karyawan",
                    options=df_active["id"].tolist(),
                    format_func=lambda x: df_active.loc[df_active["id"] == x, "full_name"].values[0],
                    key="cancel_emp_one"
                )
                target_ids2 = [emp_id2]
            else:
                target_ids2 = df_active["id"].tolist()

            if st.button("Batalkan LIBUR", key="btn_cancel_libur"):
                clear_override(target_ids2, d2)
                st.success("Override LIBUR dihapus. Default kembali MASUK.")

        st.markdown("### Daftar override LIBUR (yang pernah diinput)")
        df_over = query_df("""
            SELECT ao.work_date, e.full_name, e.employee_code, ao.status, ao.notes, ao.created_at
            FROM attendance_overrides ao
            JOIN employees e ON e.id = ao.employee_id
            ORDER BY ao.work_date DESC, e.full_name
        """)
        st.dataframe(df_over, use_container_width=True, hide_index=True)

# ---- TAB 3: Reports
with tab3:
    st.subheader("Rekap & Export CSV")

    df_active = get_active_employees()
    if df_active.empty:
        st.warning("Tidak ada karyawan aktif.")
    else:
        today = date.today()
        colR1, colR2, colR3 = st.columns([1, 1, 2], gap="large")

        with colR1:
            st.markdown("### Rekap bulanan")
            y = st.number_input("Tahun", min_value=2000, max_value=2100, value=today.year, step=1, key="rep_month_year")
            m = st.number_input("Bulan", min_value=1, max_value=12, value=today.month, step=1, key="rep_month_month")
            start_m, end_m = month_range(int(y), int(m))
            st.write(f"Periode: **{start_m} s/d {end_m}**")

            rep_m = build_report(start_m, end_m)
            st.dataframe(rep_m, use_container_width=True, hide_index=True)

            csv_m = rep_m.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV Bulanan", data=csv_m, file_name=f"rekap_{y}-{int(m):02d}.csv", mime="text/csv", key="dl_month")

        with colR2:
            st.markdown("### Rekap tahunan")
            y2 = st.number_input("Tahun (tahunan)", min_value=2000, max_value=2100, value=today.year, step=1, key="rep_year_year")
            start_y, end_y = year_range(int(y2))
            st.write(f"Periode: **{start_y} s/d {end_y}**")

            rep_y = build_report(start_y, end_y)
            st.dataframe(rep_y, use_container_width=True, hide_index=True)

            csv_y = rep_y.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV Tahunan", data=csv_y, file_name=f"rekap_{y2}.csv", mime="text/csv", key="dl_year")

        with colR3:
            st.markdown("### Catatan logika")
            st.write(
                "- Sistem ini **tidak menghitung jam**.\n"
                "- Data yang disimpan hanya **pengecualian LIBUR**.\n"
                "- **MASUK = default** untuk semua tanggal di rentang rekap, kecuali ada override LIBUR.\n"
            )
import sqlite3
from datetime import date, datetime
import pandas as pd
import streamlit as st

APP_TITLE = "Absensi Sederhana (Admin Manual)"
DB_PATH = "absensi.db"

# -----------------------
# DB helpers
# -----------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        employee_code TEXT UNIQUE,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)

    # Only store exceptions from default MASUK
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('LIBUR')),
        notes TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(employee_id, work_date),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()

def query_df(sql, params=None):
    conn = get_conn()
    df = pd.read_sql_query(sql, conn, params=params or [])
    conn.close()
    return df

def execute(sql, params=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit()
    conn.close()

# -----------------------
# Business logic
# -----------------------
def get_active_employees():
    return query_df("""
        SELECT id, full_name, employee_code
        FROM employees
        WHERE is_active = 1
        ORDER BY full_name
    """)

def get_all_employees():
    return query_df("""
        SELECT id, full_name, employee_code, is_active, created_at
        FROM employees
        ORDER BY full_name
    """)

def set_libur(employee_ids, work_date: date, notes=""):
    now = datetime.now().isoformat(timespec="seconds")
    for eid in employee_ids:
        execute("""
            INSERT INTO attendance_overrides(employee_id, work_date, status, notes, created_at)
            VALUES(?, ?, 'LIBUR', ?, ?)
            ON CONFLICT(employee_id, work_date) DO UPDATE SET
                status='LIBUR',
                notes=excluded.notes
        """, [eid, work_date.isoformat(), notes, now])

def clear_override(employee_ids, work_date: date):
    for eid in employee_ids:
        execute("""
            DELETE FROM attendance_overrides
            WHERE employee_id = ? AND work_date = ?
        """, [eid, work_date.isoformat()])

def build_report(start_date: date, end_date: date):
    employees = get_active_employees()
    if employees.empty:
        return pd.DataFrame()

    overrides = query_df("""
        SELECT employee_id, COUNT(*) AS libur_days
        FROM attendance_overrides
        WHERE work_date BETWEEN ? AND ?
        GROUP BY employee_id
    """, [start_date.isoformat(), end_date.isoformat()])

    total_days = (end_date - start_date).days + 1

    rep = employees.merge(overrides, how="left", left_on="id", right_on="employee_id")
    rep["libur_days"] = rep["libur_days"].fillna(0).astype(int)
    rep["total_days"] = total_days
    rep["masuk_days"] = rep["total_days"] - rep["libur_days"]

    rep = rep[["full_name", "employee_code", "total_days", "masuk_days", "libur_days"]]
    rep = rep.sort_values("full_name").reset_index(drop=True)
    return rep

def month_range(year: int, month: int):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - pd.Timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - pd.Timedelta(days=1)
    return start, end.to_pydatetime().date()

def year_range(year: int):
    return date(year, 1, 1), date(year, 12, 31)

# -----------------------
# UI
# -----------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
init_db()

st.title(APP_TITLE)
st.caption("Aturan: default = MASUK. Admin hanya menginput pengecualian: LIBUR. Jika tidak ada input, otomatis dianggap MASUK.")

tab1, tab2, tab3 = st.tabs(["1) Karyawan", "2) Input LIBUR", "3) Rekap & Export"])

# ---- TAB 1: Employees
with tab1:
    st.subheader("Master Karyawan")

    colA, colB = st.columns([1, 2], gap="large")

    with colA:
        st.markdown("### Tambah karyawan")
        full_name = st.text_input("Nama lengkap", placeholder="Contoh: Andi Pratama", key="emp_full_name")
        employee_code = st.text_input("Kode karyawan (opsional, unik)", placeholder="Contoh: EMP-001", key="emp_code")

        if st.button("Tambah", type="primary", key="btn_add_emp"):
            if not full_name.strip():
                st.error("Nama tidak boleh kosong.")
            else:
                try:
                    execute("""
                        INSERT INTO employees(full_name, employee_code, is_active, created_at)
                        VALUES(?, ?, 1, ?)
                    """, [full_name.strip(), employee_code.strip() or None, datetime.now().isoformat(timespec="seconds")])
                    st.success("Karyawan ditambahkan.")
                except sqlite3.IntegrityError as e:
                    st.error(f"Gagal: {e}")

    with colB:
        st.markdown("### Daftar karyawan")
        df_emp = get_all_employees()
        if df_emp.empty:
            st.info("Belum ada karyawan.")
        else:
            show = df_emp.copy()
            show["status"] = show["is_active"].map({1: "Aktif", 0: "Nonaktif"})
            show = show.drop(columns=["is_active"])
            st.dataframe(show, use_container_width=True, hide_index=True)

            st.markdown("### Aktif/Nonaktif")
            ids = df_emp["id"].tolist()
            selected_id = st.selectbox(
                "Pilih karyawan",
                options=ids,
                format_func=lambda x: df_emp.loc[df_emp["id"] == x, "full_name"].values[0],
                key="emp_select_status"
            )
            new_state = st.radio("Status", options=["Aktif", "Nonaktif"], horizontal=True, key="emp_radio_status")
            if st.button("Simpan status", key="btn_save_status"):
                execute("UPDATE employees SET is_active = ? WHERE id = ?", [1 if new_state == "Aktif" else 0, selected_id])
                st.success("Status diperbarui. Refresh halaman jika perlu.")

# ---- TAB 2: Input LIBUR
with tab2:
    st.subheader("Input LIBUR (pengecualian dari default MASUK)")
    df_active = get_active_employees()

    if df_active.empty:
        st.warning("Tambahkan karyawan aktif dulu di tab Karyawan.")
    else:
        col1, col2 = st.columns([1, 1], gap="large")

        with col1:
            st.markdown("### Set LIBUR")
            d = st.date_input("Tanggal", value=date.today(), key="libur_date")
            mode = st.radio("Untuk siapa?", ["Satu karyawan", "Semua karyawan aktif"], horizontal=True, key="libur_mode")
            notes = st.text_input("Catatan (opsional)", placeholder="Contoh: Cuti bersama / Izin pribadi", key="libur_notes")

            if mode == "Satu karyawan":
                emp_id = st.selectbox(
                    "Pilih karyawan",
                    options=df_active["id"].tolist(),
                    format_func=lambda x: df_active.loc[df_active["id"] == x, "full_name"].values[0],
                    key="libur_emp_one"
                )
                target_ids = [emp_id]
            else:
                target_ids = df_active["id"].tolist()

            if st.button("Tandai LIBUR", type="primary", key="btn_set_libur"):
                set_libur(target_ids, d, notes=notes.strip())
                st.success("LIBUR tersimpan.")

        with col2:
            st.markdown("### Batalkan LIBUR (kembali default MASUK)")
            d2 = st.date_input("Tanggal yang dibatalkan", value=date.today(), key="cancel_date")
            mode2 = st.radio("Untuk siapa dibatalkan?", ["Satu karyawan", "Semua karyawan aktif"], horizontal=True, key="cancel_mode")
            if mode2 == "Satu karyawan":
                emp_id2 = st.selectbox(
                    "Pilih karyawan",
                    options=df_active["id"].tolist(),
                    format_func=lambda x: df_active.loc[df_active["id"] == x, "full_name"].values[0],
                    key="cancel_emp_one"
                )
                target_ids2 = [emp_id2]
            else:
                target_ids2 = df_active["id"].tolist()

            if st.button("Batalkan LIBUR", key="btn_cancel_libur"):
                clear_override(target_ids2, d2)
                st.success("Override LIBUR dihapus. Default kembali MASUK.")

        st.markdown("### Daftar override LIBUR (yang pernah diinput)")
        df_over = query_df("""
            SELECT ao.work_date, e.full_name, e.employee_code, ao.status, ao.notes, ao.created_at
            FROM attendance_overrides ao
            JOIN employees e ON e.id = ao.employee_id
            ORDER BY ao.work_date DESC, e.full_name
        """)
        st.dataframe(df_over, use_container_width=True, hide_index=True)

# ---- TAB 3: Reports
with tab3:
    st.subheader("Rekap & Export CSV")

    df_active = get_active_employees()
    if df_active.empty:
        st.warning("Tidak ada karyawan aktif.")
    else:
        today = date.today()
        colR1, colR2, colR3 = st.columns([1, 1, 2], gap="large")

        with colR1:
            st.markdown("### Rekap bulanan")
            y = st.number_input("Tahun", min_value=2000, max_value=2100, value=today.year, step=1, key="rep_month_year")
            m = st.number_input("Bulan", min_value=1, max_value=12, value=today.month, step=1, key="rep_month_month")
            start_m, end_m = month_range(int(y), int(m))
            st.write(f"Periode: **{start_m} s/d {end_m}**")

            rep_m = build_report(start_m, end_m)
            st.dataframe(rep_m, use_container_width=True, hide_index=True)

            csv_m = rep_m.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV Bulanan", data=csv_m, file_name=f"rekap_{y}-{int(m):02d}.csv", mime="text/csv", key="dl_month")

        with colR2:
            st.markdown("### Rekap tahunan")
            y2 = st.number_input("Tahun (tahunan)", min_value=2000, max_value=2100, value=today.year, step=1, key="rep_year_year")
            start_y, end_y = year_range(int(y2))
            st.write(f"Periode: **{start_y} s/d {end_y}**")

            rep_y = build_report(start_y, end_y)
            st.dataframe(rep_y, use_container_width=True, hide_index=True)

            csv_y = rep_y.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV Tahunan", data=csv_y, file_name=f"rekap_{y2}.csv", mime="text/csv", key="dl_year")

        with colR3:
            st.markdown("### Catatan logika")
            st.write(
                "- Sistem ini **tidak menghitung jam**.\n"
                "- Data yang disimpan hanya **pengecualian LIBUR**.\n"
                "- **MASUK = default** untuk semua tanggal di rentang rekap, kecuali ada override LIBUR.\n"
            )
