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

            # admins — المشرفون المضافون من داخل البوت
            admins_header = ["username", "added_by", "created_at"]
            if "admins" not in sheet_titles:
                spreadsheet.add_worksheet(title="admins", rows=500, cols=3)
                spreadsheet.worksheet("admins").append_row(admins_header)
            else:
                sheet3 = spreadsheet.worksheet("admins")
                if not sheet3.row_values(1):
                    sheet3.insert_row(admins_header, 1)

            print("✅ Google Sheet جاهز للاستخدام")

        except Exception as e:
            print(f"❌ خطأ أثناء التهيئة: {e}")

# ========== مواد دائمة ==========
def add_material(semester, course, type_, file_id, section=""):
    """
    إضافة مادة للنظام
    semester : رقم الفصل
    course   : اسم المقرر
    section  : القسم (Anatomy, Physiology, ...)  — اختياري
    type_    : نوع الملف (pdf, video, recording, reference)
    file_id  : معرف الملف في تيليجرام
    """
    with LOCK:
        try:
            sheet = client.open(GOOGLE_SHEET_NAME).worksheet("materials")
            created_at = datetime.utcnow().isoformat()
            # عمود doctor أُبقي فارغاً للحفاظ على هيكل الورقة الحالي
            sheet.append_row([semester, course, section or "", "",
                               type_, file_id, created_at])
            # مسح الكاش المرتبط
            _cache.pop("materials_all", None)
            _cache.pop(f"mat_{semester}_{course}_{section}_{type_}", None)
        except Exception as e:
            print(f"❌ خطأ أثناء إضافة المادة: {e}")

def get_materials(semester, course, type_, section="", use_cache=False):
    """
    جلب الملفات بناءً على الفلاتر المحددة.
    إذا كان section فارغاً يُهمل في الفلتر
    (يُرجع كل ملفات المقرر بغض النظر عن القسم)
    """
    key = f"mat_{semester}_{course}_{section}_{type_}"

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
        results.append({
            "semester":   row.get("semester"),
            "course":     row.get("course"),
            "section":    row.get("section", ""),
            "type":       row.get("type"),
            "file_id":    row.get("file_id"),
            "created_at": row.get("created_at"),
        })

    if use_cache:
        _set_cache(key, results)

    return results

def delete_material(semester, course, type_, file_id, section=""):
    """
    حذف سطر واحد مطابق من ورقة materials.
    يرجع: deleted | not_found | error
    """
    with LOCK:
        try:
            sheet = client.open(GOOGLE_SHEET_NAME).worksheet("materials")
            values = sheet.get_all_values()
            if not values:
                return "not_found"
            header = values[0]
            idx = {n: header.index(n) for n in ("semester", "course", "section", "type", "file_id")}

            def cell(row, name):
                j = idx[name]
                return str(row[j]).strip() if j < len(row) else ""

            target_row = None
            for i, row in enumerate(values[1:], start=2):
                if (cell(row, "semester") == str(semester).strip()
                        and cell(row, "course") == str(course).strip()
                        and cell(row, "section") == str(section or "").strip()
                        and cell(row, "type") == str(type_).strip()
                        and cell(row, "file_id") == str(file_id).strip()):
                    target_row = i
                    break
            if target_row is None:
                return "not_found"
            sheet.delete_rows(target_row)
        except Exception as e:
            print(f"❌ خطأ أثناء حذف المادة: {e}")
            return "error"
    # مسح الكاش حتى لا يستمر إرسال الملف المحذوف للطلاب
    for k in [k for k in _cache if k.startswith("mat_")]:
        _cache.pop(k, None)
    _cache.pop("materials_all", None)
    return "deleted"

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

# ========== المشرفون (يُضافون ويُحذفون من داخل البوت) ==========
# المشرفون الرئيسيون يأتون من متغير البيئة ADMIN_USERNAMES (في main.py)
# أما هنا فنخزّن المشرفين العاديين (رفع المواد فقط)
_admins_cache = {"names": set(), "time": 0}
ADMINS_CACHE_TTL = 60  # ثواني

def _norm_username(username):
    return str(username or "").strip().lstrip("@").lower()

def _fetch_admins_from_sheet():
    with LOCK:
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("admins")
        return sheet.get_all_records()

def list_admins():
    """قائمة المشرفين المضافين (قراءة مباشرة من الورقة)"""
    try:
        rows = _fetch_admins_from_sheet()
    except Exception as e:
        print(f"❌ خطأ أثناء جلب المشرفين: {e}")
        return []
    result = []
    for r in rows:
        name = _norm_username(r.get("username"))
        if name:
            result.append({"username": name, "added_by": r.get("added_by", ""),
                           "created_at": r.get("created_at", "")})
    _admins_cache["names"] = {a["username"] for a in result}
    _admins_cache["time"] = time.time()
    return result

def get_admin_usernames():
    """مجموعة معرفات المشرفين المضافين (مع كاش قصير لتجنب ضغط Google Sheets)"""
    if time.time() - _admins_cache["time"] < ADMINS_CACHE_TTL:
        return _admins_cache["names"]
    try:
        rows = _fetch_admins_from_sheet()
        _admins_cache["names"] = {_norm_username(r.get("username")) for r in rows
                                  if _norm_username(r.get("username"))}
    except Exception as e:
        print(f"❌ خطأ أثناء تحديث المشرفين (نستخدم النسخة السابقة): {e}")
    _admins_cache["time"] = time.time()
    return _admins_cache["names"]

def add_admin(username, added_by=""):
    """يرجع: added | exists | error"""
    username = _norm_username(username)
    with LOCK:
        try:
            sheet = client.open(GOOGLE_SHEET_NAME).worksheet("admins")
            existing = {_norm_username(v) for v in sheet.col_values(1)[1:]}
            if username in existing:
                return "exists"
            sheet.append_row([username, _norm_username(added_by), datetime.utcnow().isoformat()])
        except Exception as e:
            print(f"❌ خطأ أثناء إضافة مشرف: {e}")
            return "error"
    _admins_cache["names"] = existing | {username}
    _admins_cache["time"] = time.time()
    return "added"

def remove_admin(username):
    """يرجع: removed | not_found | error"""
    username = _norm_username(username)
    with LOCK:
        try:
            sheet = client.open(GOOGLE_SHEET_NAME).worksheet("admins")
            values = sheet.col_values(1)
            row_index = None
            for i, v in enumerate(values[1:], start=2):
                if _norm_username(v) == username:
                    row_index = i
                    break
            if row_index is None:
                return "not_found"
            sheet.delete_rows(row_index)
        except Exception as e:
            print(f"❌ خطأ أثناء حذف مشرف: {e}")
            return "error"
    _admins_cache["names"] = {_norm_username(v) for v in values[1:]
                              if _norm_username(v)} - {username}
    _admins_cache["time"] = time.time()
    return "removed"
