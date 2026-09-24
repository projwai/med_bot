import os
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

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Med Faculty Bot")

@app.on_event("startup")
async def startup():
    crud.init_db()
    logger.info("✅ Database initialized successfully.")

# ========= إدارة رفع الملفات المتعددة للأدمن =========
# session: {"semester", "course", "section", "doctor", "type", "files": [...]}
UPLOAD_SESSION = {}

# ========= حالة المستخدم =========
# state: {"semester", "course", "section", "doctor"}
USER_STATE = {}

# ========= هيكل المحتوى التفصيلي =========
# الفصل الأول: لا أقسام ولا دكاترة (كما هو)
# الفصل الثاني: Embryology فقط له أقسام، بدون دكاترة
# الفصل الثالث: أقسام بدون دكاترة
# الفصل الرابع وما بعد: أقسام + دكاترة

COURSE_STRUCTURE = {
    # ======= الفصل الثاني =======
    ("2", "Embryology"): {
        "sections": ["Internal", "External"],
        "has_doctors": False
    },
    # باقي مواد الفصل الثاني بدون أقسام
    ("2", "Nutrition"):    {"sections": [], "has_doctors": False},
    ("2", "Genetics"):     {"sections": [], "has_doctors": False},
    ("2", "Computer"):     {"sections": [], "has_doctors": False},
    ("2", "Statistics"):   {"sections": [], "has_doctors": False},
    ("2", "Ethics"):       {"sections": [], "has_doctors": False},
    ("2", "English"):      {"sections": [], "has_doctors": False},
    ("2", "Arabic"):       {"sections": [], "has_doctors": False},
    ("2", "Islamyia"):     {"sections": [], "has_doctors": False},

    # ======= الفصل الثالث =======
    ("3", "Pathology"): {
        "sections": ["General Pathology", "Bacteriology", "Virology", "Mycology"],
        "has_doctors": False
    },
    ("3", "Musculoskeletal System"): {
        "sections": ["Physiology", "Pathology", "Anatomy", "DR"],
        "has_doctors": False
    },
    ("3", "Community"):       {"sections": [], "has_doctors": False},
    ("3", "Sudanese Studies"): {"sections": [], "has_doctors": False},

    # ======= الفصل الرابع =======
    ("4", "Hematology"): {
        "sections": ["Physiology", "Pathology"],
        "has_doctors": True,
        "doctors": {
            "Physiology": ["د. وفاء", "د. ناجي", "د. طارق مصطفى"],
            "Pathology":  ["د. فردوس", "د. منى مهنا", "د. عبدالله عبد القادر",
                           "د. عبد الرحيم محمد", "د. عمر عدلان", "د. ياسر محمد",
                           "د. عبد العزيز خوجلي", "د. طارق مصطفى"],
        }
    },
    ("4", "Cardiopulmonary 1"): {
        "sections": ["Anatomy", "DR", "Pathology", "Physiology"],
        "has_doctors": True,
        "doctors": {
            "Anatomy":    ["د. أبوعلامة", "د. السر"],
            "DR":         ["د. أبوعلامة"],
            "Pathology":  ["د. يوسف عمر", "د. عبد العزيز خوجلي", "د. فردوس إبراهيم",
                           "د. عمر عدلان", "د. ياسر محمد", "د. أحمد الريح",
                           "د. محمد يوسف هجو"],
            "Physiology": ["د. محمد نور", "د. ناجي"],
        }
    },
    ("4", "Primary Health Care 1"): {"sections": [], "has_doctors": False},
    ("4", "Basic Skills"):           {"sections": [], "has_doctors": False},
    ("4", "The Rural"):              {"sections": [], "has_doctors": False},

    # ======= الفصل الخامس =======
    ("5", "Cardiopulmonary 2"): {
        "sections": ["Anatomy + Embryology", "Pathology", "Physiology",
                     "Clinical", "Examination + History"],
        "has_doctors": True,
        "doctors": {
            "Anatomy + Embryology":   ["د. أبوعلامة"],
            "Pathology":              ["د. يوسف"],
            "Physiology":             ["د. محمد نور"],
            "Clinical":               ["د. عبد الرحيم", "د. فردوس", "د. عبدالله عبد القادر",
                                       "د. منى مهنا", "د. أبومدين", "د. معز عبودي",
                                       "د. عبد العزيز خوجلي", "د. أحمد الريح"],
            "Examination + History":  ["د. فردوس", "د. أحمد الريح", "د. منى مهنا",
                                       "د. عبد الرحيم", "د. عبدالله عبد القادر"],
        }
    },
    ("5", "Endocrinology"): {
        "sections": ["Physiology", "Anatomy + Embryology + Histology",
                     "Clinical", "Biochemistry", "Pathology"],
        "has_doctors": True,
        "doctors": {
            "Physiology":                        ["د. محمد نور", "د. ناجي"],
            "Anatomy + Embryology + Histology":  ["د. أبوعلامة"],
            "Clinical":                          ["د. عبدالله عبد القادر", "د. عبد الرحيم",
                                                  "د. فردوس", "د. منى مهنا", "د. أحمد الريح",
                                                  "د. عبد العزيز خوجلي", "د. ياسر محمد",
                                                  "د. أبومدين"],
            "Biochemistry":                      ["د. صلاح"],
            "Pathology":                         ["د. فردوس", "د. منى مهنا",
                                                  "د. عبدالله عبد القادر", "د. عبد الرحيم",
                                                  "د. أحمد الريح", "د. أبومدين",
                                                  "د. عبد العزيز خوجلي", "د. ياسر محمد"],
        }
    },
    ("5", "Pharmacology"): {
        "sections": ["General", "Autonomic"],
        "has_doctors": True,
        "doctors": {
            "General":   ["د. مصعب الأنصاري", "د. أبومدين"],
            "Autonomic": ["د. أبومدين", "د. مصعب الأنصاري"],
        }
    },
    ("5", "Primary Health Care 2"): {"sections": [], "has_doctors": False},

    # ======= الفصل السادس =======
    ("6", "Gastrointestinal Tract 1"): {
        "sections": ["Anatomy + Embryology + Histology", "DR",
                     "Physiology", "Pathology", "Clinical"],
        "has_doctors": True,
        "doctors": {
            "Anatomy + Embryology + Histology": ["د. أبوعلامة"],
            "DR":        ["د. عبد الرحيم"],
            "Physiology": ["د. محمد نور", "د. ناجي"],
            "Pathology":  ["د. يوسف"],
            "Clinical":   ["د. أحمد الريح"],
        }
    },
    ("6", "Gastrointestinal Tract 2"): {
        "sections": ["Anatomy + Embryology + Histology", "Pathology",
                     "Physiology", "Clinical", "Examination + History"],
        "has_doctors": True,
        "doctors": {
            "Anatomy + Embryology + Histology": ["د. أبوعلامة"],
            "Pathology":  ["د. يوسف"],
            "Physiology": ["د. ناجي", "د. محمد نور"],
            "Clinical":   ["د. فردوس", "د. عبدالله عبد القادر", "د. أحمد الريح",
                           "د. منى مهنا", "د. عبد الرحيم", "د. أبومدين"],
            "Examination + History": ["د. منى مهنا"],
        }
    },
    ("6", "Family Medicine"):  {"sections": [], "has_doctors": False},
    ("6", "Endemic Diseases"): {"sections": [], "has_doctors": False},
    ("6", "The Rural 2"):      {"sections": [], "has_doctors": False},

    # ======= الفصل السابع =======
    ("7", "Genito-urinary System"): {
        "sections": ["Anatomy", "Physiology", "Pathology",
                     "Clinical", "Examination + History"],
        "has_doctors": True,
        "doctors": {
            "Anatomy":   ["د. أبوعلامة"],
            "Physiology": ["د. ناجي"],
            "Pathology":  ["د. محمد يوسف"],
            "Clinical":   ["د. محمد الأمين", "د. ياسر البر", "د. المعز",
                           "د. محمد المسلمي", "د. أحمد الريح"],
            "Examination + History": [],
        }
    },
    ("7", "Central Nervous System"): {
        "sections": ["Anatomy", "Physiology", "Pathology",
                     "Clinical", "Examination + History"],
        "has_doctors": True,
        "doctors": {
            "Anatomy":   ["د. أبوعلامة"],
            "Physiology": ["د. محمد نور"],
            "Pathology":  ["د. يوسف عمر"],
            "Clinical":   ["د. منى مهنا", "د. فردوس", "د. عبدالله عبد القادر",
                           "د. أحمد الريح", "د. عبد الرحيم", "د. عبد العزيز",
                           "د. أبومدين"],
            "Examination + History": ["د. فردوس"],
        }
    },
    ("7", "Forensic Medicine"): {"sections": [], "has_doctors": False},
}

