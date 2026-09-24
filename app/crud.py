import os
import threading
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import time

# 🔒 قفل لتفادي التداخل بين الطلبات
LOCK = threading.Lock()

# ===== إعداد Google Sheets =====
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "MedBot Files")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

if not SERVICE_ACCOUNT_JSON:
    raise ValueError("❌ متغير البيئة GOOGLE_SERVICE_ACCOUNT_JSON غير موجود!")

creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
client = gspread.authorize(credentials)

# ===== كاش داخلي =====
_cache = {}
CACHE_TTL = 60  # ثواني

def _get_cache(key):
    if key in _cache and (time.time() - _cache[key]['time'] < CACHE_TTL):
        return _cache[key]['value']
    return None

def _set_cache(key, value):
    _cache[key] = {'value': value, 'time': time.time()}

# ===== تهيئة الورقة =====
def init_db():
    with LOCK:
        try:
            try:
                spreadsheet = client.open(GOOGLE_SHEET_NAME)
            except gspread.SpreadsheetNotFound:
                spreadsheet = client.create(GOOGLE_SHEET_NAME)

            sheet_titles = [s.title for s in spreadsheet.worksheets()]

            # materials — الهيكل الجديد: semester, course, section, doctor, type, file_id, created_at
            expected_header = ["semester", "course", "section", "doctor", "type", "file_id", "created_at"]
            if "materials" not in sheet_titles:
                spreadsheet.add_worksheet(title="materials", rows=5000, cols=7)
                sheet = spreadsheet.worksheet("materials")
                sheet.append_row(expected_header)
            else:
                sheet = spreadsheet.worksheet("materials")
                header = sheet.row_values(1)
                if header[:len(expected_header)] != expected_header:
                    # إذا كان الهيكل القديم (بدون section/doctor) نضيف الأعمدة الجديدة
                    old_header = ["semester", "course", "type", "file_id", "created_at"]
                    if header[:len(old_header)] == old_header:
                        # ترقية: إدراج عمودين جديدين بعد course
                        # نحتفظ بالبيانات القديمة ونعيد بناء الورقة
                        all_rows = sheet.get_all_values()
                        sheet.clear()
                        sheet.append_row(expected_header)
                        for row in all_rows[1:]:  # تخطي الهيدر القديم
                            if len(row) >= 5:
                                # semester, course, type, file_id, created_at
                                new_row = [row[0], row[1], "", "", row[2], row[3], row[4]]
                                sheet.append_row(new_row)
                        print("✅ تم ترقية هيكل materials بنجاح")
                    else:
                        try:
                            sheet.delete_rows(1)
                        except Exception:
                            pass
                        sheet.insert_row(expected_header, 1)

            # waiting_files
            if "waiting_files" not in sheet_titles:
                spreadsheet.add_worksheet(title="waiting_files", rows=1000, cols=4)
                sheet2 = spreadsheet.worksheet("waiting_files")
                sheet2.append_row(["chat_id", "file_id", "type", "semester"])
            else:
                sheet2 = spreadsheet.worksheet("waiting_files")
                header2 = sheet2.row_values(1)
                if header2[:4] != ["chat_id", "file_id", "type", "semester"]:
                    try:
                        sheet2.delete_rows(1)
                    except Exception:
                        pass
                    sheet2.insert_row(["chat_id", "file_id", "type", "semester"], 1)

            print("✅ Google Sheet جاهز للاستخدام")

        except Exception as e:
            print(f"❌ خطأ أثناء التهيئة: {e}")

# ========== مواد دائمة ==========
def add_material(semester, course, type_, file_id, section="", doctor=""):
    """
    إضافة مادة للنظام
    semester : رقم الفصل
    course   : اسم المقرر
    section  : القسم (Anatomy, Physiology, ...)  — اختياري
    doctor   : اسم الدكتور — اختياري
    type_    : نوع الملف (pdf, video, recording, reference)
    file_id  : معرف الملف في تيليجرام
    """
    with LOCK:
        try:
            sheet = client.open(GOOGLE_SHEET_NAME).worksheet("materials")
            created_at = datetime.utcnow().isoformat()
            sheet.append_row([semester, course, section or "", doctor or "",
                               type_, file_id, created_at])
            # مسح الكاش المرتبط
            _cache.pop("materials_all", None)
            _cache.pop(f"mat_{semester}_{course}_{section}_{doctor}_{type_}", None)
        except Exception as e:
            print(f"❌ خطأ أثناء إضافة المادة: {e}")

