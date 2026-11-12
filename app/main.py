import os
import re
import time
import threading
import requests
import logging
from fastapi import FastAPI, Header, HTTPException
from app import crud

# ========= Logging مفصل =========
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ========= الإعدادات الأساسية =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", None)

DEVELOPER_USERNAME = "@Mgdad_ali"

_raw_admins = os.getenv("ADMIN_USERNAMES", "Mgdad_ali")
ADMIN_USERNAMES = {u.strip().lstrip("@") for u in _raw_admins.split(",") if u.strip()}
# المشرفون الرئيسيون (من متغير البيئة): يرفعون المواد + يديرون المشرفين الآخرين
SUPER_ADMINS = {u.lower() for u in ADMIN_USERNAMES}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")

# قناة الأرشفة (اختياري): إذا كان المتغير فارغاً تبقى الميزة معطّلة والبوت يعمل كما كان
ARCHIVE_CHANNEL_ID = os.getenv("ARCHIVE_CHANNEL_ID", "").strip()
# صاحب صلاحية زر «أرشفة المحتوى» (معرّف واحد فقط) — يُضبط من متغير البيئة
ARCHIVE_OWNER = os.getenv("ARCHIVE_OWNER_USERNAME", "").strip().lstrip("@").lower()
ARCHIVE_DELAY = 3.2   # ثواني بين كل ملفين (حد تيليجرام ~20 رسالة/دقيقة للقناة)
ARCHIVE_LOCK = threading.Lock()
ARCHIVE_JOB = {"running": False, "stop": False, "done": 0, "total": 0,
               "failed": [], "next": 1}

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Med Faculty Bot")

@app.on_event("startup")
async def startup():
    crud.init_db()
    logger.info("✅ Database initialized successfully.")

UPLOAD_SESSION = {}
USER_STATE = {}
MANAGE_STATE = {}   # chat_id -> "add" | "remove" | "archive_from" (بانتظار إدخال من المشرف)

# =========================================================
# هيكل المحتوى التفصيلي
# =========================================================
COURSE_STRUCTURE = {

    # ======= الفصل الثاني =======
    ("2", "Embryology"): {
        "sections": ["Internal", "External"]
    },
    ("2", "Nutrition"):    {"sections": []},
    ("2", "Genetics"):     {"sections": []},
    ("2", "Computer"):     {"sections": []},
    ("2", "Statistics"):   {"sections": []},
    ("2", "Ethics"):       {"sections": []},
    ("2", "English"):      {"sections": []},
    ("2", "Arabic"):       {"sections": []},
    ("2", "Islamyia"):     {"sections": []},

    # ======= الفصل الثالث =======
    ("3", "Pathology"): {
        "sections": ["General Pathology", "Bacteriology", "Virology", "Mycology", "Microbiology"]
    },
    ("3", "Musculoskeletal System"): {
        "sections": ["Physiology", "Pathology", "Anatomy", "DR"]
    },
    ("3", "Community"):        {"sections": []},
    ("3", "Sudanese Studies"): {"sections": []},

    # ======= الفصل الرابع =======
    ("4", "Hematology"): {
        "sections": ["Physiology", "Pathology"]
    },
    ("4", "Cardiopulmonary 1"): {
        "sections": ["Anatomy", "DR", "Pathology", "Physiology"]
    },
    ("4", "Primary Health Care 1"): {"sections": []},
    ("4", "Basic Skills"):           {"sections": []},
    ("4", "The Rural"):              {"sections": []},

    # ======= الفصل الخامس =======
    ("5", "Cardiopulmonary 2"): {
        "sections": ["Anatomy + Embryology", "Pathology", "Physiology",
                     "Clinical", "Examination + History"]
    },
    ("5", "Endocrinology"): {
        "sections": ["Physiology", "Anatomy + Embryology + Histology",
                     "Clinical", "Biochemistry", "Pathology"]
    },
    ("5", "Pharmacology"): {
        "sections": ["General", "Autonomic"]
    },
    ("5", "Primary Health Care 2"): {"sections": []},

    # ======= الفصل السادس =======
    ("6", "Gastrointestinal Tract 1"): {
        "sections": ["Anatomy + Embryology + Histology", "DR",
                     "Physiology", "Pathology", "Clinical", "Microbiology"]
    },
    ("6", "Gastrointestinal Tract 2"): {
        "sections": ["Anatomy + Embryology + Histology", "Pathology",
                     "Physiology", "Clinical", "Examination + History"]
    },
    ("6", "Family Medicine"):  {"sections": []},
    ("6", "Endemic Diseases"): {"sections": []},
    ("6", "The Rural 2"):      {"sections": []},

    # ======= الفصل السابع =======
    ("7", "Genito-urinary System"): {
        "sections": ["Anatomy", "Physiology", "Pathology",
                     "Clinical", "Examination + History"]
    },
    ("7", "Central Nervous System"): {
        "sections": ["Anatomy", "Physiology", "Pathology",
                     "Clinical", "Examination + History"]
    },
    ("7", "Forensic Medicine"): {"sections": []},
}

# =========================================================
# بناء مجموعات الكشف
# =========================================================
ALL_SECTIONS = set()
for v in COURSE_STRUCTURE.values():
    for s in v.get("sections", []):
        ALL_SECTIONS.add(s)

# =========================================================
# دوال مساعدة
# =========================================================
def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        logger.info(f"Send message status: {r.status_code}, response: {r.text}")
    except Exception as e:
        logger.exception(f"Failed to send message: {e}")

def send_file(chat_id, file_id, content_type="pdf", caption=None):
    extra = {"caption": caption} if caption else {}
    try:
        if content_type == "video":
            r = requests.post(f"{TELEGRAM_API}/sendVideo",
                              json={"chat_id": chat_id, "video": file_id, **extra})
        elif content_type == "recording":
            r = requests.post(f"{TELEGRAM_API}/sendAudio",
                              json={"chat_id": chat_id, "audio": file_id, **extra})
        else:
            r = requests.post(f"{TELEGRAM_API}/sendDocument",
                              json={"chat_id": chat_id, "document": file_id, **extra})
        logger.info(f"Send file status: {r.status_code}, response: {r.text}")
    except Exception as e:
        logger.exception(f"Failed to send file: {e}")

def is_super_admin(user):
    """مشرف رئيسي: معرفه في متغير البيئة — يستطيع إضافة/حذف مشرفين"""
    return (user.get("username") or "").lower() in SUPER_ADMINS