# مجموعة أسماء الأقسام الكاملة لكل المواد (للكشف عن الضغط)
ALL_SECTIONS = set()
for v in COURSE_STRUCTURE.values():
    for s in v.get("sections", []):
        ALL_SECTIONS.add(s)

# مجموعة أسماء الدكاترة الكاملة
ALL_DOCTORS = set()
for v in COURSE_STRUCTURE.values():
    for doc_list in v.get("doctors", {}).values():
        for d in doc_list:
            ALL_DOCTORS.add(d)

# ========= دوال مساعدة =========
def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        logger.info(f"Send message status: {r.status_code}, response: {r.text}")
    except Exception as e:
        logger.exception(f"Failed to send message: {e}")

def send_file(chat_id, file_id, content_type="pdf"):
    try:
        if content_type == "video":
            r = requests.post(f"{TELEGRAM_API}/sendVideo", json={"chat_id": chat_id, "video": file_id})
        elif content_type == "recording":
            r = requests.post(f"{TELEGRAM_API}/sendAudio", json={"chat_id": chat_id, "audio": file_id})
        else:
            r = requests.post(f"{TELEGRAM_API}/sendDocument", json={"chat_id": chat_id, "document": file_id})
        logger.info(f"Send file status: {r.status_code}, response: {r.text}")
    except Exception as e:
        logger.exception(f"Failed to send file: {e}")

