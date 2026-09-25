"""
موقع الخوارزمي — واجهة ويب كاملة مع تسجيل دخول وتبديل النماذج
التشغيل: python app.py  ثم افتح http://127.0.0.1:5000
"""

import io
import json
import os
import random
import re
import sys
import threading
import urllib.parse
import urllib.request
from functools import wraps

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)
from openai import OpenAI, OpenAIError
from werkzeug.security import check_password_hash, generate_password_hash

# إعدادات البوت المشتركة (الشخصية، المزوّد)
from chatbot import PROVIDER, SYSTEM_PROMPT, create_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")

# تحميل متغيرات البيئة من ملف .env (بالمسار الكامل — مهم على الاستضافات مثل PythonAnywhere)
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or "khawarizmi-dev-secret"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

create_client()  # تحقق من وجود مفتاح Gemini عند بدء التشغيل


# ===== النماذج المتاحة (تتفعّل تلقائياً حسب المفاتيح) =====
MODELS = {
    "gemini-2.5-flash": {
        "label": "Gemini 2.5 Flash",
        "desc": "الأذكى — من جوجل (مجاني)",
        "provider": "gemini",
        "id": "gemini-2.5-flash",
    },
    "gemini-2.5-flash-lite": {
        "label": "Gemini 2.5 Flash-Lite",
        "desc": "الأسرع — من جوجل (مجاني)",
        "provider": "gemini",
        "id": "gemini-2.5-flash-lite",
    },
    "image-flux": {
        "label": "توليد صورة (FLUX.1)",
        "desc": "ولّد صوراً بأي وصف — نموذج مفتوح المصدر",
        "provider": "image",
        "id": "flux",
        "kind": "image",
        "icon": "image",
    },
}

# نموذجنا الحصري "Al-Khwarizmi Flash" — سريع وخفيف، يُقدَّم تحت اسمنا الخاص لتمييز الموقع
if os.getenv("OPENROUTER_API_KEY"):
    MODELS = {
        "khwarizmi-flash": {
            "label": "Al-Khwarizmi Flash",
            "desc": "نموذجنا الخاص — سريع وخفيف، مدرب لخدمتك",
            "provider": "openrouter",
            "id": "nex-agi/nex-n2.5-mini:free",
            "icon": "bolt",
        },
        **MODELS,
    }

# نماذج مفتوحة المصدر عبر Groq — تظهر إذا انحط مفتاح GROQ_API_KEY في .env
if os.getenv("GROQ_API_KEY"):
    MODELS.update({
        "groq-gpt-oss-120b": {
            "label": "GPT-OSS 120B",
            "desc": "مفتوح المصدر — من OpenAI (عبر Groq)",
            "provider": "groq",
            "id": "openai/gpt-oss-120b",
        },
        "groq-gpt-oss-20b": {
            "label": "GPT-OSS 20B",
            "desc": "مفتوح المصدر — أسرع وأخف (عبر Groq)",
            "provider": "groq",
            "id": "openai/gpt-oss-20b",
        },
        "groq-qwen3": {
            "label": "Qwen 3.8 27B",
            "desc": "مفتوح المصدر — من علي بابا (عبر Groq)",
            "provider": "groq",
            "id": "qwen/qwen3.8-27b",
        },
    })