def get_materials(semester, course, type_, section="", doctor="", use_cache=False):
    """
    جلب الملفات بناءً على الفلاتر المحددة.
    إذا كان section أو doctor فارغاً يُهمل في الفلتر
    (يُرجع كل ملفات المقرر بغض النظر عن القسم/الدكتور)
    """
    key = f"mat_{semester}_{course}_{section}_{doctor}_{type_}"

    if use_cache:
        cached = _get_cache(key)
        if cached is not None:
            return cached

    rows = _fetch_materials_from_sheet()
    results = []
    for row in rows:
        if str(row.get("semester")) != str(semester):
            continue
        if str(row.get("course")) != str(course):
            continue
        if str(row.get("type")) != str(type_):
            continue
        # فلتر القسم: إذا طُلب قسم محدد نطابقه، وإلا نقبل الكل
        if section and str(row.get("section", "")) != str(section):
            continue
        # فلتر الدكتور: نفس المنطق
        if doctor and str(row.get("doctor", "")) != str(doctor):
            continue
        results.append({
            "semester":   row.get("semester"),
            "course":     row.get("course"),
            "section":    row.get("section", ""),
            "doctor":     row.get("doctor", ""),
            "type":       row.get("type"),
            "file_id":    row.get("file_id"),
            "created_at": row.get("created_at"),
        })

    if use_cache:
        _set_cache(key, results)

    return results

def _fetch_materials_from_sheet():
    """جلب جميع المواد من الورقة"""
    with LOCK:
        try:
            sheet = client.open(GOOGLE_SHEET_NAME).worksheet("materials")
            return sheet.get_all_records()
        except Exception as e:
            print(f"❌ خطأ أثناء جلب المواد: {e}")
            return []

# ======= الملفات المؤقتة (لم تتغير) =======
def set_waiting_file(chat_id, flag):
    with LOCK:
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("waiting_files")
        all_rows = sheet.get_all_records()
        if not flag:
            new_rows = [r for r in all_rows if str(r.get("chat_id")) != str(chat_id)]
            sheet.clear()
            sheet.append_row(["chat_id", "file_id", "type", "semester"])
            for row in new_rows:
                sheet.append_row([row.get("chat_id"), row.get("file_id"),
                                   row.get("type"), row.get("semester") or ""])
        else:
            for r in all_rows:
                if str(r.get("chat_id")) == str(chat_id):
                    return
            sheet.append_row([chat_id, "", "", ""])
        _cache.pop(f"waiting_file_{chat_id}", None)
        _cache.pop(f"waiting_data_{chat_id}", None)

def set_waiting_file_fileid(chat_id, file_id, type_, semester=None):
    with LOCK:
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("waiting_files")
        all_rows = sheet.get_all_records()
        for i, row in enumerate(all_rows, start=2):
            if str(row.get("chat_id")) == str(chat_id):
                sheet.update(f"A{i}:D{i}", [[chat_id, file_id, type_, semester or ""]])
                _cache.pop(f"waiting_data_{chat_id}", None)
                return
        sheet.append_row([chat_id, file_id, type_, semester or ""])
        _cache.pop(f"waiting_data_{chat_id}", None)

def set_waiting_file_semester(chat_id, semester):
    with LOCK:
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("waiting_files")
        all_rows = sheet.get_all_records()
        for i, row in enumerate(all_rows, start=2):
            if str(row.get("chat_id")) == str(chat_id):
                sheet.update(f"D{i}:D{i}", [[semester]])
                _cache.pop(f"waiting_data_{chat_id}", None)
                return

def is_waiting_file(chat_id, use_cache=False):
    key = f"waiting_file_{chat_id}"
    if use_cache:
        cached = _get_cache(key)
        if cached is not None:
            return cached
    with LOCK:
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("waiting_files")
        rows = sheet.get_all_records()
        exists = any(str(r.get("chat_id")) == str(chat_id) for r in rows)
    if use_cache:
        _set_cache(key, exists)
    return exists

def get_waiting_file(chat_id, use_cache=False):
    key = f"waiting_data_{chat_id}"
    if use_cache:
        cached = _get_cache(key)
        if cached:
            return cached
    with LOCK:
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("waiting_files")
        rows = sheet.get_all_records()
        for r in rows:
            if str(r.get("chat_id")) == str(chat_id):
                result = {"file_id": r.get("file_id"), "type": r.get("type"),
                          "semester": r.get("semester")}
                if use_cache:
                    _set_cache(key, result)
                return result
    return None