def is_admin(user):
    return user.get("username") in ADMIN_USERNAMES

def ctype_label(ctype):
    return {"pdf": "PDF 📄", "video": "فيديو 🎥",
            "recording": "تسجيلات 🎙️", "reference": "مرجع 📚"}.get(ctype, ctype)

# ========= بناء لوحات المفاتيح =========
def get_main_keyboard(admin=False):
    buttons = [[{"text": "ابدأ 🎓"}], [{"text": "تواصل مع المطور 👨‍💻"}]]
    if admin:
        buttons.append([{"text": "رفع ملف جديد 📤"}])
    return {"keyboard": buttons, "resize_keyboard": True}

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
    course_buttons = courses_map.get(semester, [[{"text": "لا توجد مقررات"}]])
    course_buttons = [row[:] for row in course_buttons]  # نسخ عميق
    course_buttons.append([{"text": "⬅️ رجوع"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": course_buttons, "resize_keyboard": True}

def get_sections_keyboard(sections):
    """لوحة مفاتيح الأقسام"""
    rows = []
    for i in range(0, len(sections), 2):
        row = [{"text": sections[i]}]
        if i + 1 < len(sections):
            row.append({"text": sections[i + 1]})
        rows.append(row)
    rows.append([{"text": "⬅️ رجوع"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": rows, "resize_keyboard": True}

def get_doctors_keyboard(doctors):
    """لوحة مفاتيح الدكاترة"""
    rows = []
    for i in range(0, len(doctors), 2):
        row = [{"text": doctors[i]}]
        if i + 1 < len(doctors):
            row.append({"text": doctors[i + 1]})
        rows.append(row)
    rows.append([{"text": "⬅️ رجوع"}, {"text": "🏠 القائمة الرئيسية"}])
    return {"keyboard": rows, "resize_keyboard": True}

def get_types_keyboard(label):
    """لوحة مفاتيح نوع المحتوى - label هو الاسم المختصر للزر"""
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

# ========= دوال منطق التنقل =========
def needs_section(semester, course):
    """هل هذه المادة تحتاج اختيار قسم؟"""
    key = (str(semester), course)
    s = COURSE_STRUCTURE.get(key)
    return s is not None and len(s.get("sections", [])) > 0

def needs_doctor(semester, course, section):
    """هل هذا القسم يحتاج اختيار دكتور؟"""
    key = (str(semester), course)
    s = COURSE_STRUCTURE.get(key)
    if not s or not s.get("has_doctors"):
        return False
    doctors = s.get("doctors", {}).get(section, [])
    return len(doctors) > 0

def get_sections(semester, course):
    key = (str(semester), course)
    s = COURSE_STRUCTURE.get(key)
    return s.get("sections", []) if s else []

def get_doctors(semester, course, section):
    key = (str(semester), course)
    s = COURSE_STRUCTURE.get(key)
    if not s:
        return []
    return s.get("doctors", {}).get(section, [])

# label مختصر للزر (أول كلمة أو اسم مناسب)
def short_label(text):
    return text.split()[0] if text else text

# ========= Webhook =========
@app.post("/webhook")
async def webhook(update: dict, x_telegram_bot_api_secret_token: str = Header(None)):
    try:
        if WEBHOOK_SECRET_TOKEN and x_telegram_bot_api_secret_token != WEBHOOK_SECRET_TOKEN:
            logger.warning("Invalid secret token received.")
            raise HTTPException(status_code=401, detail="Invalid secret header")

        logger.debug(f"Received update: {update}")
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

        # ===== استقبال ملفات الأدمن في جلسة رفع نشطة =====
        if file_info and is_admin(user) and chat_id in UPLOAD_SESSION:
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
                send_message(chat_id, f"⚠️ نوع الملف غير متطابق! اخترت {session.get('type')} ولكن أرسلت {content_type}")
            return {"ok": True}

        # ===== انتهيت من الرفع =====
        if text == "✅ انتهيت من الرفع" and is_admin(user) and chat_id in UPLOAD_SESSION:
            session = UPLOAD_SESSION[chat_id]
            semester = session.get("semester")
            course   = session.get("course")
            section  = session.get("section", "")
            doctor   = session.get("doctor", "")
            ctype    = session.get("type")
            files    = session.get("files", [])

            if not files:
                send_message(chat_id, "⚠️ لم يتم رفع أي ملفات! أرسل الملفات أولاً.")
                return {"ok": True}

            saved_count = 0
            for file_id in files:
                try:
                    crud.add_material(semester, course, ctype, file_id,
                                      section=section, doctor=doctor)
                    saved_count += 1
                except Exception as e:
                    logger.exception(f"Failed to save file {file_id}: {e}")

            UPLOAD_SESSION.pop(chat_id, None)
            send_message(
                chat_id,
                f"✅ تم حفظ {saved_count} ملف بنجاح!\n\n"
                f"📚 السمستر: {semester}\n"
                f"📖 المقرر: {course}\n"
                f"📂 القسم: {section or '—'}\n"
                f"👨‍⚕️ الدكتور: {doctor or '—'}\n"
                f"🗂 النوع: {ctype_label(ctype)}",
                reply_markup=get_main_keyboard(admin=True)
            )
            return {"ok": True}

        # ===== إلغاء العملية =====
        if text == "❌ إلغاء العملية" and is_admin(user) and chat_id in UPLOAD_SESSION:
            UPLOAD_SESSION.pop(chat_id, None)
            send_message(chat_id, "❌ تم إلغاء عملية الرفع.", reply_markup=get_main_keyboard(admin=True))
            return {"ok": True}

        # ===== رفع ملف جديد (أدمن) =====
        if text == "رفع ملف جديد 📤" and is_admin(user):
            UPLOAD_SESSION[chat_id] = {
                "semester": None, "course": None,
                "section": None, "doctor": None,
                "type": None, "files": []
            }
            send_message(chat_id, "📤 اختر السمستر:", reply_markup=get_semesters_keyboard())
            return {"ok": True}

        # ===== /addfile (أدمن) =====
        if text and text.startswith("/addfile") and is_admin(user):
            parts = text.split()
            if len(parts) >= 5:
                semester, course, ctype, file_id = parts[1], parts[2], parts[3], parts[4]
                section = parts[5] if len(parts) > 5 else ""
                doctor  = parts[6] if len(parts) > 6 else ""
                crud.add_material(semester, course, ctype, file_id,
                                  section=section, doctor=doctor)
                send_message(chat_id, f"✅ تمت الإضافة بنجاح!")
            else:
                send_message(chat_id,
                    "❌ الصيغة:\n/addfile <semester> <course> <type> <file_id> [section] [doctor]")
            return {"ok": True}

        # ===== /start =====
        if text == "/start":
            USER_STATE.pop(chat_id, None)
            UPLOAD_SESSION.pop(chat_id, None)
            welcome_text = (
                "👋 مرحبًا بك في بوت كلية الطب – جامعة المناقل\n\n"
                "📚 هذا البوت يساعدك للوصول إلى محتوى المقررات بسهولة.\n"
            )
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin(user)))
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
                         reply_markup=get_main_keyboard(is_admin(user)))
            return {"ok": True}

        # ===== ابدأ =====
        if text == "ابدأ 🎓":
            USER_STATE.pop(chat_id, None)
            send_message(chat_id, "📚 اختر الفصل الدراسي:", reply_markup=get_semesters_keyboard())
            return {"ok": True}

        # ===== رجوع =====
        if text == "⬅️ رجوع":
            state = USER_STATE.get(chat_id, {})

            # إذا كان عند الدكتور → رجع للأقسام
            if state.get("doctor"):
                state.pop("doctor", None)
                USER_STATE[chat_id] = state
                sections = get_sections(state["semester"], state["course"])
                send_message(chat_id, "⬅️ اختر القسم:",
                             reply_markup=get_sections_keyboard(sections))
                return {"ok": True}

            # إذا كان عند القسم → رجع للمقررات
            if state.get("section"):
                state.pop("section", None)
                USER_STATE[chat_id] = state
                send_message(chat_id, "⬅️ اختر المقرر:",
                             reply_markup=get_courses_keyboard(state["semester"]))
                return {"ok": True}

            # إذا كان عند المقرر → رجع للسمسترات
            if state.get("course"):
                state.pop("course", None)
                USER_STATE[chat_id] = state
                send_message(chat_id, "⬅️ اختر المقرر:",
                             reply_markup=get_courses_keyboard(state["semester"]))
                return {"ok": True}

            # إذا كان عند السمستر → رجع للسمسترات
            if state.get("semester"):
                USER_STATE.pop(chat_id, None)
                send_message(chat_id, "⬅️ اختر الفصل الدراسي:",
                             reply_markup=get_semesters_keyboard())
                return {"ok": True}

            send_message(chat_id, "⬅️ اختر الفصل الدراسي:", reply_markup=get_semesters_keyboard())
            return {"ok": True}

        # ===== اختيار السمستر =====
        semester_map = {
            "الفصل الأول ": "1", "الفصل الثاني ": "2",
            "الفصل الثالث ": "3", "الفصل الرابع ": "4",
            "الفصل الخامس ": "5", "الفصل السادس ": "6",
            "الفصل السابع ": "7", "الفصل الثامن ": "8",
            "الفصل التاسع ": "9", "الفصل العاشر ": "10",
            # بدون مسافة أيضاً للأمان
            "الفصل الأول": "1", "الفصل الثاني": "2",
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
            send_message(chat_id, f"📖 اختر المقرر:", reply_markup=get_courses_keyboard(semester))
            return {"ok": True}

        # ===== اختيار المقرر =====
        course_names = [
            # الأول
            "Introduction", "Biochemistry 1", "Parasitology", "Histology",
            "Physiology", "Medical Physics", "Islamyia",
            # الثاني
            "Nutrition", "Genetics", "Embryology", "Computer",
            "Statistics", "Ethics",
            # الثالث
            "Community", "Pathology", "Musculoskeletal System", "Sudanese Studies",
            # الرابع
            "Primary Health Care 1", "Hematology", "Basic Skills",
            "Cardiopulmonary 1", "The Rural",
            # الخامس
            "Primary Health Care 2", "Cardiopulmonary 2",
            "Pharmacology", "Endocrinology",
            # السادس
            "Family Medicine", "Gastrointestinal Tract 1",
            "Gastrointestinal Tract 2", "Endemic Diseases", "The Rural 2",
            # السابع
            "Genito-urinary System", "Central Nervous System", "Forensic Medicine",
            # الثامن
            "Clerkship in medicine", "Dermatology",
            "Clerkship in Mental Health", "Rural Residency",
            # التاسع
            "Obstetrics and Gynecology", "Pediatrics",
            # العاشر
            "Surgery", "Ophthalmology", "ENT", "Emergency medicine",
            "Clerkship in Primary Health Care",
            # مشترك
            "English", "Arabic",
        ]

        if text in course_names:
            state = USER_STATE.get(chat_id, {})
            semester = state.get("semester")

            if is_admin(user) and chat_id in UPLOAD_SESSION:
                session = UPLOAD_SESSION[chat_id]
                semester = session.get("semester")
                # إذا المقرر محدد بالفعل والنص موجود في ALL_SECTIONS → هو قسم لا مادة
                if session.get("course") and text in ALL_SECTIONS:
                    pass  # يكمل لمعالج القسم أدناه
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
                # مستخدم عادي: إذا المقرر محدد بالفعل والنص في ALL_SECTIONS → قسم
                if state.get("course") and text in ALL_SECTIONS:
                    pass  # يكمل لمعالج القسم أدناه
                else:
                    if not semester:
                        send_message(chat_id, "⚠️ يرجى اختيار السمستر أولاً")
                        return {"ok": True}

                    state["course"] = text
                    USER_STATE[chat_id] = state

                    if needs_section(semester, text):
                        sections = get_sections(semester, text)
                        send_message(chat_id, f"📂 اختر القسم:", reply_markup=get_sections_keyboard(sections))
                    else:
                        send_message(chat_id, f"🗂 اختر نوع المحتوى:", reply_markup=get_types_keyboard(short_label(text)))
                    return {"ok": True}

        # ===== اختيار القسم =====
        if text in ALL_SECTIONS:
            state = USER_STATE.get(chat_id, {})

            if is_admin(user) and chat_id in UPLOAD_SESSION:
                session = UPLOAD_SESSION[chat_id]
                semester = session.get("semester")
                course   = session.get("course")
                session["section"] = text
                # هل يحتاج دكتور؟
                if needs_doctor(semester, course, text):
                    doctors = get_doctors(semester, course, text)
                    send_message(chat_id, f"👨‍⚕️ اختر الدكتور:",
                                 reply_markup=get_doctors_keyboard(doctors))
                else:
                    send_message(chat_id, f"🗂 اختر نوع المحتوى:",
                                 reply_markup=get_types_keyboard(short_label(text)))
                return {"ok": True}

            semester = state.get("semester")
            course   = state.get("course")
            if not semester or not course:
                send_message(chat_id, "⚠️ يرجى اختيار السمستر والمقرر أولاً")
                return {"ok": True}

            state["section"] = text
            USER_STATE[chat_id] = state

            if needs_doctor(semester, course, text):
                doctors = get_doctors(semester, course, text)
                send_message(chat_id, f"👨‍⚕️ اختر الدكتور:", reply_markup=get_doctors_keyboard(doctors))
            else:
                send_message(chat_id, f"🗂 اختر نوع المحتوى:", reply_markup=get_types_keyboard(short_label(text)))
            return {"ok": True}

        # ===== اختيار الدكتور =====
        if text in ALL_DOCTORS:
            state = USER_STATE.get(chat_id, {})

            if is_admin(user) and chat_id in UPLOAD_SESSION:
                UPLOAD_SESSION[chat_id]["doctor"] = text
                section = UPLOAD_SESSION[chat_id].get("section", "")
                send_message(chat_id, f"🗂 اختر نوع المحتوى:",
                             reply_markup=get_types_keyboard(short_label(section or text)))
                return {"ok": True}

            if not state.get("semester") or not state.get("course"):
                send_message(chat_id, "⚠️ يرجى اختيار السمستر والمقرر أولاً")
                return {"ok": True}

            state["doctor"] = text
            USER_STATE[chat_id] = state
            section = state.get("section", "")
            send_message(chat_id, f"🗂 اختر نوع المحتوى:",
                         reply_markup=get_types_keyboard(short_label(section or text)))
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

            # الأدمن: حفظ النوع وانتظار الملفات
            if is_admin(user) and chat_id in UPLOAD_SESSION:
                session = UPLOAD_SESSION[chat_id]
                if not session.get("semester") or not session.get("course"):
                    send_message(chat_id, "❌ بيانات غير مكتملة. أعد العملية.")
                    return {"ok": True}
                session["type"] = ctype
                send_message(
                    chat_id,
                    f"✅ جاهز للرفع!\n\n"
                    f"📚 السمستر: {session.get('semester')}\n"
                    f"📖 المقرر: {session.get('course')}\n"
                    f"📂 القسم: {session.get('section') or '—'}\n"
                    f"👨‍⚕️ الدكتور: {session.get('doctor') or '—'}\n"
                    f"🗂 النوع: {ctype_label(ctype)}\n\n"
                    f"أرسل الملفات واحداً تلو الآخر ثم اضغط '✅ انتهيت من الرفع'",
                    reply_markup=get_upload_finish_keyboard()
                )
                return {"ok": True}

            # المستخدم: عرض الملفات
            state = USER_STATE.get(chat_id, {})
            semester = state.get("semester")
            course   = state.get("course")
            section  = state.get("section", "")
            doctor   = state.get("doctor", "")

            if not semester or not course:
                send_message(chat_id, "⚠️ يرجى اختيار السمستر والمقرر أولاً")
                return {"ok": True}

            mats = crud.get_materials(semester, course, ctype,
                                      section=section, doctor=doctor, use_cache=True)
            if not mats:
                send_message(chat_id,
                    f"🚧 لا توجد ملفات متاحة حالياً\n"
                    f"المقرر: {course} | القسم: {section or '—'} | الدكتور: {doctor or '—'}")
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