# نماذج مفتوحة المصدر عبر OpenRouter — تظهر إذا انحط مفتاح OPENROUTER_API_KEY في .env
if os.getenv("OPENROUTER_API_KEY"):
    MODELS.update({
        "or-glm-5.2": {
            "label": "GLM-5.2",
            "desc": "مفتوح المصدر — من Zhipu (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "z-ai/glm-5.2:free",
        },
        "or-nemotron-ultra": {
            "label": "Nemotron 3 Ultra 550B",
            "desc": "مفتوح المصدر — من NVIDIA (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        },
        "or-gemma-4": {
            "label": "Gemma 4 31B",
            "desc": "مفتوح المصدر — من جوجل (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "google/gemma-4-31b-it:free",
        },
        "or-qwen-3.8": {
            "label": "Qwen 3.8 27B",
            "desc": "مفتوح المصدر — من علي بابا (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "qwen/qwen3.8-27b:free",
        },
        "or-north-code": {
            "label": "North Mini Code",
            "desc": "مفتوح المصدر — للبرمجة من Cohere (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "cohere/north-mini-code:free",
        },
        "or-liquid-mini": {
            "label": "LFM 2.5 2.6B",
            "desc": "مفتوح المصدر — خفيف وسريع من Liquid (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "liquid/lfm-2.5-2.6b:free",
        },
        "or-ling-fin": {
            "label": "Ling 3.0 Flash (مالية)",
            "desc": "مفتوح المصدر — متخصص مالي من InclusionAI (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "inclusionai/ling-3.0-flash-fin:free",
        },
        "or-ling-sante": {
            "label": "Ling 3.0 Flash (صحة)",
            "desc": "مفتوح المصدر — متخصص صحي من InclusionAI (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "inclusionai/ling-3.0-flash-sante:free",
        },
        "or-nex-pro": {
            "label": "Nex N2.5 Pro",
            "desc": "مفتوح المصدر — النسخة الأقوى من فلاشنا (عبر OpenRouter)",
            "provider": "openrouter",
            "id": "nex-agi/nex-n2.5-pro:free",
        },
    })

# ===== عملاء المزوّدين (يُبنى العميل عند أول استخدام) =====
PROVIDER_CONFIGS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "timeout": 30,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "timeout": 30,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "timeout": 30,
    },
}

_clients: dict = {}


def get_client(provider: str) -> OpenAI:
    """إرجاع عميل المزوّد (يُنشأ مرة واحدة ويُخزن)"""
    if provider not in _clients:
        cfg = PROVIDER_CONFIGS[provider]
        key = os.getenv(cfg["key_env"])
        _clients[provider] = OpenAI(
            api_key=key,
            base_url=cfg["base_url"],
            timeout=cfg["timeout"],
            max_retries=1,
        )
    return _clients[provider]


MAX_HISTORY = 40      # أقصى عدد رسائل محفوظة من المتصفح
MAX_MSG_LEN = 4000    # أقصى طول للرسالة الواحدة


# ===== إدارة المستخدمين =====
# قفل للكتابة المتزامنة: موقع عام = عدة مستخدمين يسجّلون بنفس اللحظة،
# وهذا يمنع تلف ملف users.json
_USERS_LOCK = threading.Lock()


def load_users() -> dict:
    """قراءة ملف المستخدمين (كلمات المرور مخزنة مشفّرة)"""
    with _USERS_LOCK:
        if not os.path.exists(USERS_FILE):
            return {}
        try:
            with open(USERS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}


def save_users(users: dict) -> None:
    """حفظ آمن: نكتب لملف مؤقت ثم نستبدل الملف الأصلي (لا يخرب لو انقطع التيار)"""
    with _USERS_LOCK:
        tmp = USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        os.replace(tmp, USERS_FILE)


def current_user() -> dict | None:
    email = session.get("email")
    if not email:
        return None
    return load_users().get(email)


