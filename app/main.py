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

# [تعديل 2] فصل معرف المطور عن الأدمنز
# معرف المطور يظهر في زر "تواصل مع المطور" - ثابت في الكود
DEVELOPER_USERNAME = "@Mgdad_ali"

# قائمة الأدمنز من متغير البيئة CC - تقبل أكثر من معرف مفصول بفاصلة
# مثال: ADMIN_USERNAMES=Mgdad_ali,admin2,admin3
_raw_admins = os.getenv("ADMIN_USERNAMES", "Mgdad_ali")
ADMIN_USERNAMES = {u.strip().lstrip("@") for u in _raw_admins.split(",") if u.strip()}

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Med Faculty Bot")

@app.on_event("startup")
async def startup():
    crud.init_db()
    logger.info("✅ Database initialized successfully.")

# ========= إدارة رفع الملفات المتعددة للأدمن =========
UPLOAD_SESSION = {}  # keyed by chat_id -> {"semester":..., "course":..., "type":..., "files": [file_id1, file_id2, ...]}

# ========= حالة المستخدم لاختيار السمستر والمقرر والنوع =========
USER_STATE = {}  # keyed by chat_id -> {"semester": ..., "course": ..., "type": ...}

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

# [تعديل 2] دالة التحقق من الأدمن تعتمد على ADMIN_USERNAMES
def is_admin(user):
    return user.get("username") in ADMIN_USERNAMES

# ========= القوائم =========
def get_main_keyboard(is_admin=False):
    buttons = [[{"text": "ابدأ 🎓"}], [{"text": "تواصل مع المطور 👨‍💻"}]]
    if is_admin:
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
    # تحديد المقررات حسب كل سمستر
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
    course_buttons.append([{"text": "⬅️ رجوع"}, {"text": "🏠 القائمة الرئيسية"}])
    
    return {"keyboard": course_buttons, "resize_keyboard": True}