def is_archive_owner(user):
    """صاحب صلاحية الأرشفة اليدوية: المعرّف الوحيد في ARCHIVE_OWNER_USERNAME"""
    uname = (user.get("username") or "").lower()
    return bool(ARCHIVE_OWNER) and uname == ARCHIVE_OWNER

def is_admin(user):
    """أي مشرف (رئيسي أو مضاف من داخل البوت) — يستطيع رفع المواد"""
    uname = (user.get("username") or "").lower()
    if not uname:
        return False
    return uname in SUPER_ADMINS or uname in crud.get_admin_usernames()

def ctype_label(ctype):
    return {"pdf": "PDF 📄", "video": "فيديو 🎥",
            "recording": "تسجيلات 🎙️", "reference": "مرجع 📚"}.get(ctype, ctype)

# =========================================================
# لوحات المفاتيح
# =========================================================
def get_main_keyboard(admin=False, manager=False):
    buttons = [[{"text": "ابدأ 🎓"}], [{"text": "تواصل مع المطور 👨‍💻"}]]
    if admin:
        buttons.append([{"text": "رفع ملف جديد 📤"}])
    if manager:
        buttons.append([{"text": "ادارة ⚙️"}])
    return {"keyboard": buttons, "resize_keyboard": True}

def get_manage_keyboard(archive=False):
    rows = [
        [{"text": "➕ إضافة مشرف"}, {"text": "➖ حذف مشرف"}],
        [{"text": "🗑 حذف محتوى"}],
    ]
    if archive:
        rows.append([{"text": "📦 أرشفة المحتوى"}])
    rows += [
        [{"text": "📋 قائمة المشرفين"}],
        [{"text": "🏠 القائمة الرئيسية"}]
    ]
    return {"keyboard": rows, "resize_keyboard": True}

def get_manage_back_keyboard():
    return {
        "keyboard": [
            [{"text": "↩️ رجوع للإدارة"}],
            [{"text": "🏠 القائمة الرئيسية"}]
        ],
        "resize_keyboard": True
    }