def login_required(view):
    """حماية الصفحات والـ API — غير المسجّل يُحوَّل لصفحة الدخول"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("email"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "انتهت الجلسة، سجّل دخولك من جديد"}), 401
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)
    return wrapped


# ===== صفحات الموقع =====
@app.route("/login")
def login_page():
    if session.get("email"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/")
@login_required
def index():
    user = current_user() or {}
    return render_template(
        "index.html",
        provider=PROVIDER,
        email=session.get("email", ""),
        name=user.get("name") or session.get("email", ""),
    )


# ===== تسجيل الدخول / حساب جديد / خروج =====
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if "@" not in email or "." not in email:
        return jsonify({"error": "البريد الإلكتروني غير صالح"}), 400
    if len(password) < 6:
        return jsonify({"error": "كلمة المرور لازم تكون 6 أحرف على الأقل"}), 400

    users = load_users()
    if email in users:
        return jsonify({"error": "هذا البريد مسجّل من قبل — جرّب تسجيل الدخول"}), 409

    users[email] = {
        "name": name or email.split("@")[0],
        "hash": generate_password_hash(password),
    }
    save_users(users)
    session["email"] = email
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = load_users().get(email)
    if not user or not check_password_hash(user["hash"], password):
        return jsonify({"error": "البريد الإلكتروني أو كلمة المرور غير صحيحة"}), 401

    session["email"] = email
    return jsonify({"ok": True})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# ===== المحادثة =====
@app.route("/api/models")
@login_required
def api_models():
    return jsonify([
        {"id": mid, "label": e["label"], "desc": e["desc"], "kind": e.get("kind", "chat"),
         "icon": e.get("icon")}
        for mid, e in MODELS.items()
    ])


def web_search(query: str, limit: int = 4):
    """بحث في ويكيبيديا (عربي/إنجليزي) — مجاني بدون مفتاح، يعيد نتائج للوضع Agent"""
    results = []
    # حاول العربية أولاً، ثم الإنجليزية
    for lang in ("ar", "en"):
        try:
            q = urllib.parse.quote(query[:200])
            url = (
                f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
                f"&srsearch={q}&format=json&utf8=1&srlimit={limit}"
                f"&srprop=snippet"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "KhawarizmiBot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
            for item in data.get("query", {}).get("search", []):
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                snippet = snippet.replace('<span class="searchmatch">', "").replace("</span>", "")
                page_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                results.append({
                    "title": title[:150],
                    "snippet": snippet[:400],
                    "url": page_url,
                })
            if results:
                break  # نجحت العربية — توقف
        except Exception:
            continue
    return results[:limit]


def _extract_last_user(messages: list) -> str:
    """أخذ آخر رسالة مستخدم من السجل"""
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


# امتدادات الملفات حسب اللغة — لتسمية القطع البرمجية
_EXT_MAP = {
    "python": "py", "javascript": "js", "typescript": "ts", "html": "html",
    "html+css": "html", "css": "css", "json": "json", "bash": "sh",
    "sql": "sql", "cpp": "cpp", "java": "java", "rust": "rs", "go": "go",
    "ruby": "rb", "php": "php", "swift": "swift", "kotlin": "kt",
    "scala": "scala", "dart": "dart", "perl": "pl", "r": "r",
    "markdown": "md", "text": "txt",
}


def extract_artifacts(reply: str) -> list[dict]:
    """استخراج مقاطع الكود من الرد كقطع منفصلة (Artifacts) للمعاينة"""
    artifacts = []
    pattern = re.compile(r"```(\w[\w+#-]*)(?:\s*:\s*([^\n]+))?\n([\s\S]*?)```")
    pos = 0
    for m in pattern.finditer(reply or ""):
        lang = m.group(1).strip() or "text"
        name = (m.group(2) or "").strip()
        code = m.group(3).strip("\n")
        if not code.strip():
            continue
        ext = _EXT_MAP.get(lang.lower(), lang.lower() or "txt")
        if not name:
            name = f"file.{ext}"
        artifacts.append({"name": name, "lang": lang, "code": code})
        pos = m.end()
    # مقاطع غير مكتملة (بدون إغلاق ``` بسبب حد الطول) — استخرجها حتى نهاية الرد
    tail = (reply or "")[pos:] if pos else (reply or "")
    um = re.search(r"```(\w[\w+#-]*)(?:\s*:\s*([^\n]+))?\n([\s\S]*)$", tail)
    if um:
        lang = um.group(1).strip() or "text"
        name = (um.group(2) or "").strip()
        code = um.group(3).strip("\n")
        if code.strip():
            ext = _EXT_MAP.get(lang.lower(), lang.lower() or "txt")
            if not name:
                name = f"file.{ext}"
            artifacts.append({"name": name, "lang": lang, "code": code})
    return artifacts


@app.route("/api/chat", methods=["POST"])
@login_required
def chat_api():
    data = request.get_json(force=True, silent=True) or {}
    history = data.get("messages", [])
    requested = data.get("model")
    mode = (data.get("mode") or "chat").lower()          # chat | agent
    temperature = float(data.get("temperature", 0.7))
    temperature = max(0.0, min(1.5, temperature))
    max_tokens = int(data.get("max_tokens", 0) or 0)

    # بناء سجل المحادثة: شخصية البوت + الرسائل المُنقّاة
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history[-MAX_HISTORY:]:
        role, content = m.get("role"), m.get("content", "")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content[:MAX_MSG_LEN]})

    if len(messages) == 1:
        return jsonify({"error": "الرسالة فارغة"}), 400

    # إذا النموذج المختار لتوليد الصور: حول آخر رسالة لصورة
    req_entry = MODELS.get(requested)
    if req_entry and req_entry.get("kind") == "image":
        prompt = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                prompt = m.get("content", "")
                break
        for prefix in ("/image", "/img", "صورة:", "ارسم:", "توليد صورة:"):
            if prompt.startswith(prefix):
                prompt = prompt[len(prefix):].strip()
        if not prompt:
            return jsonify({"error": "اكتب وصف الصورة التي تريد توليدها"}), 400
        return jsonify(build_image_payload(prompt, req_entry["id"]))

    # === وضع Agent: بحث في الإنترنت + تنفيذ المهام (برمجة/بناء) ===
    sources = []
    if mode == "agent":
        query = _extract_last_user(messages)
        # إزالة أوامر الصور من الاستعلام
        for prefix in ("/image", "/img", "صورة:", "ارسم:"):
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
        if query:
            sources = web_search(query)
            context_parts = []
            if sources:
                context_parts.append(
                    "نتائج بحث من ويكيبيديا (قد تكون حديثة أو جزئية):\n"
                    + "\n".join(
                        f"- {s['title']}: {s['snippet']} ({s['url']})"
                        for s in sources
                    )
                    + "\nاستخدمها لتحسين إجابتك واذكر المصادر بصيغة: (المصدر: العنوان). لا تختلق إن لم تكن مفيدة."
                )
            # وضع مهمة بناء/برمجة — أعطِ النموذج قواعد إخراج مقاطع كود منظمة
            wants_build = any(k in query.lower() for k in (
                "ابن", "اصنع", "صمم", "اكتب لي", "برمج", "برمجة", "إنشئ", "انشئ",
                "موقع", "صفحة", "تطبيق", "أداة", "اداة", "game", "build", "make",
                "create", "write code", "website", "app", "html", "css", "js",
            ))
            if wants_build:
                context_parts.append(
                    "طلب المستخدم بناء شيء أو كتابة كود. أجب بصيغة مقاطع كود منفصلة: "
                    "كل ملف داخل صندوق ```لغة:اسم-الملف (مثال: ```html:index.html ثم الكود ثم ```). "
                    "للموقع: ملف index.html يحتوي كل شيء، مع CSS داخلي. اكتب الكود كاملاً يعمل فوراً."
                )
            if context_parts:
                messages.append({
                    "role": "system",
                    "content": "الوضع: وكيل تنفيذ (Agent). " + " ".join(context_parts),
                })

    # ترتيب المحاولات: النموذج المطلوب أولاً، ثم باقي نماذج السحابة كاحتياط
    ordered = []
    if requested in MODELS:
        ordered.append((requested, MODELS[requested]))
    for mid, e in MODELS.items():
        if mid != requested and e.get("kind", "chat") == "chat":
            ordered.append((mid, e))

    # صندوق الأوامر الختامية لنموذج الاستدعاء
    last_error = None
    for mid, entry in ordered[:5]:
        try:
            c = get_client(entry["provider"])
            kwargs = {
                "model": entry["id"],
                "messages": messages,
                "temperature": temperature,
            }
            # طلبات البناء تحتاج ردوداً أطول لكي يكتمل الكود
            eff_max = max_tokens
            if mode == "agent" and max_tokens <= 0:
                eff_max = 2000
            if eff_max > 0:
                kwargs["max_tokens"] = min(eff_max, 8000)
            r = c.chat.completions.create(**kwargs)
            reply = r.choices[0].message.content or ""
            artifacts = extract_artifacts(reply) if mode == "agent" else []
            return jsonify({
                "reply": reply,
                "model": mid,
                "label": entry["label"],
                "sources": sources,
                "artifacts": artifacts,
            })
        except OpenAIError as e:
            last_error = e
            status = getattr(e, "status_code", None)
            # 429 = تجاوز الحد، 404 = نموذج غير موجود، 503 = ضغط، None = خطأ اتصال
            if status in (429, 404, 503) or status is None:
                continue
            break

    print(f"خطأ API: {last_error}")
    return jsonify({"error": "الخدمة مشغولة حالياً — جرّب مرة ثانية بعد دقيقة"}), 503


# ===== توليد الصور عبر FLUX.1 (Pollinations) — مجاني بالكامل بدون أي مفتاح =====
IMAGE_MODELS = {
    "flux": {
        "label": "FLUX.1 Schnell",
        "desc": "المفتوح الأشهر — أعلى دقة وواقعية (مجاني)",
        "api": "flux",
    },
}

# مجلد حفظ الصور المولّدة محلياً (تشوفها بالمتصفح من /static/generated/)
GENERATED_DIR = os.path.join(BASE_DIR, "static", "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)


def _pollinations_url(english_prompt: str, img_model: str, seed: int) -> str:
    """بناء رابط توليد الصورة من Pollinations (مجاني — بدون مفتاح)"""
    encoded = urllib.parse.quote(english_prompt)
    return (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?model={img_model}&width=1024&height=1024&seed={seed}&nologo=true"
    )


def strip_watermark(data: bytes) -> bytes:
    """قص الشريط السفلي من الصورة (يحوي علامة pollinations المائية)"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        cropped = img.crop((0, 0, w, int(h * 0.86)))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception as e:
        print(f"تعذر قص العلامة المائية: {e}")
        return data