# [تعديل 3] إضافة فئة "تسجيلات" لنوع المحتوى
def get_types_keyboard(course):
    return {
        "keyboard": [
            [{"text": f"{course} 📄 PDF"}, {"text": f"{course} 🎥 فيديو"}],
            [{"text": f"{course} 📚 مرجع"}, {"text": f"{course} 🎙️ تسجيلات"}],
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

        # التقاط الملفات
        file_info = None
        content_type = None
        if "document" in msg:
            # الملفات المرسلة كمستند (PDF, MP3, OGG, إلخ)
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
            # ملفات صوتية مرسلة كـ audio (MP3, M4A, إلخ)
            file_info = msg["audio"]
            content_type = "recording"
        elif "voice" in msg:
            # رسائل صوتية مسجلة داخل تيليجرام
            file_info = msg["voice"]
            content_type = "recording"

        # ===== استقبال الملفات من الأدمن أثناء جلسة رفع نشطة =====
        if file_info and is_admin(user) and chat_id in UPLOAD_SESSION:
            session = UPLOAD_SESSION[chat_id]
            file_id = file_info.get("file_id")
            
            # تأكد من أن النوع متطابق
            if session.get("type") == content_type:
                session["files"].append(file_id)
                files_count = len(session["files"])
                send_message(
                    chat_id, 
                    f"✅ تم استلام الملف #{files_count}\n\n"
                    f"📊 إجمالي الملفات المستلمة: {files_count}\n\n"
                    f"يمكنك إرسال المزيد أو اضغط '✅ انتهيت من الرفع' للحفظ.",
                    reply_markup=get_upload_finish_keyboard()
                )
            else:
                send_message(chat_id, f"⚠️ نوع الملف غير متطابق! اخترت {session.get('type')} ولكن أرسلت {content_type}")
            
            return {"ok": True}

        # ===== زر "انتهيت من الرفع" - حفظ كل الملفات =====
        if text == "✅ انتهيت من الرفع" and is_admin(user) and chat_id in UPLOAD_SESSION:
            session = UPLOAD_SESSION[chat_id]
            semester = session.get("semester")
            course = session.get("course")
            ctype = session.get("type")
            files = session.get("files", [])
            
            if not files:
                send_message(chat_id, "⚠️ لم يتم رفع أي ملفات! أرسل الملفات أولاً.")
                return {"ok": True}
            
            # حفظ كل الملفات في قاعدة البيانات
            saved_count = 0
            for file_id in files:
                try:
                    crud.add_material(semester, course, ctype, file_id)
                    saved_count += 1
                except Exception as e:
                    logger.exception(f"Failed to save file {file_id}: {e}")
            
            # مسح الجلسة
            UPLOAD_SESSION.pop(chat_id, None)
            
            # رسالة تأكيد
            send_message(
                chat_id,
                f"✅ تم حفظ {saved_count} ملف بنجاح!\n\n"
                f"📚 السمستر: {semester}\n"
                f"📖 المقرر: {course}\n"
                f"📂 النوع: {ctype}",
                reply_markup=get_main_keyboard(is_admin=True)
            )
            return {"ok": True}

        # ===== زر "إلغاء العملية" =====
        if text == "❌ إلغاء العملية" and is_admin(user) and chat_id in UPLOAD_SESSION:
            UPLOAD_SESSION.pop(chat_id, None)
            send_message(chat_id, "❌ تم إلغاء عملية الرفع.", reply_markup=get_main_keyboard(is_admin=True))
            return {"ok": True}

        # ===== أوامر الأدمن =====
        if text == "رفع ملف جديد 📤" and is_admin(user):
            # بدء جلسة رفع جديدة
            UPLOAD_SESSION[chat_id] = {"semester": None, "course": None, "type": None, "files": []}
            send_message(chat_id, "📤 اختر السمستر الذي تريد رفع الملفات له:", reply_markup=get_semesters_keyboard())
            return {"ok": True}

        if text and text.startswith("/addfile") and is_admin(user):
            parts = text.split()
            if len(parts) == 5:
                semester, course, ctype, file_id = parts[1], parts[2], parts[3], parts[4]
                crud.add_material(semester, course, ctype, file_id)
                send_message(chat_id, f"✅ تمت إضافة {ctype} لمادة {course} (سمستر {semester}) بنجاح!")
            else:
                send_message(chat_id, "❌ الصيغة الصحيحة:\n/addfile <semester> <course> <type> <file_id>")
            return {"ok": True}

        # ===== أوامر المستخدم =====
        if text == "/start":
            USER_STATE.pop(chat_id, None)
            UPLOAD_SESSION.pop(chat_id, None)
            welcome_text = (
                "👋 مرحبًا بك في بوت كلية الطب – جامعة المناقل\n\n"
                "📚 هذا البوت يساعدك للوصول إلى محتوى المقررات بسهولة.\n"
             
            )
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin(user)))
            return {"ok": True}

        # [تعديل 2] زر "تواصل مع المطور" يعرض DEVELOPER_USERNAME الثابت دائماً
        if text == "تواصل مع المطور 👨‍💻":
            send_message(chat_id, f"📩 تواصل مع المطور: {DEVELOPER_USERNAME}")
            return {"ok": True}

        if text == "🏠 القائمة الرئيسية":
            USER_STATE.pop(chat_id, None)
            UPLOAD_SESSION.pop(chat_id, None)
            send_message(chat_id, "🏠 عدت إلى القائمة الرئيسية", reply_markup=get_main_keyboard(is_admin(user)))
            return {"ok": True}

        if text == "ابدأ 🎓":
            USER_STATE.pop(chat_id, None)
            send_message(chat_id, "📚 اختر الفصل الدراسي:", reply_markup=get_semesters_keyboard())
            return {"ok": True}

        if text == "⬅️ رجوع":
            state = USER_STATE.get(chat_id, {})
            
            # إذا كان عند اختيار النوع، نرجع لاختيار المقرر
            if state.get("course") and state.get("semester"):
                state.pop("type", None)
                state.pop("course", None)
                send_message(chat_id, f"⬅️ اختر المقرر:", reply_markup=get_courses_keyboard(state.get("semester")))
                return {"ok": True}
            
            # إذا كان عند اختيار المقرر، نرجع لاختيار السمستر
            if state.get("semester"):
                USER_STATE.pop(chat_id, None)
                send_message(chat_id, "⬅️ اختر الفصل الدراسي:", reply_markup=get_semesters_keyboard())
                return {"ok": True}
            
            # افتراضي: رجوع للسمسترات
            send_message(chat_id, "⬅️ اختر الفصل الدراسي:", reply_markup=get_semesters_keyboard())
            return {"ok": True}

        # ===== اختيار السمستر =====
        semester_map = {
            "الفصل الأول": "1",
"الفصل الثاني": "2",
"الفصل الثالث": "3",
"الفصل الرابع": "4",
"الفصل الخامس": "5",
"الفصل السادس": "6",
"الفصل السابع": "7",
"الفصل الثامن": "8",
"الفصل التاسع": "9",
"الفصل العاشر": "10"
        }
        
        if text in semester_map:
            semester = semester_map[text]
            
            # للأدمن في جلسة رفع: حفظ السمستر
            if is_admin(user) and chat_id in UPLOAD_SESSION:
                UPLOAD_SESSION[chat_id]["semester"] = semester
                send_message(chat_id, f"✅ تم اختيار {text}. الآن اختر المقرر:", reply_markup=get_courses_keyboard(semester))
                return {"ok": True}
            
            # للمستخدم العادي: حفظ في USER_STATE
            USER_STATE[chat_id] = {"semester": semester}
            send_message(chat_id, f"📖 اختر المقرر من {text}:", reply_markup=get_courses_keyboard(semester))
            return {"ok": True}

        # ===== اختيار المقرر =====
        # [تعديل 1] مزامنة الأسماء مع get_courses_keyboard بالضبط
        course_names = [
            # السمستر الأول
            "Introduction", "Biochemistry 1", "Parasitology", "Histology",
            "Physiology", "Medical Physics", "Islamyia",
            # السمستر الثاني
            "Nutrition", "Genetics", "Embryology", "Computer",
            "Statistics", "Ethics",
            # السمستر الثالث
            "Community", "Pathology", "Musculoskeletal System", "Sudanese Studies",
            # السمستر الرابع
            "Primary Health Care 1", "Hematology", "Basic Skills",
            "Cardiopulmonary 1", "The Rural",
            # السمستر الخامس
            "Primary Health Care 2", "Cardiopulmonary 2",
            "Pharmacology", "Endocrinology",
            # السمستر السادس
            "Family Medicine", "Gastrointestinal Tract 1",
            "Gastrointestinal Tract 2", "Endemic Diseases", "The Rural 2",
            # السمستر السابع
            "Genito-urinary System", "Central Nervous System", "Forensic Medicine",
            # السمستر الثامن
            "Clerkship in medicine", "Dermatology",
            "Clerkship in Mental Health", "Rural Residency",
            # السمستر التاسع
            "Obstetrics and Gynecology", "Pediatrics",
            # السمستر العاشر
            "Surgery", "Ophthalmology", "ENT", "Emergency medicine",
            "Clerkship in Primary Health Care",
            # مشترك بين سمسترات متعددة
            "English", "Arabic",
        ]

        if text in course_names:
            # للأدمن في جلسة رفع: حفظ المقرر
            if is_admin(user) and chat_id in UPLOAD_SESSION:
                UPLOAD_SESSION[chat_id]["course"] = text
                send_message(chat_id, f"📂 اختر نوع المحتوى لمقرر {text}:", reply_markup=get_types_keyboard(text))
                return {"ok": True}
            
            # للمستخدم: حفظ المقرر
            state = USER_STATE.get(chat_id, {})
            if not state.get("semester"):
                send_message(chat_id, "⚠️ يرجى اختيار السمستر أولاً")
                return {"ok": True}
            
            state["course"] = text
            USER_STATE[chat_id] = state
            send_message(chat_id, f"📂 اختر نوع المحتوى لمقرر {text}:", reply_markup=get_types_keyboard(text))
            return {"ok": True}

        # ===== اختيار نوع الملف =====
        # [تعديل 3] إضافة "تسجيلات" للكشف والتحويل
        if text and any(x in text for x in ["PDF", "فيديو", "مرجع", "تسجيلات"]):
            course_name = text.split()[0]
            if "PDF" in text:
                ctype = "pdf"
            elif "فيديو" in text:
                ctype = "video"
            elif "تسجيلات" in text:
                ctype = "recording"
            else:
                ctype = "reference"

            # للأدمن في جلسة رفع: حفظ النوع وانتظار الملفات
            if is_admin(user) and chat_id in UPLOAD_SESSION:
                session = UPLOAD_SESSION[chat_id]
                semester = session.get("semester")
                course = session.get("course") or course_name

                if not semester or not course:
                    send_message(chat_id, "❌ بيانات غير مكتملة. أعد العملية.")
                    return {"ok": True}

                session["type"] = ctype
                
                # [تعديل 3] تسمية الأنواع بالعربي للرسائل
                file_type_text = (
                    "PDF" if ctype == "pdf"
                    else "فيديو" if ctype == "video"
                    else "تسجيلات" if ctype == "recording"
                    else "مرجع"
                )
                send_message(
                    chat_id,
                    f"✅ تم اختيار: {file_type_text}\n\n"
                    f"📚 السمستر: {semester}\n"
                    f"📖 المقرر: {course}\n"
                    f"📂 النوع: {file_type_text}\n\n"
                    f"الآن أرسل الملفات ({file_type_text}) واحداً تلو الآخر.\n"
                    f"عند الانتهاء اضغط '✅ انتهيت من الرفع'",
                    reply_markup=get_upload_finish_keyboard()
                )
                return {"ok": True}

            # للمستخدم: عرض الملفات مباشرة
            state = USER_STATE.get(chat_id, {})
            semester = state.get("semester")
            course = state.get("course")
            
            if not semester or not course:
                send_message(chat_id, "⚠️ يرجى اختيار السمستر والمقرر أولاً")
                return {"ok": True}

            # جلب الملفات من قاعدة البيانات
            mats = crud.get_materials(semester, course, ctype, use_cache=True)
            
            if not mats:
                send_message(chat_id, f"🚧 لا توجد ملفات متاحة حالياً لـ {course} ({ctype})")
                return {"ok": True}
            
            send_message(chat_id, f"📤 جاري إرسال ملفات {course} ({ctype})...")
            for m in mats:
                send_file(chat_id, m.get("file_id"), content_type=ctype)
            
            return {"ok": True}

        # افتراضي
        send_message(chat_id, "🤔 لم أفهم الأمر، يرجى اختيار من القائمة.")
        return {"ok": True}

    except Exception as e:
        logger.exception(f"Exception in webhook processing: {e}")
        return {"ok": True}