def get_remove_admin_keyboard(names):
    rows = []
    for i in range(0, len(names), 2):
        row = [{"text": f"@{names[i]}"}]
        if i + 1 < len(names):
            row.append({"text": f"@{names[i + 1]}"})
        rows.append(row)
    rows.append([{"text": "↩️ رجوع للإدارة"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": rows, "resize_keyboard": True}

ARCHIVE_BTN = "📦 أرشفة المحتوى"
ARCHIVE_FROM_START_BTN = "▶️ بدء الأرشفة من البداية"
ARCHIVE_RESUME_BTN = "▶️ متابعة الأرشفة"
ARCHIVE_CUSTOM_BTN = "🔢 البدء من رقم محدد"
ARCHIVE_STOP_BTN = "⏹ إيقاف الأرشفة"

def get_archive_keyboard(can_resume):
    rows = [[{"text": ARCHIVE_FROM_START_BTN}]]
    if can_resume:
        rows.append([{"text": ARCHIVE_RESUME_BTN}])
    rows.append([{"text": ARCHIVE_CUSTOM_BTN}])
    rows.append([{"text": "↩️ رجوع للإدارة"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": rows, "resize_keyboard": True}

def get_archive_running_keyboard():
    return {
        "keyboard": [
            [{"text": ARCHIVE_STOP_BTN}],
            [{"text": ARCHIVE_BTN}],
            [{"text": "↩️ رجوع للإدارة"}, {"text": "🏠 القائمة الرئيسية"}]
        ],
        "resize_keyboard": True
    }

def archive_caption(semester, course, section, ctype):
    return f"semester={semester} | course={course} | section={section or '-'} | type={ctype}"

def archive_send(file_id, ctype, caption):
    """
    ينسخ ملفاً إلى قناة الأرشفة باستخدام file_id (بدون تحميل أو حد حجم).
    يرجع (ok, error_text, fatal) — fatal=True يعني مشكلة في القناة نفسها (لا فائدة من المتابعة).
    """
    if ctype == "video":
        method, key = "sendVideo", "video"
    elif ctype == "recording":
        method, key = "sendAudio", "audio"
    else:
        method, key = "sendDocument", "document"

    last_err = ""
    for _ in range(4):
        try:
            r = requests.post(f"{TELEGRAM_API}/{method}",
                              json={"chat_id": ARCHIVE_CHANNEL_ID, key: file_id, "caption": caption},
                              timeout=60)
            data = r.json()
        except Exception as e:
            last_err = str(e)
            time.sleep(2)
            continue

        if data.get("ok"):
            return True, "", False

        desc = str(data.get("description", ""))
        if r.status_code == 429:
            wait = int(data.get("parameters", {}).get("retry_after", 5))
            logger.warning(f"[ARCHIVE] rate limited, waiting {wait}s")
            time.sleep(wait + 1)
            continue

        low = desc.lower()
        fatal = any(k in low for k in ("chat not found", "not enough rights", "not a member",
                                       "have no rights", "forbidden", "kicked", "bot was blocked"))
        if not fatal and method != "sendDocument":
            # احتياط: بعض الملفات تُخزَّن كمستند فنجرب إرسالها كمستند
            method, key = "sendDocument", "document"
            last_err = desc
            continue
        return False, desc, fatal

    return False, last_err or "failed after retries", False

def archive_new_files(chat_id, items):
    """
    أرشفة الملفات الجديدة تلقائياً بعد الرفع (في خيط منفصل ولا تؤثر على الرفع).
    items: قائمة (semester, course, section, ctype, file_id)
    """
    if not ARCHIVE_CHANNEL_ID or not items:
        return

    def _run():
        ok_count, failed = 0, 0
        for (sem, course, section, ctype, fid) in items:
            try:
                ok, err, fatal = archive_send(fid, ctype, archive_caption(sem, course, section, ctype))
            except Exception as e:
                ok, err, fatal = False, str(e), False
            if ok:
                ok_count += 1
            else:
                failed += 1
                logger.error(f"[ARCHIVE] new file failed: {err}")
                if fatal:
                    break
            time.sleep(ARCHIVE_DELAY)
        if failed:
            send_message(chat_id,
                f"⚠️ تعذّر نسخ {failed} ملف إلى قناة الأرشفة.\n"
                f"تأكد أن البوت مشرف في القناة بصلاحية نشر الرسائل. "
                f"(الملفات محفوظة في البوت بشكل طبيعي)")
        else:
            send_message(chat_id, f"📦 تم نسخ {ok_count} ملف إلى قناة الأرشفة.")

    threading.Thread(target=_run, daemon=True).start()

def archive_status_text():
    job = ARCHIVE_JOB
    return (f"📦 الأرشفة قيد التشغيل\n"
            f"تمت معالجة: {job['done']} من {job['total']}\n"
            f"فشل: {len(job['failed'])}")

def archive_all_job(admin_chat_id, mats, start_index):
    """نسخ المحتوى الحالي إلى القناة بالترتيب (خيط منفصل، بطيء عمداً، قابل للإيقاف والمتابعة)"""
    job = ARCHIVE_JOB
    total = len(mats)
    ok_count = 0
    aborted = None
    try:
        for i in range(start_index, total + 1):
            if job["stop"]:
                break
            m = mats[i - 1]
            ctype = m.get("type")
            try:
                ok, err, fatal = archive_send(m.get("file_id"), ctype,
                                              archive_caption(m.get("semester"), m.get("course"),
                                                              m.get("section"), ctype))
            except Exception as e:
                ok, err, fatal = False, str(e), False

            job["done"] = i
            job["next"] = i + 1
            if ok:
                ok_count += 1
            else:
                job["failed"].append((i, err[:60]))
                logger.error(f"[ARCHIVE] #{i} failed: {err}")
                if fatal:
                    aborted = err
                    break

            if i % 25 == 0:
                send_message(admin_chat_id, f"📦 تقدّم الأرشفة: {i} من {total} • فشل: {len(job['failed'])}")
            time.sleep(ARCHIVE_DELAY)
    except Exception as e:
        logger.exception("[ARCHIVE] job crashed")
        aborted = str(e)
    finally:
        job["running"] = False
        job["stop"] = False

    failed = job["failed"]
    lines = []
    if aborted:
        lines.append(f"❌ توقفت الأرشفة: {aborted}")
        lines.append("تأكد أن البوت مشرف في القناة وأن ARCHIVE_CHANNEL_ID صحيح.")
    elif job["next"] <= total:
        lines.append("⏹ تم إيقاف الأرشفة.")
    else:
        lines.append("✅ انتهت الأرشفة.")
    lines.append(f"تم نسخ: {ok_count} • فشل: {len(failed)} • آخر ملف تمت معالجته: #{job['done']} من {total}")
    if job["next"] <= total:
        lines.append(f"للمتابعة: زر «{ARCHIVE_RESUME_BTN}» (أو ابدأ من رقم {job['next']} إن أُعيد تشغيل البوت).")
    if failed:
        lines.append("ملفات فشلت (رقم: السبب):")
        lines += [f"#{n}: {why}" for n, why in failed[:15]]
        if len(failed) > 15:
            lines.append(f"... و{len(failed) - 15} أخرى")
    send_message(admin_chat_id, "\n".join(lines), reply_markup=get_manage_keyboard(True))

def begin_archive(chat_id, start):
    """التحقق ثم تشغيل أرشفة المحتوى الحالي من الملف رقم start"""
    if not ARCHIVE_CHANNEL_ID:
        send_message(chat_id, "⚠️ قناة الأرشفة غير مضبوطة (ARCHIVE_CHANNEL_ID).",
                     reply_markup=get_manage_keyboard(True))
        return
    try:
        mats = crud.get_all_materials()
    except Exception:
        logger.exception("[ARCHIVE] failed reading materials")
        send_message(chat_id, "❌ تعذّر قراءة الملفات من الشيت. حاول لاحقاً.",
                     reply_markup=get_manage_keyboard(True))
        return
    total = len(mats)
    if total == 0:
        send_message(chat_id, "ℹ️ لا توجد ملفات مسجلة للأرشفة.", reply_markup=get_manage_keyboard(True))
        return
    if start < 1 or start > total:
        send_message(chat_id, f"⚠️ رقم غير صالح. اختر من 1 إلى {total}.",
                     reply_markup=get_manage_keyboard(True))
        return
    with ARCHIVE_LOCK:
        if ARCHIVE_JOB["running"]:
            send_message(chat_id, archive_status_text(), reply_markup=get_archive_running_keyboard())
            return
        ARCHIVE_JOB.update(running=True, stop=False, done=start - 1, total=total,
                           failed=[], next=start)
    threading.Thread(target=archive_all_job, args=(chat_id, mats, start), daemon=True).start()
    minutes = max(1, int((total - start + 1) * ARCHIVE_DELAY / 60))
    send_message(chat_id,
        f"📦 بدأت الأرشفة من الملف #{start} من أصل {total}.\n"
        f"⏱ المدة التقريبية: {minutes} دقيقة. سأرسل لك تقدماً كل 25 ملفاً، "
        f"ويمكنك إيقافها في أي وقت.",
        reply_markup=get_archive_running_keyboard())

DELETE_BTN = "🗑 حذف #"
DELETE_CONFIRM_BTN = "✅ تأكيد حذف #"
DELETE_CANCEL_BTN = "❌ إلغاء الحذف"
DELETE_CHANGE_TYPE_BTN = "🗂 تغيير النوع"
DELETE_MAX_ITEMS = 90   # حد أزرار لوحة المفاتيح في تيليجرام

def get_delete_keyboard(count):
    rows, row = [], []
    for i in range(1, count + 1):
        row.append({"text": f"{DELETE_BTN}{i}"})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": DELETE_CHANGE_TYPE_BTN}])
    rows.append([{"text": "↩️ رجوع للإدارة"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": rows, "resize_keyboard": True}

def get_delete_confirm_keyboard(index):
    return {
        "keyboard": [
            [{"text": f"{DELETE_CONFIRM_BTN}{index}"}],
            [{"text": DELETE_CANCEL_BTN}]
        ],
        "resize_keyboard": True
    }

def show_delete_list(chat_id, session):
    """عرض ملفات النوع المحدد مرقّمة مع أزرار الحذف (للمشرفين الرئيسيين فقط)"""
    semester = session.get("semester")
    course   = session.get("course")
    section  = session.get("section") or ""
    ctype    = session.get("type")

    mats = crud.get_materials(semester, course, ctype, section=section)
    session.pop("confirm_idx", None)

    if not mats:
        session["delete_list"] = []
        send_message(chat_id,
            f"🚧 لا توجد ملفات في هذا القسم.\n"
            f"المقرر: {course} | القسم: {section or '—'} | النوع: {ctype_label(ctype)}\n\n"
            f"يمكنك اختيار نوع آخر:",
            reply_markup=get_types_keyboard(short_label(section or course)))
        return

    shown = mats[:DELETE_MAX_ITEMS]
    session["delete_list"] = shown
    note = f" (عُرض أول {DELETE_MAX_ITEMS} فقط)" if len(mats) > DELETE_MAX_ITEMS else ""
    send_message(chat_id,
        f"🗑 حذف محتوى\n"
        f"📖 المقرر: {course} | 📂 القسم: {section or '—'} | 🗂 {ctype_label(ctype)}\n"
        f"عدد الملفات: {len(mats)}{note}")
    for i, m in enumerate(shown, start=1):
        created = str(m.get("created_at") or "")[:10]
        caption = f"#{i}" + (f" • {created}" if created else "")
        send_file(chat_id, m.get("file_id"), content_type=ctype, caption=caption)
    send_message(chat_id, "اختر رقم الملف المراد حذفه:",
                 reply_markup=get_delete_keyboard(len(shown)))

def get_semesters_keyboard():
    return {
        "keyboard": [
            [{"text": "الفصل الأول "}, {"text": "الفصل الثاني "}],
            [{"text": "الفصل الثالث "}, {"text": "الفصل الرابع "}],
            [{"text": "الفصل الخامس "}, {"text": "الفصل السادس "}],
            [{"text": "الفصل السابع "}, {"text": "الفصل الثامن "}],
            [{"text": "الفصل التاسع "}, {"text": "الفصل العاشر "}],
            [{"text": "🏠 القائمة الرئيسية"}]
        ],
        "resize_keyboard": True
    }

def get_courses_keyboard(semester):
    courses_map = {
        "1": [
            [{"text": "Introduction"}, {"text": "Biochemistry 1"}],
            [{"text": "Parasitology"}, {"text": "Histology"}],
            [{"text": "Physiology"}, {"text": "Medical Physics"}],
            [{"text": "English"}, {"text": "Arabic"}],
            [{"text": "Islamyia"}]
        ],
        "2": [
            [{"text": "Nutrition"}, {"text": "Genetics"}],
            [{"text": "Embryology"}, {"text": "Computer"}],
            [{"text": "Statistics"}, {"text": "Ethics"}],
            [{"text": "English"}, {"text": "Arabic"}],
            [{"text": "Islamyia"}]
        ],
        "3": [
            [{"text": "Community"}, {"text": "Pathology"}],
            [{"text": "Musculoskeletal System"}, {"text": "Sudanese Studies"}]
        ],
        "4": [
            [{"text": "Primary Health Care 1"}, {"text": "Hematology"}],
            [{"text": "Basic Skills"}, {"text": "Cardiopulmonary 1"}],
            [{"text": "The Rural"}]
        ],
        "5": [
            [{"text": "Primary Health Care 2"}, {"text": "Cardiopulmonary 2"}],
            [{"text": "Pharmacology"}, {"text": "Endocrinology"}]
        ],
        "6": [
            [{"text": "Family Medicine"}, {"text": "Gastrointestinal Tract 1"}],
            [{"text": "Gastrointestinal Tract 2"}, {"text": "Endemic Diseases"}],
            [{"text": "The Rural 2"}]
        ],
        "7": [
            [{"text": "Genito-urinary System"}, {"text": "Central Nervous System"}],
            [{"text": "Forensic Medicine"}]
        ],
        "8": [
            [{"text": "Clerkship in medicine"}, {"text": "Dermatology"}],
            [{"text": "Clerkship in Mental Health"}, {"text": "Rural Residency"}]
        ],
        "9": [
            [{"text": "Obstetrics and Gynecology"}, {"text": "Pediatrics"}]
        ],
        "10": [
            [{"text": "Surgery"}, {"text": "Ophthalmology"}],
            [{"text": "ENT"}, {"text": "Emergency medicine"}],
            [{"text": "Clerkship in Primary Health Care"}]
        ]
    }
    rows = [row[:] for row in courses_map.get(semester, [[{"text": "لا توجد مقررات"}]])]
    rows.append([{"text": "⬅️ رجوع"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": rows, "resize_keyboard": True}

def get_sections_keyboard(sections):
    rows = []
    for i in range(0, len(sections), 2):
        row = [{"text": sections[i]}]
        if i + 1 < len(sections):
            row.append({"text": sections[i + 1]})
        rows.append(row)
    rows.append([{"text": "⬅️ رجوع"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": rows, "resize_keyboard": True}

def get_types_keyboard(label):
    return {
        "keyboard": [
            [{"text": f"{label} 📄 PDF"}, {"text": f"{label} 🎥 فيديو"}],
            [{"text": f"{label} 📚 مرجع"}, {"text": f"{label} 🎙️ تسجيلات"}],
            [{"text": "⬅️ رجوع"}, {"text": "🏠 القائمة الرئيسية"}]
        ],
        "resize_keyboard": True
    }

def get_upload_finish_keyboard():
    return {
        "keyboard": [
            [{"text": "✅ انتهيت من الرفع"}],
            [{"text": "❌ إلغاء العملية"}]
        ],
        "resize_keyboard": True
    }

# =========================================================
# دوال منطق التنقل
# =========================================================
def needs_section(semester, course):
    key = (str(semester), course)
    s = COURSE_STRUCTURE.get(key)
    return s is not None and len(s.get("sections", [])) > 0

def get_sections(semester, course):
    key = (str(semester), course)
    s = COURSE_STRUCTURE.get(key)
    return s.get("sections", []) if s else []

def short_label(text):
    return text.split()[0] if text else text

# =========================================================
# Webhook
# =========================================================
@app.post("/webhook")
async def webhook(update: dict, x_telegram_bot_api_secret_token: str = Header(None)):
    try:
        if WEBHOOK_SECRET_TOKEN and x_telegram_bot_api_secret_token != WEBHOOK_SECRET_TOKEN:
            logger.warning("Invalid secret token received.")
            raise HTTPException(status_code=401, detail="Invalid secret header")

        logger.debug(f"Received update: {update}")
        post = update.get("channel_post")
        if post is not None:
            # مساعد الإعداد: أرسل /id داخل قناة البوت مشرف فيها ليرد بمعرّفها
            if (post.get("text") or "").strip() == "/id":
                cid = post["chat"]["id"]
                send_message(cid,
                    f"🆔 معرّف هذه القناة:\n{cid}\n\n"
                    f"ضعه في متغير البيئة ARCHIVE_CHANNEL_ID على Clever Cloud ثم أعد النشر. "
                    f"يمكنك حذف الرسالتين بعد ذلك.")
            return {"ok": True}

        msg = update.get("message")
        if not msg:
            return {"ok": True}

        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        user = msg.get("from", {})

        # ===== التقاط الملفات =====
        file_info = None
        content_type = None
        if "document" in msg:
            doc = msg["document"]
            mime = doc.get("mime_type", "")
            if mime.startswith("audio/") or mime.startswith("video/ogg"):
                file_info = doc
                content_type = "recording"
            else:
                file_info = doc
                content_type = "pdf"
        elif "video" in msg:
            file_info = msg["video"]
            content_type = "video"
        elif "audio" in msg:
            file_info = msg["audio"]
            content_type = "recording"
        elif "voice" in msg:
            file_info = msg["voice"]
            content_type = "recording"

        # ===== استقبال ملفات الأدمن =====
        if (file_info and is_admin(user) and chat_id in UPLOAD_SESSION
                and UPLOAD_SESSION[chat_id].get("mode") != "delete"):
            session = UPLOAD_SESSION[chat_id]
            file_id = file_info.get("file_id")
            if session.get("type") == content_type:
                session["files"].append(file_id)
                files_count = len(session["files"])
                send_message(
                    chat_id,
                    f"✅ تم استلام الملف #{files_count}\n"
                    f"📊 الإجمالي: {files_count}\n\n"
                    f"أرسل المزيد أو اضغط '✅ انتهيت من الرفع'",
                    reply_markup=get_upload_finish_keyboard()
                )
            else:
                send_message(chat_id,
                    f"⚠️ نوع الملف غير متطابق! اخترت {session.get('type')} ولكن أرسلت {content_type}")
            return {"ok": True}

        # ===== انتهيت من الرفع =====
        if text == "✅ انتهيت من الرفع" and is_admin(user) and chat_id in UPLOAD_SESSION:
            session = UPLOAD_SESSION[chat_id]
            semester = session.get("semester")
            course   = session.get("course")
            section  = session.get("section", "")
            ctype    = session.get("type")
            files    = session.get("files", [])

            if not files:
                send_message(chat_id, "⚠️ لم يتم رفع أي ملفات! أرسل الملفات أولاً.")
                return {"ok": True}

            saved_count = 0
            saved_items = []
            for file_id in files:
                try:
                    crud.add_material(semester, course, ctype, file_id,
                                      section=section)
                    saved_count += 1
                    saved_items.append((semester, course, section, ctype, file_id))
                except Exception as e:
                    logger.exception(f"Failed to save file {file_id}: {e}")

            archive_new_files(chat_id, saved_items)

            UPLOAD_SESSION.pop(chat_id, None)
            send_message(
                chat_id,
                f"✅ تم حفظ {saved_count} ملف بنجاح!\n\n"
                f"📚 السمستر: {semester}\n"
                f"📖 المقرر: {course}\n"
                f"📂 القسم: {section or '—'}\n"
                f"🗂 النوع: {ctype_label(ctype)}",
                reply_markup=get_main_keyboard(admin=True, manager=is_super_admin(user))
            )
            return {"ok": True}

        # ===== إلغاء العملية =====
        if text == "❌ إلغاء العملية" and is_admin(user) and chat_id in UPLOAD_SESSION:
            UPLOAD_SESSION.pop(chat_id, None)
            send_message(chat_id, "❌ تم إلغاء عملية الرفع.",
                         reply_markup=get_main_keyboard(admin=True, manager=is_super_admin(user)))
            return {"ok": True}

        # ===== إدارة المشرفين (للمشرفين الرئيسيين فقط) =====
        if is_super_admin(user):
            if text in ("ادارة ⚙️", "↩️ رجوع للإدارة"):
                UPLOAD_SESSION.pop(chat_id, None)
                USER_STATE.pop(chat_id, None)
                MANAGE_STATE.pop(chat_id, None)
                send_message(chat_id,
                    "⚙️ إدارة المشرفين\n\n"
                    "• المشرف المضاف يستطيع رفع المواد فقط.\n"
                    "• لا يستطيع إضافة أو حذف مشرفين.\n\n"
                    "اختر العملية:",
                    reply_markup=get_manage_keyboard(is_archive_owner(user)))
                return {"ok": True}

            if text == "➕ إضافة مشرف":
                MANAGE_STATE[chat_id] = "add"
                send_message(chat_id,
                    "➕ أرسل معرّف المشرف الجديد\n(مثال: @username)",
                    reply_markup=get_manage_back_keyboard())
                return {"ok": True}

            if text == "➖ حذف مشرف":
                names = [a["username"] for a in crud.list_admins()]
                if not names:
                    send_message(chat_id, "ℹ️ لا يوجد مشرفون مضافون لحذفهم.",
                                 reply_markup=get_manage_keyboard(is_archive_owner(user)))
                    return {"ok": True}
                MANAGE_STATE[chat_id] = "remove"
                send_message(chat_id, "➖ اختر المشرف المراد حذفه أو أرسل معرّفه:",
                             reply_markup=get_remove_admin_keyboard(names))
                return {"ok": True}

            if text == "📋 قائمة المشرفين":
                added = crud.list_admins()
                msg_lines = ["👑 المشرفون الرئيسيون:"]
                msg_lines += [f"• @{u}" for u in sorted(SUPER_ADMINS)] or ["—"]
                msg_lines += ["", "🛠 المشرفون المضافون:"]
                msg_lines += [f"• @{a['username']}" for a in added] or ["—"]
                send_message(chat_id, "\n".join(msg_lines),
                             reply_markup=get_manage_keyboard(is_archive_owner(user)))
                return {"ok": True}

            if text == ARCHIVE_BTN and is_archive_owner(user):
                MANAGE_STATE.pop(chat_id, None)
                if not ARCHIVE_CHANNEL_ID:
                    send_message(chat_id,
                        "⚠️ قناة الأرشفة غير مضبوطة.\n\n"
                        "1) أنشئ قناة خاصة وأضف البوت مشرفاً (صلاحية نشر الرسائل).\n"
                        "2) أرسل /id داخل القناة ليرد البوت بمعرّفها.\n"
                        "3) ضعه في متغير البيئة ARCHIVE_CHANNEL_ID على Clever Cloud وأعد النشر.",
                        reply_markup=get_manage_keyboard(is_archive_owner(user)))
                    return {"ok": True}
                if ARCHIVE_JOB["running"]:
                    send_message(chat_id, archive_status_text(),
                                 reply_markup=get_archive_running_keyboard())
                    return {"ok": True}
                try:
                    total_files = len(crud.get_all_materials())
                except Exception:
                    logger.exception("[ARCHIVE] failed reading materials")
                    send_message(chat_id, "❌ تعذّر قراءة الملفات من الشيت. حاول لاحقاً.",
                                 reply_markup=get_manage_keyboard(is_archive_owner(user)))
                    return {"ok": True}
                nxt = ARCHIVE_JOB["next"]
                send_message(chat_id,
                    f"📦 أرشفة المحتوى الحالي إلى القناة\n\n"
                    f"عدد الملفات المسجلة: {total_files}\n"
                    f"القناة: {ARCHIVE_CHANNEL_ID}\n\n"
                    f"⚠️ البدء من البداية مرة ثانية يكرّر الملفات في القناة. "
                    f"إن توقفت العملية استخدم «متابعة».\n"
                    f"(الملفات الجديدة تُنسخ للقناة تلقائياً عند الرفع.)",
                    reply_markup=get_archive_keyboard(1 < nxt <= total_files))
                return {"ok": True}

            if text == ARCHIVE_FROM_START_BTN and is_archive_owner(user):
                begin_archive(chat_id, 1)
                return {"ok": True}

            if text == ARCHIVE_RESUME_BTN and is_archive_owner(user):
                begin_archive(chat_id, ARCHIVE_JOB["next"])
                return {"ok": True}

            if text == ARCHIVE_CUSTOM_BTN and is_archive_owner(user):
                MANAGE_STATE[chat_id] = "archive_from"
                send_message(chat_id,
                    "🔢 أرسل رقم الملف الذي تريد البدء منه (1 هو الأقدم).",
                    reply_markup=get_manage_back_keyboard())
                return {"ok": True}

            if text == ARCHIVE_STOP_BTN and is_archive_owner(user):
                if ARCHIVE_JOB["running"]:
                    ARCHIVE_JOB["stop"] = True
                    send_message(chat_id,
                        "⏹ سيتوقف بعد الملف الحالي، وسأرسل لك ملخصاً بآخر ملف تمت معالجته.",
                        reply_markup=get_manage_keyboard(is_archive_owner(user)))
                else:
                    send_message(chat_id, "ℹ️ لا توجد أرشفة قيد التشغيل.",
                                 reply_markup=get_manage_keyboard(is_archive_owner(user)))
                return {"ok": True}

            if text == "🗑 حذف محتوى":
                MANAGE_STATE.pop(chat_id, None)
                UPLOAD_SESSION[chat_id] = {
                    "mode": "delete",
                    "semester": None, "course": None,
                    "section": None,
                    "type": None, "files": []
                }
                send_message(chat_id,
                    "🗑 حذف محتوى\n\nاختر السمستر ثم المقرر ثم القسم ثم النوع "
                    "لعرض الملفات واختيار ما تريد حذفه:",
                    reply_markup=get_semesters_keyboard())
                return {"ok": True}

            del_session = UPLOAD_SESSION.get(chat_id)
            if del_session and del_session.get("mode") == "delete" and text:
                dlist = del_session.get("delete_list") or []

                if text == DELETE_CHANGE_TYPE_BTN:
                    del_session["type"] = None
                    del_session.pop("confirm_idx", None)
                    send_message(chat_id, "🗂 اختر نوع المحتوى:",
                                 reply_markup=get_types_keyboard(
                                     short_label(del_session.get("section") or del_session.get("course") or "")))
                    return {"ok": True}

                if text == DELETE_CANCEL_BTN:
                    del_session.pop("confirm_idx", None)
                    send_message(chat_id, "↩️ تم إلغاء الحذف.",
                                 reply_markup=get_delete_keyboard(len(dlist)))
                    return {"ok": True}

                if text.startswith(DELETE_BTN) or text.startswith(DELETE_CONFIRM_BTN):
                    is_confirm = text.startswith(DELETE_CONFIRM_BTN)
                    num_part = text[len(DELETE_CONFIRM_BTN if is_confirm else DELETE_BTN):]
                    try:
                        n = int(num_part)
                    except ValueError:
                        n = 0
                    if n < 1 or n > len(dlist):
                        send_message(chat_id, "⚠️ رقم غير صالح. اختر من الأزرار.",
                                     reply_markup=get_delete_keyboard(len(dlist)))
                        return {"ok": True}

                    if not is_confirm:
                        del_session["confirm_idx"] = n
                        send_message(chat_id,
                            f"⚠️ هل تريد حذف الملف #{n} نهائياً؟\nلا يمكن التراجع عن الحذف.",
                            reply_markup=get_delete_confirm_keyboard(n))
                        return {"ok": True}

                    if del_session.get("confirm_idx") != n:
                        send_message(chat_id, "⚠️ اختر الملف أولاً ثم أكّد الحذف.",
                                     reply_markup=get_delete_keyboard(len(dlist)))
                        return {"ok": True}

                    item = dlist[n - 1]
                    result = crud.delete_material(
                        del_session.get("semester"), del_session.get("course"),
                        del_session.get("type"), item.get("file_id"),
                        section=del_session.get("section") or "")
                    logger.info(f"[DELETE MATERIAL] by={user.get('username')} result={result} "
                                f"sem={del_session.get('semester')} course={del_session.get('course')} "
                                f"section={del_session.get('section')} type={del_session.get('type')}")
                    if result == "deleted":
                        send_message(chat_id, f"✅ تم حذف الملف #{n}.")
                        show_delete_list(chat_id, del_session)
                    elif result == "not_found":
                        send_message(chat_id, "ℹ️ الملف غير موجود (ربما حُذف مسبقاً).")
                        show_delete_list(chat_id, del_session)
                    else:
                        send_message(chat_id, "❌ حدث خطأ أثناء الحذف. حاول مرة أخرى.",
                                     reply_markup=get_delete_keyboard(len(dlist)))
                    return {"ok": True}

            pending = MANAGE_STATE.get(chat_id)
            if pending and text:
                if text in ("🏠 القائمة الرئيسية", "/start", "ابدأ 🎓",
                            "تواصل مع المطور 👨‍💻", "رفع ملف جديد 📤"):
                    # خروج من وضع الإدارة وإكمال المعالجة العادية
                    MANAGE_STATE.pop(chat_id, None)
                elif pending == "archive_from" and is_archive_owner(user):
                    num = text.strip()
                    if not num.isdigit():
                        send_message(chat_id, "⚠️ أرسل رقماً صحيحاً (مثال: 1).")
                        return {"ok": True}
                    MANAGE_STATE.pop(chat_id, None)
                    begin_archive(chat_id, int(num))
                    return {"ok": True}
                else:
                    uname = text.strip().lstrip("@")
                    if not USERNAME_RE.match(uname):
                        send_message(chat_id,
                            "⚠️ معرّف غير صالح. أرسل المعرّف بصيغة @username "
                            "(حروف إنجليزية وأرقام و _ فقط، من 5 إلى 32 حرفاً).")
                        return {"ok": True}

                    if pending == "add":
                        if uname.lower() in SUPER_ADMINS:
                            reply = f"ℹ️ @{uname} مشرف رئيسي بالفعل."
                        else:
                            result = crud.add_admin(uname, added_by=user.get("username"))
                            if result == "added":
                                reply = (f"✅ تمت إضافة @{uname} كمشرف.\n"
                                         f"يجب أن يرسل /start للبوت ليظهر له زر الرفع.")
                            elif result == "exists":
                                reply = f"ℹ️ @{uname} مشرف بالفعل."
                            else:
                                reply = "❌ حدث خطأ أثناء الإضافة. حاول مرة أخرى."
                    else:
                        if uname.lower() in SUPER_ADMINS:
                            reply = (f"⛔ @{uname} مشرف رئيسي ولا يمكن حذفه من البوت "
                                     f"(يُدار من متغيرات البيئة).")
                        else:
                            result = crud.remove_admin(uname)
                            if result == "removed":
                                reply = f"✅ تم حذف @{uname} من المشرفين."
                            elif result == "not_found":
                                reply = f"ℹ️ @{uname} ليس ضمن المشرفين المضافين."
                            else:
                                reply = "❌ حدث خطأ أثناء الحذف. حاول مرة أخرى."

                    MANAGE_STATE.pop(chat_id, None)
                    send_message(chat_id, reply, reply_markup=get_manage_keyboard(is_archive_owner(user)))
                    return {"ok": True}

        # ===== رفع ملف جديد =====
        if text == "رفع ملف جديد 📤" and is_admin(user):
            UPLOAD_SESSION[chat_id] = {
                "semester": None, "course": None,
                "section": None,
                "type": None, "files": []
            }
            send_message(chat_id, "📤 اختر السمستر:", reply_markup=get_semesters_keyboard())
            return {"ok": True}

        # ===== /addfile =====
        if text and text.startswith("/addfile") and is_admin(user):
            parts = text.split()
            if len(parts) >= 5:
                semester, course, ctype, file_id = parts[1], parts[2], parts[3], parts[4]
                section = parts[5] if len(parts) > 5 else ""
                crud.add_material(semester, course, ctype, file_id,
                                  section=section)
                archive_new_files(chat_id, [(semester, course, section, ctype, file_id)])
                send_message(chat_id, "✅ تمت الإضافة بنجاح!")
            else:
                send_message(chat_id,
                    "❌ الصيغة:\n/addfile <semester> <course> <type> <file_id> [section]")
            return {"ok": True}

        # ===== /start =====
        if text == "/start":
            USER_STATE.pop(chat_id, None)
            UPLOAD_SESSION.pop(chat_id, None)
            welcome_text = (
                "👋 مرحبًا بك في بوت كلية الطب – جامعة المناقل\n\n"
                "📚 هذا البوت يساعدك للوصول إلى محتوى المقررات بسهولة.\n"
            )
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin(user), is_super_admin(user)))
            return {"ok": True}

        # ===== تواصل مع المطور =====
        if text == "تواصل مع المطور 👨‍💻":
            send_message(chat_id, f"📩 تواصل مع المطور: {DEVELOPER_USERNAME}")
            return {"ok": True}

        # ===== القائمة الرئيسية =====
        if text == "🏠 القائمة الرئيسية":
            USER_STATE.pop(chat_id, None)
            UPLOAD_SESSION.pop(chat_id, None)
            send_message(chat_id, "🏠 عدت إلى القائمة الرئيسية",
                         reply_markup=get_main_keyboard(is_admin(user), is_super_admin(user)))
            return {"ok": True}

        # ===== ابدأ =====
        if text == "ابدأ 🎓":
            USER_STATE.pop(chat_id, None)
            send_message(chat_id, "📚 اختر الفصل الدراسي:",
                         reply_markup=get_semesters_keyboard())
            return {"ok": True}

        # ===== رجوع =====
        if text == "⬅️ رجوع":
            state = USER_STATE.get(chat_id, {})

            # عند شاشة نوع المحتوى (بعد القسم) → رجوع للأقسام
            if state.get("section") and state.get("course"):
                # نمسح section ونعرض الأقسام من جديد
                section_backup = state.pop("section")
                USER_STATE[chat_id] = state
                sections = get_sections(state["semester"], state["course"])
                send_message(chat_id, "⬅️ اختر القسم:",
                             reply_markup=get_sections_keyboard(sections))
                return {"ok": True}

            # عند شاشة القسم أو المقرر → رجوع للمقررات
            if state.get("course"):
                state.pop("course", None)
                USER_STATE[chat_id] = state
                send_message(chat_id, "⬅️ اختر المقرر:",
                             reply_markup=get_courses_keyboard(state["semester"]))
                return {"ok": True}

            # عند شاشة المقررات → رجوع للفصول
            if state.get("semester"):
                USER_STATE.pop(chat_id, None)
                send_message(chat_id, "⬅️ اختر الفصل الدراسي:",
                             reply_markup=get_semesters_keyboard())
                return {"ok": True}

            send_message(chat_id, "⬅️ اختر الفصل الدراسي:",
                         reply_markup=get_semesters_keyboard())
            return {"ok": True}

        # ===== اختيار السمستر =====
        semester_map = {
            "الفصل الأول ": "1",  "الفصل الثاني ": "2",
            "الفصل الثالث ": "3", "الفصل الرابع ": "4",
            "الفصل الخامس ": "5", "الفصل السادس ": "6",
            "الفصل السابع ": "7", "الفصل الثامن ": "8",
            "الفصل التاسع ": "9", "الفصل العاشر ": "10",
            "الفصل الأول": "1",  "الفصل الثاني": "2",
            "الفصل الثالث": "3", "الفصل الرابع": "4",
            "الفصل الخامس": "5", "الفصل السادس": "6",
            "الفصل السابع": "7", "الفصل الثامن": "8",
            "الفصل التاسع": "9", "الفصل العاشر": "10",
        }

        if text in semester_map:
            semester = semester_map[text]
            if is_admin(user) and chat_id in UPLOAD_SESSION:
                UPLOAD_SESSION[chat_id]["semester"] = semester
                send_message(chat_id, f"✅ السمستر {semester}. اختر المقرر:",
                             reply_markup=get_courses_keyboard(semester))
                return {"ok": True}
            USER_STATE[chat_id] = {"semester": semester}
            send_message(chat_id, "📖 اختر المقرر:",
                         reply_markup=get_courses_keyboard(semester))
            return {"ok": True}

        # ===== اختيار المقرر =====
        course_names = [
            "Introduction", "Biochemistry 1", "Parasitology", "Histology",
            "Physiology", "Medical Physics", "Islamyia",
            "Nutrition", "Genetics", "Embryology", "Computer",
            "Statistics", "Ethics",
            "Community", "Pathology", "Musculoskeletal System", "Sudanese Studies",
            "Primary Health Care 1", "Hematology", "Basic Skills",
            "Cardiopulmonary 1", "The Rural",
            "Primary Health Care 2", "Cardiopulmonary 2",
            "Pharmacology", "Endocrinology",
            "Family Medicine", "Gastrointestinal Tract 1",
            "Gastrointestinal Tract 2", "Endemic Diseases", "The Rural 2",
            "Genito-urinary System", "Central Nervous System", "Forensic Medicine",
            "Clerkship in medicine", "Dermatology",
            "Clerkship in Mental Health", "Rural Residency",
            "Obstetrics and Gynecology", "Pediatrics",
            "Surgery", "Ophthalmology", "ENT", "Emergency medicine",
            "Clerkship in Primary Health Care",
            "English", "Arabic",
        ]

        if text in course_names:
            state = USER_STATE.get(chat_id, {})

            if is_admin(user) and chat_id in UPLOAD_SESSION:
                session = UPLOAD_SESSION[chat_id]
                semester = session.get("semester")
                # إذا المقرر محدد بالفعل والنص قسم → تجاوز لمعالج القسم
                if session.get("course") and text in ALL_SECTIONS:
                    pass
                else:
                    session["course"] = text
                    if needs_section(semester, text):
                        sections = get_sections(semester, text)
                        send_message(chat_id, f"📂 اختر القسم لـ {text}:",
                                     reply_markup=get_sections_keyboard(sections))
                    else:
                        send_message(chat_id, f"🗂 اختر نوع المحتوى لـ {text}:",
                                     reply_markup=get_types_keyboard(short_label(text)))
                    return {"ok": True}

            else:
                semester = state.get("semester")
                # إذا المقرر محدد بالفعل والنص قسم → تجاوز لمعالج القسم
                if state.get("course") and text in ALL_SECTIONS:
                    pass
                else:
                    if not semester:
                        send_message(chat_id, "⚠️ يرجى اختيار السمستر أولاً")
                        return {"ok": True}
                    state["course"] = text
                    USER_STATE[chat_id] = state
                    if needs_section(semester, text):
                        sections = get_sections(semester, text)
                        send_message(chat_id, "📂 اختر القسم:",
                                     reply_markup=get_sections_keyboard(sections))
                    else:
                        send_message(chat_id, "🗂 اختر نوع المحتوى:",
                                     reply_markup=get_types_keyboard(short_label(text)))
                    return {"ok": True}

        # ===== اختيار القسم =====
        if text in ALL_SECTIONS:
            state = USER_STATE.get(chat_id, {})

            if is_admin(user) and chat_id in UPLOAD_SESSION:
                session = UPLOAD_SESSION[chat_id]
                semester = session.get("semester")
                course   = session.get("course")
                session["section"] = text
                logger.debug(f"[ADMIN SECTION] sem={semester} course={course} section={text}")
                send_message(chat_id, "🗂 اختر نوع المحتوى:",
                             reply_markup=get_types_keyboard(short_label(text)))
                return {"ok": True}

            semester = state.get("semester")
            course   = state.get("course")
            logger.debug(f"[USER SECTION] state={state} text={text}")
            if not semester or not course:
                send_message(chat_id, "⚠️ يرجى اختيار السمستر والمقرر أولاً")
                return {"ok": True}

            state["section"] = text
            USER_STATE[chat_id] = state

            send_message(chat_id, "🗂 اختر نوع المحتوى:",
                         reply_markup=get_types_keyboard(short_label(text)))
            return {"ok": True}

        # ===== اختيار نوع المحتوى =====
        if text and any(x in text for x in ["📄 PDF", "🎥 فيديو", "📚 مرجع", "🎙️ تسجيلات"]):
            if "PDF" in text:
                ctype = "pdf"
            elif "فيديو" in text:
                ctype = "video"
            elif "تسجيلات" in text:
                ctype = "recording"
            else:
                ctype = "reference"

            if is_admin(user) and chat_id in UPLOAD_SESSION:
                session = UPLOAD_SESSION[chat_id]
                if not session.get("semester") or not session.get("course"):
                    send_message(chat_id, "❌ بيانات غير مكتملة. أعد العملية.")
                    return {"ok": True}
                if session.get("mode") == "delete":
                    if not is_super_admin(user):
                        UPLOAD_SESSION.pop(chat_id, None)
                        send_message(chat_id, "⛔ هذه الصلاحية للمشرفين الرئيسيين فقط.",
                                     reply_markup=get_main_keyboard(admin=True))
                        return {"ok": True}
                    session["type"] = ctype
                    show_delete_list(chat_id, session)
                    return {"ok": True}
                session["type"] = ctype
                send_message(
                    chat_id,
                    f"✅ جاهز للرفع!\n\n"
                    f"📚 السمستر: {session.get('semester')}\n"
                    f"📖 المقرر: {session.get('course')}\n"
                    f"📂 القسم: {session.get('section') or '—'}\n"
                    f"🗂 النوع: {ctype_label(ctype)}\n\n"
                    f"أرسل الملفات واحداً تلو الآخر ثم اضغط '✅ انتهيت من الرفع'",
                    reply_markup=get_upload_finish_keyboard()
                )
                return {"ok": True}

            state    = USER_STATE.get(chat_id, {})
            semester = state.get("semester")
            course   = state.get("course")
            section  = state.get("section", "")

            if not semester or not course:
                send_message(chat_id, "⚠️ يرجى اختيار السمستر والمقرر أولاً")
                return {"ok": True}

            mats = crud.get_materials(semester, course, ctype,
                                      section=section, use_cache=True)
            if not mats:
                send_message(chat_id,
                    f"🚧 لا توجد ملفات متاحة حالياً\n"
                    f"المقرر: {course} | القسم: {section or '—'}")
                return {"ok": True}

            send_message(chat_id, f"📤 جاري الإرسال... ({len(mats)} ملف)")
            for m in mats:
                send_file(chat_id, m.get("file_id"), content_type=ctype)
            return {"ok": True}

        # ===== افتراضي =====
        send_message(chat_id, "🤔 لم أفهم الأمر، يرجى اختيار من القائمة.")
        return {"ok": True}

    except Exception as e:
        logger.exception(f"Exception in webhook processing: {e}")
        return {"ok": True}