def enhance_image_prompt(prompt: str) -> str:
    """تحسين وصف الصورة وترجمته للإنجليزية للحصول على أفضل دقة من FLUX"""
    # إذا النص أغلبه إنجليزي استخدمه مباشرة
    has_arabic = any("\u0600" <= ch <= "\u06ff" for ch in prompt)
    if not has_arabic:
        return prompt.strip()

    # استخدام نموذج سريع لتحويل الطلب العربي لوصف احترافي لـ FLUX
    providers_to_try = [
        ("groq", "qwen/qwen3.8-27b"),
        ("gemini", "gemini-2.5-flash-lite"),
    ]
    for prov, m_id in providers_to_try:
        try:
            c = get_client(prov)
            # مهلة قصيرة (8 ثوانٍ) — الترجمة مهمة صغيرة ما لازم توقف الصورة
            res = c.with_options(timeout=8, max_retries=0).chat.completions.create(
                model=m_id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert AI prompt engineer for image generation models like FLUX.1. "
                            "Convert the user's Arabic idea into a rich, detailed, high quality English prompt. "
                            "Add photographic/artistic style details, lighting, and composition. "
                            "Output ONLY the final English prompt, no explanations, no quotes."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=100,
                temperature=0.3,
            )
            enhanced = (res.choices[0].message.content or "").strip()
            if enhanced and len(enhanced) > 5:
                return enhanced
        except Exception:
            continue
    return prompt.strip()


def build_image_payload(prompt: str, img_model: str = "flux") -> dict:
    """بناء رد توليد الصورة — يحمّلها لسيرفرنا ويزيل العلامة المائية"""
    if img_model not in IMAGE_MODELS:
        img_model = "flux"
    seed = random.randint(1000, 9999999)
    english_prompt = enhance_image_prompt(prompt)
    url = _pollinations_url(english_prompt, img_model, seed)

    image_url = url  # احتياطي: الرابط المباشر إذا فشل التحميل
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=50) as resp:
            data = resp.read()
        # قص شريط العلامة المائية تلقائياً (النسخة المجانية تضيفها)
        data = strip_watermark(data)
        fname = f"img_{seed}_{random.randint(1000, 9999)}.jpg"
        with open(os.path.join(GENERATED_DIR, fname), "wb") as f:
            f.write(data)
        image_url = f"/static/generated/{fname}"
    except Exception as e:
        print(f"تحميل الصورة فشل، استخدام الرابط المباشر: {e}")

    return {
        "image_url": image_url,
        "enhanced_prompt": english_prompt,
        "original_prompt": prompt,
        "model_label": IMAGE_MODELS[img_model]["label"],
    }


@app.route("/api/generate-image", methods=["POST"])
@login_required
def api_generate_image():
    data = request.get_json(force=True, silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip()
    img_model = data.get("model") or "flux"

    if not user_prompt:
        return jsonify({"error": "يرجى كتابة وصف للصورة المراد توليدها"}), 400

    return jsonify(build_image_payload(user_prompt, img_model))


if __name__ == "__main__":
    print("=" * 50)
    print("موقع الخوارزمي شغّال!")
    print("   افتح المتصفح على: http://127.0.0.1:5000")
    print("   للإيقاف: Ctrl+C")
    print("=" * 50)
    try:
        # خادم إنتاجي حقيقي (يدعم عدة مستخدمين بالتوازي) — أفضل للنشر
        from waitress import serve
        serve(app, host="127.0.0.1", port=5000)
    except ImportError:
        # احتياطي: خادم Flask التطويري (لو waitress غير مثبّت)
        app.run(host="127.0.0.1", port=5000, debug=False)

