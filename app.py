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
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
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
        "desc": "الأذكى والأدق — متعدد اللغات",
        "provider": "gemini",
        "id": "gemini-2.5-flash",
        "vision": True,
    },
    "gemini-2.5-flash-lite": {
        "label": "Gemini 2.5 Flash-Lite",
        "desc": "الأسرع — خفيف وسريع الاستجابة",
        "provider": "gemini",
        "id": "gemini-2.5-flash-lite",
        "vision": True,
    },
    "image-flux": {
        "label": "توليد صورة (FLUX.1)",
        "desc": "ولّد صوراً بأي وصف إبداعي",
        "provider": "image",
        "id": "flux",
        "kind": "image",
        "icon": "image",
    },
}

# ═══════ OpenRouter ═══════

# نماذج مفتوحة المصدر عبر Groq — تظهر إذا انحط مفتاح GROQ_API_KEY في .env
if os.getenv("GROQ_API_KEY"):
    MODELS.update({
        "groq-gpt-oss-120b": {
            "label": "GPT-OSS 120B",
            "desc": "أقوى نموذج متاح — برمجة واستنتاج متقدم",
            "provider": "groq",
            "id": "openai/gpt-oss-120b",
        },
        "al-khwarizmi": {
            "label": "Al-Khwarizmi Flash",
            "desc": "مطوّر بـ Light Co من فلسطين — سريع وخفيف",
            "provider": "groq",
            "id": "openai/gpt-oss-20b",
        },
        "groq-qwen3": {
            "label": "Qwen 3.8 27B",
            "desc": "قوي بالعربية والبرمجة",
            "provider": "groq",
            "id": "qwen/qwen3.8-27b",
        },
    })

# نماذج عبر Cerebras — تظهر إذا انحط مفتاح CEREBRAS_API_KEY في .env
# (أسرع مزوّد نصي بالعالم، حصته المجانية تعتمد على تفعيل الحساب)
if os.getenv("CEREBRAS_API_KEY"):
    MODELS.update({
        "cerebras-gpt-oss-120b": {
            "label": "GPT-OSS 120B",
            "desc": "الأسرع استجابة — قوي بالعموم",
            "provider": "cerebras",
            "id": "gpt-oss-120b",
        },
        "cerebras-qwen": {
            "label": "Qwen 3.8 27B",
            "desc": "سريع وخفيف — مثالي للمحادثة",
            "provider": "cerebras",
            "id": "qwen-3.8-27b",
        },
    })

# نماذج عبر NVIDIA NIM (build.nvidia.com) — تظهر إذا انحط مفتاح NVIDIA_API_KEY في .env
# مكتبة حرة غنية 80+ نموذجاً — فيها رؤية حقيقية عبر Llama Vision
if os.getenv("NVIDIA_API_KEY"):
    MODELS.update({
        "nvidia-gemma-4": {
            "label": "Gemma 4 31B",
            "desc": "قوي بالعربية — فهم عميق",
            "provider": "nvidia",
            "id": "google/gemma-4-31b-it",
        },
        "nvidia-llama-vision": {
            "label": "Llama 3.2 Vision 11B",
            "desc": "يقرأ الصور والوثائق بدقة",
            "provider": "nvidia",
            "id": "meta/llama-3.2-11b-vision-instruct",
            "vision": True,
        },
        "nvidia-llama-vision-90b": {
            "label": "Llama 3.2 Vision 90B",
            "desc": "يقرأ الصور — النسخة الأقوى",
            "provider": "nvidia",
            "id": "meta/llama-3.2-90b-vision-instruct",
            "vision": True,
        },
    })

# نموذجك الخاص "Al-Khwarizmi Local" — يعمل على جهازك أو كولاب عبر بوابة خاصة
# يظهر إذا ضبطت COLABC_URL (رابط النفق) و COLABC_KEY (المفتاح السري) في .env
if os.getenv("COLABC_URL") and os.getenv("COLABC_KEY"):
    MODELS.update({
        "khwarizmi-local": {
            "label": "Al-Khwarizmi Local",
            "desc": "نموذجك الخاص — يشتغل على جهازك/كولاب",
            "provider": "colab",
            "id": "khwarizmi",
            "icon": "bolt",
        },
    })

# ═══════════ مزوّدون إضافيون (يظهر كل واحد إذا ضعفت مفتاحه في .env) ═══════════
if os.getenv("MISTRAL_API_KEY"):
    MODELS.update({
        "mistral-small": {
            "label": "Mistral Small",
            "desc": "سريع وذكي — 128K سياق — قارئ صور",
            "provider": "mistral",
            "id": "mistral-small-latest",
            "vision": True,
        },
        "mistral-mixtral": {
            "label": "Mixtral 8x7B",
            "desc": "قوي بالعموم — متعدد المهام",
            "provider": "mistral",
            "id": "mistral.mixtral-8x7b-instruct-v0.1",
        },
    })
if os.getenv("TOGETHER_API_KEY"):
    MODELS.update({
        "al-khwarizmi-together": {
            "label": "Al-Khwarizmi (قوي)",
            "desc": "نموذج الموقع — قوي وسريع",
            "provider": "together",
            "id": "meta-llama/Llama-3.1-8B-Instruct",
        },
        "together-llama-3.1": {
            "label": "Llama 3.1 8B",
            "desc": "متعدد الاستخدامات — موثوق",
            "provider": "together",
            "id": "meta-llama/Llama-3.1-8B-Instruct",
        },
        "together-qwen-72b": {
            "label": "Qwen 2.5 72B",
            "desc": "قوي بالعربية والبرمجة",
            "provider": "together",
            "id": "Qwen/Qwen2.5-72B-Instruct",
        },
    })
if os.getenv("FIREWORKS_API_KEY"):
    MODELS.update({
        "fw-llama-3.1": {
            "label": "Llama 3.1",
            "desc": "سريع وخفيف — استجابة فورية",
            "provider": "fireworks",
            "id": "fireworks/firellama-3.1-11b-v0.2",
        },
        "fw-qwen-72b": {
            "label": "Qwen 2.5 72B",
            "desc": "قوي بالعربية والبرمجة",
            "provider": "fireworks",
            "id": "Qwen/Qwen2.5-72B-Instruct",
        },
    })

# ═══════ نماذج APInex (مجاني 100% — 1M token لكل الموديلات) ═══════
# التسجيل: apinex.bond + أدخل الكود TMKTL35G
# المفتاح: APINEX_API_KEY من لوحة المطورين
if os.getenv("APINEX_API_KEY"):
    MODELS.update({
        "apnx-glm-5.3-flash": {
            "label": "GLM-5.3 Flash",
            "desc": "قوي وسريع — تفكير متقدم",
            "provider": "apinex",
            "id": "free/glm-5.3-flash",
            "vision": True,
        },
        "apnx-dsv4-pro": {
            "label": "DeepSeek V4 Pro",
            "desc": "أقوى نسخة — استنتاج وتحليل عميق",
            "provider": "apinex",
            "id": "free/deepseek-v4-pro-0813",
            "vision": True,
        },
        "apnx-dsv4-flash": {
            "label": "DeepSeek V4 Flash",
            "desc": "سريع وذكي — خفيف على الجهاز",
            "provider": "apinex",
            "id": "free/deepseek-v4.1-flash",
        },
    })

# ═══════════ نماذج OpenRouter ═══════════
if os.getenv("OPENROUTER_API_KEY"):
    MODELS.update({
        "or-glm-5.2": {
            "label": "GLM-5.2",
            "desc": "سريع وذكي — متعدد اللغات",
            "provider": "openrouter",
            "id": "z-ai/glm-5.2:free",
            "vision": True,
        },
        "or-nemotron-ultra": {
            "label": "Nemotron 3 Ultra 550B",
            "desc": "أضخم نموذج متاح — استنتاج عميق",
            "provider": "openrouter",
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        },
        "or-gemma-4": {
            "label": "Gemma 4 31B",
            "desc": "قوي بالعربية — يقرأ الصور",
            "provider": "openrouter",
            "id": "google/gemma-4-31b-it:free",
            "vision": True,
        },
        "or-qwen-3.8": {
            "label": "Qwen 3.8 27B",
            "desc": "قوي بالعربية والبرمجة",
            "provider": "openrouter",
            "id": "qwen/qwen3.8-27b:free",
        },
        "or-north-code": {
            "label": "North Mini Code",
            "desc": "متخصص بالبرمجة والكود",
            "provider": "openrouter",
            "id": "cohere/north-mini-code:free",
        },
        "or-liquid-mini": {
            "label": "LFM 2.5 2.6B",
            "desc": "خفيف وسريع — استجابة لحظية",
            "provider": "openrouter",
            "id": "liquid/lfm-2.5-2.6b:free",
        },
        "or-ling-fin": {
            "label": "Ling 3.0 Flash (مالية)",
            "desc": "متخصص بالتحليل المالي",
            "provider": "openrouter",
            "id": "inclusionai/ling-3.0-flash-fin:free",
        },
        "or-ling-sante": {
            "label": "Ling 3.0 Flash (صحة)",
            "desc": "متخصص بالمجال الصحي",
            "provider": "openrouter",
            "id": "inclusionai/ling-3.0-flash-sante:free",
        },
        "or-nex-pro": {
            "label": "Nex N2.5 Pro",
            "desc": "النسخة الأقوى من عائلتنا — تفكير عميق",
            "provider": "openrouter",
            "id": "nex-agi/nex-n2.5-pro:free",
            "vision": True,
        },
    })

# ===== عملاء المزوّدين (يُبنى العميل عند أول استخدام) =====
PROVIDER_CONFIGS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "timeout": 10,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "timeout": 10,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "timeout": 10,
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "key_env": "CEREBRAS_API_KEY",
        "timeout": 10,
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
        "timeout": 10,
    },
    "colab": {
        "base_url": os.getenv("COLABC_URL", ""),   # رابط نفق Cloudflare من جهازك/كولاب
        "key_env": "COLABC_KEY",
        "timeout": 15,
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY",
        "timeout": 10,
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "key_env": "TOGETHER_API_KEY",
        "timeout": 10,
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "key_env": "FIREWORKS_API_KEY",
        "timeout": 10,
    },
    "apinex": {
        "base_url": "https://apinex.bond/v1",
        "key_env": "APINEX_API_KEY",
        "timeout": 10,
    },
}

_clients: dict = {}
_rot_count: dict = {}

# ذاكرة صحة المفاتيح: المفتاح الذي وصل حده (429) أو رُفض (401/403) يُجمَّد مؤقتاً
# حتى لا يُعاد تجربته مع كل طلب جديد فيضيع وقت الموقع على الردود المرفوضة.
_KEY_COOLDOWN: dict = {}   # (مزوّد, مفتاح) -> وقت انتهاء التجميد (ثواني منذ 1970)
KEY_COOLDOWN_SECONDS = 60  # مدة تجميد المفتاح بعد تجاوز حده


def _mark_key_down(provider: str, key, seconds: int = KEY_COOLDOWN_SECONDS) -> None:
    """منع استخدام مفتاح مؤقتاً بعد استنزافه أو فشله"""
    if key:
        _KEY_COOLDOWN[(provider, key)] = time.time() + seconds


def _key_is_down(provider: str, key) -> bool:
    """هل المفتاح مجمّد حالياً؟ (يُرفع التجميد تلقائياً بعد انتهاء مدته)"""
    until = _KEY_COOLDOWN.get((provider, key))
    if until is None:
        return False
    if time.time() < until:
        return True
    _KEY_COOLDOWN.pop((provider, key), None)  # انتهى التجميد
    return False


def _keys_of(provider: str) -> list:
    """كل مفاتيح مزوّد واحد: المفتاح الأساسي (قد يحوي عدة مفاتيح مفصولة بفواصل)
    بالإضافة إلى مفاتيح إضافية بالصيغة: GEMINI_API_KEY_2، GEMINI_API_KEY_3..."""
    cfg = PROVIDER_CONFIGS[provider]
    base = cfg["key_env"]
    raw = os.getenv(base, "").strip()
    keys = [k.strip() for k in re.split(r"[,;\s]+", raw) if k.strip()]
    n = 2
    while n <= 9:
        extra = os.getenv(f"{base}_{n}", "").strip()
        if not extra:
            break
        keys.append(extra.strip())
        n += 1
    return keys


def get_client_and_key(provider: str):
    """عميل واحد بالتناوب (round-robin) عبر مفاتيح المزوّد —
    كل طلب/محاولة تلقائياً بمفتاح مختلف لتوزيع الحصص المجانية،
    مع تجاوز تلقائي للمفاتيح المجمّدة (التي وصلت حدها أو فشلت مؤخراً)"""
    keys = _keys_of(provider) or [None]
    healthy = [k for k in keys if not _key_is_down(provider, k)]
    pool = healthy or keys   # لو كل المفاتيح مجمّدة — نجربها رغم ذلك (قد تكون الحصة عادت)
    i = _rot_count.get(provider, 0)
    _rot_count[provider] = i + 1
    key = pool[i % len(pool)]
    if (provider, key) not in _clients:
        cfg = PROVIDER_CONFIGS[provider]
        _clients[(provider, key)] = OpenAI(
            api_key=key,
            base_url=cfg["base_url"],
            timeout=cfg["timeout"],
            max_retries=1,
        )
    return _clients[(provider, key)], key


def get_client(provider: str) -> OpenAI:
    """إرجاع عميل المزوّد (يتناوب عبر المفاتيح المتاحة)"""
    c, _ = get_client_and_key(provider)
    return c


MAX_HISTORY = 40      # أقصى عدد رسائل محفوظة من المتصفح
MAX_MSG_LEN = 4000    # أقصى طول للرسالة الواحدة


# ===== حماية الحصص المجانية: حد استخدام لكل مستخدم =====
# يمنع أي حساب واحد من حرق ميزانية المزوّدين المجانية على الجميع.
# ===== ميزانية النموذج وتوزيع عادل =====
# الموديل المجاني (Groq) يعطي ~2000 طلب/يوم — عشان محدش يحرق الكل،
# كل مستخدم له حد يومي، والحد ينقص تلقائياً لما الميزانية تقل.
DAILY_BUDGET = int(os.getenv("DAILY_BUDGET", "2000") or 2000)
_USER_DAILY_LIMIT = int(os.getenv("USER_DAILY_LIMIT", "15") or 15)
_USER_HOURLY_LIMIT = int(os.getenv("USER_HOURLY_LIMIT", "5") or 5)
_USER_CALLS: dict = {}   # البريد -> قائمة أوقات الطلبات (ثواني)
_TOTAL_USED = 0          # إجمالي الطلبات اليوم (تتبّع الميزانية)

# ===== تتبّع التوكنز لكل مستخدم =====
_USER_TOKENS: dict = {}   # البريد -> إجمالي التوكنز المستخدمة اليوم
USER_DAILY_TOKEN_LIMIT = int(os.getenv("USER_DAILY_TOKEN_LIMIT", "20000") or 20000)
_TOKEN_LOCK = threading.Lock()


def _record_user_tokens(email: str, tokens: int) -> None:
    """تسجيل التوكنز المستخدمة من المستخدم"""
    if tokens <= 0:
        return
    with _TOKEN_LOCK:
        _USER_TOKENS[email] = _USER_TOKENS.get(email, 0) + tokens


def _check_user_tokens(email: str) -> tuple:
    """هل المستخدم عنده رصيد توكنز كافٍ؟ — (صحيح/غالط، رسالة)"""
    with _TOKEN_LOCK:
        used = _USER_TOKENS.get(email, 0)
    if used >= USER_DAILY_TOKEN_LIMIT:
        return False, f"🫡 وصلت الحد اليومي ({USER_DAILY_TOKEN_LIMIT} توكن). جرب بعد دقيقة أو بكرا 🌅"
    return True, None
_RATE_LOCK = threading.Lock()
_BUDGET_LOCK = threading.Lock()


def _get_dynamic_limits():
    """تحديد الحدود ديناميكياً حسب الميزانية المتبقية — توزيع عادل بين المستخدمين"""
    with _BUDGET_LOCK:
        remaining = max(0, DAILY_BUDGET - _TOTAL_USED)
    # لو الميزانية أقل من 30% — حدّ صارم (3 طلبات/يوم)
    # لو أقل من 50% — حدّ متوسط (8 طلبات/يوم)
    # لو أكثر من 50% — الحدّ العادي
    if remaining < DAILY_BUDGET * 0.3:
        return 3, remaining
    elif remaining < DAILY_BUDGET * 0.5:
        return 8, remaining
    else:
        return _USER_DAILY_LIMIT, remaining


def _check_user_rate(email: str):
    """هل يُسمح برسالة جديدة؟ — حدّ ساعة + يوم ديناميكي + توزيع عادل"""
    now = time.time()
    with _RATE_LOCK:
        stamps = [t for t in _USER_CALLS.get(email, []) if now - t < 86400]
        _USER_CALLS[email] = stamps
        # الحد بالساعة
        if sum(1 for t in stamps if now - t < 3600) >= _USER_HOURLY_LIMIT:
            return False, f"وصلت الحد — {_USER_HOURLY_LIMIT} رسالة بالساعة. الموديل مشغول، جرب بعد شوي"
        # الحد اليومي الديناميكي
        per_user_limit, remaining = _get_dynamic_limits()
        if len(stamps) >= per_user_limit:
            if remaining < DAILY_BUDGET * 0.3:
                return False, f"🫡 الموديل قريب يخلص — وصلت الحد اليومي ({per_user_limit}). جرب بعد دقيقة أو بكرا"
            return False, f"وصلت الحد اليومي — {per_user_limit} رسالة. يُجدَّد تلقائياً"
        return True, None


def _record_user_call(email: str) -> None:
    """تسجيل طلب جديد + تتبّع الميزانية"""
    with _RATE_LOCK:
        _USER_CALLS.setdefault(email, []).append(time.time())
    with _BUDGET_LOCK:
        global _TOTAL_USED
        if _TOTAL_USED < DAILY_BUDGET:
            _TOTAL_USED += 1


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
        video_enabled=VIDEO_ENABLED,
        video_models=[
            {"id": mid, "label": e["label"], "desc": e["desc"]}
            for mid, e in VIDEO_MODELS.items()
        ],
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
         "icon": e.get("icon"), "vision": bool(e.get("vision"))}
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


def _text_of(value) -> str:
    """استخراج النص من رسالة قد تكون نصاً عادياً أو قائمة أجزاء (عند إرفاق صورة)"""
    if isinstance(value, list):
        return "".join(
            p.get("text", "") for p in value
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return value or ""


def _valid_image(img) -> bool:
    """تحقق من أن الصورة المرفقة data-URI صالحة وليست ضخمة (حماية من الإساءة)"""
    if not isinstance(img, str) or not img:
        return False
    return img.startswith("data:image/") and ";base64," in img and len(img) < 4_000_000


# امتدادات الملفات حسب اللغة — لتسمية القطع البرمجية
_EXT_MAP = {
    "python": "py", "javascript": "js", "typescript": "ts", "jsx": "jsx",
    "tsx": "tsx", "html": "html", "htm": "html",
    "html+css": "html", "css": "css", "scss": "scss", "json": "json",
    "bash": "sh", "sh": "sh", "shell": "sh",
    "sql": "sql", "cpp": "cpp", "c": "c", "java": "java", "rust": "rs",
    "go": "go", "ruby": "rb", "php": "php", "swift": "swift",
    "kotlin": "kt", "vue": "vue", "svelte": "svelte",
    "scala": "scala", "dart": "dart", "perl": "pl", "r": "r",
    "markdown": "md", "md": "md", "text": "txt", "txt": "txt", "xml": "xml",
    "yaml": "yml", "yml": "yml",
}


def _clean_artifact_name(name: str, ext: str) -> str:
    """تنظيف اسم الملف المستخرج من النموذج (إزالة مسارات/رموز غريبة)"""
    name = (name or "").strip().strip("`'\"").split("\n")[0][:60]
    name = re.sub(r"[^A-Za-z0-9_.\-+\u0600-\u06FF ]", "", name).strip()
    if not name or name in (".", ".."):
        return f"file.{ext}"
    if "." not in name:
        return f"{name}.{ext}"
    return name


def _norm_artifact_lang(raw: str) -> str:
    """توحيد اسم اللغة (js→javascript، py→python...) حتى تعمل المعاينة والتلوين"""
    lang = (raw or "").strip().lower().split()[0][:20] or "text"
    aliases = {
        "js": "javascript", "py": "python", "ts": "typescript",
        "htm": "html", "md": "markdown", "sh": "bash",
        "yml": "yaml", "c++": "cpp", "c#": "csharp",
    }
    return aliases.get(lang, lang)


def _push_artifact(artifacts: list, seen: set, lang: str, name: str, code: str):
    """إضافة قطعة واحدة بعد التنظيف — تتجاهل الفارغ والمكرر"""
    code = (code or "").strip("\n")
    if not code.strip() or len(code.strip()) < 8:
        return
    lang = _norm_artifact_lang(lang)
    ext = _EXT_MAP.get(lang, lang or "txt")
    name = _clean_artifact_name(name, ext)
    key = (name, code[:120])
    if key in seen:
        return
    seen.add(key)
    artifacts.append({"name": name, "lang": lang, "code": code[:60000]})


def extract_artifacts(reply: str) -> list[dict]:
    """استخراج مقاطع الكود من الرد كقطع منفصلة (Artifacts) للمعاينة"""
    artifacts: list = []
    seen: set = set()
    text = reply or ""
    # 1) صناديق مكتملة ```lang:name ... ```
    pattern = re.compile(r"```(\w[\w+#-]*)(?:\s*:\s*([^\n]+))?\n([\s\S]*?)```")
    pos = 0
    for m in pattern.finditer(text):
        _push_artifact(artifacts, seen, m.group(1), m.group(2) or "", m.group(3))
        pos = m.end()
    # 2) صندوق غير مكتمل (بدون إغلاق ``` بسبب حد الطول) — حتى نهاية الرد
    tail = text[pos:] if pos else text
    um = re.search(r"```(\w[\w+#-]*)(?:\s*:\s*([^\n]+))?\n([\s\S]*)$", tail)
    if um:
        _push_artifact(artifacts, seen, um.group(1), um.group(2) or "", um.group(3))
        tail = ""
    # 3) صندوق بدون لغة ``` ... ``` — خمّن html إن كان فيه وسم، وإلا text
    for m2 in re.finditer(r"```\n([\s\S]*?)```", tail):
        code = m2.group(1)
        guess = "html" if re.search(r"<(html|!DOCTYPE|div|style|script|canvas|button)", code, re.I) else "text"
        _push_artifact(artifacts, seen, guess, "", code)
    # 4) كتلة HTML خام طويلة بدون صناديق (بعض النماذج تنسى ```) — التقطها
    if not artifacts:
        hm = re.search(r"(<!DOCTYPE html[\s\S]{200,30000}|<html[\s\S]{200,30000}</html>)", text, re.I)
        if hm:
            _push_artifact(artifacts, seen, "html", "index.html", hm.group(1))
    # أسماء افتراضية مرقمة إن تكررت (file.html, file-2.html...)
    counts: dict = {}
    for a in artifacts:
        counts[a["name"]] = counts.get(a["name"], 0) + 1
        if counts[a["name"]] > 1:
            base, dot, ext = a["name"].partition(".")
            a["name"] = f"{base}-{counts[a['name']]}{dot}{ext}" if dot else f"{base}-{counts[a['name']]}"
    # 5) ملف معاينة مدمج: إن وُجدت html+css/js منفصلة، ادمجها في preview.html
    langs = {a["lang"] for a in artifacts}
    names = {a["name"] for a in artifacts}
    if ("html" in langs or "css" in langs or "javascript" in langs) and "preview.html" not in names:
        merged = _merge_web_preview(artifacts)
        if merged:
            artifacts.insert(0, {"name": "preview.html", "lang": "html", "code": merged})
    return artifacts


def _merge_web_preview(artifacts: list) -> str:
    """دمج أول html + أول css + أول js في ملف واحد للمعاينة الحية"""
    html_p = next((a for a in artifacts if a["lang"] == "html"), None)
    css_p = next((a for a in artifacts if a["lang"] in ("css", "scss")), None)
    js_p = next((a for a in artifacts if a["lang"] in ("javascript", "typescript", "jsx", "tsx")), None)
    if not html_p and not css_p and not js_p:
        return ""
    base = html_p["code"] if html_p else "<!DOCTYPE html><html dir=\"rtl\" lang=\"ar\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body></body></html>"
    if css_p and "</style>" not in base.lower():
        css_tag = f"<style>\n{css_p['code']}\n</style>"
        base = base.replace("</head>", css_tag + "\n</head>") if "</head>" in base.lower() else css_tag + "\n" + base
    if js_p and "</script>" not in base.lower():
        js_tag = f"<script>\n{js_p['code']}\n</script>"
        base = base.replace("</body>", js_tag + "\n</body>") if "</body>" in base.lower() else base + "\n" + js_tag
    return base


@app.route("/api/chat", methods=["POST"])
@login_required
def chat_api():
    data = request.get_json(force=True, silent=True) or {}

    # حماية الحصص: حد للاستخدام لكل مستخدم — قبل أي عملية تستهلك الميزانية
    ok_rate, rate_msg = _check_user_rate(session.get("email", ""))
    if not ok_rate:
        return jsonify({"error": rate_msg}), 429
    _record_user_call(session.get("email", ""))

    # حماية التوكنز: حد يومي لكل مستخدم
    ok_tokens, token_msg = _check_user_tokens(session.get("email", ""))
    if not ok_tokens:
        return jsonify({"error": token_msg}), 429

    history = data.get("messages", [])
    requested = data.get("model")
    mode = (data.get("mode") or "chat").lower()          # chat | agent
    temperature = float(data.get("temperature", 0.7))
    temperature = max(0.0, min(1.5, temperature))
    max_tokens = int(data.get("max_tokens", 0) or 0)

    # بناء سجل المحادثة: شخصية البوت + الرسائل المُنقّاة (مع دعم إرفاق صور)
    # نرسل آخر صورتين فقط من المحادثة — حماية للحصص المجانية من الاحتراق
    # (الصور تستهلك رموزاً كثيرة، وإعادة إرسالها مع كل رسالة تالية تضاعف الاستهلاك)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    img_budget = 2
    for m in history[-MAX_HISTORY:]:
        role, content = m.get("role"), m.get("content", "")
        img = _valid_image(m.get("image")) and m.get("image")
        keep = (isinstance(content, str) and content.strip()) or bool(img)
        if role in ("user", "assistant") and keep:
            if role == "user" and img and img_budget > 0:
                img_budget -= 1
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": content[:MAX_MSG_LEN]},
                        {"type": "image_url", "image_url": {"url": img}},
                    ],
                })
            else:
                messages.append({"role": role, "content": content[:MAX_MSG_LEN]})

    if len(messages) == 1:
        return jsonify({"error": "الرسالة فارغة"}), 400

    # إذا النموذج المختار لتوليد الصور: حول آخر رسالة لصورة
    req_entry = MODELS.get(requested)
    if req_entry and req_entry.get("kind") == "image":
        prompt = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                prompt = _text_of(m.get("content", ""))
                break
        for prefix in ("/image", "/img", "صورة:", "ارسم:", "توليد صورة:"):
            if prompt.startswith(prefix):
                prompt = prompt[len(prefix):].strip()
        if not prompt:
            return jsonify({"error": "اكتب وصف الصورة التي تريد توليدها"}), 400
        return jsonify(build_image_payload(prompt, req_entry["id"]))

    # إذا النموذج المختار لتوليد الفيديو: حول آخر رسالة لفيديو
    if req_entry and req_entry.get("kind") == "video":
        vprompt = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                vprompt = _text_of(m.get("content", ""))
                break
        for prefix in ("/video", "/vid", "فيديو:", "فيديو قصير:", "مقطع:", "توليد فيديو:"):
            if vprompt.startswith(prefix):
                vprompt = vprompt[len(prefix):].strip()
        if not vprompt:
            return jsonify({"error": "اكتب وصف الفيديو الذي تريد توليده"}), 400
        return jsonify(build_video_payload(vprompt, requested))

    # === وضع Agent: بحث في الإنترنت + تنفيذ المهام (برمجة/بناء) ===
    sources = []
    if mode == "agent":
        query = _text_of(_extract_last_user(messages))
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
                "أنشئ", "سوي", "سويلي", "اعمل", "اعملي", "جهز", "جهزلي",
                "موقع", "صفحة", "تطبيق", "أداة", "اداة", "لعبة", "لعبه",
                "متجر", "مدونة", "بورتفوليو", "معرض", "لوحة", "حاسبة", "آلة حاسبة",
                "ساعة", "مؤقت", "قائمة", "نموذج", "فورم", "جدول", "تقويم",
                "game", "build", "make", "create", "website", "webpage", "page",
                "app", "html", "css", "javascript", "python", "code",
                "write code", "landing", "portfolio", "dashboard", "clone",
                "canvas", "snake", "tetris", "quiz", "todo", "calculator",
                "stopwatch", "weather", "chatbot", "gallery", "slider",
            ))
            if wants_build:
                context_parts.append(
                    "أنت الآن وكيل بناء تنفيذي (Builder Agent) — مهمتك كتابة كود حقيقي كامل يعمل فوراً، لا شرح نظري. "
                    "قواعد صارمة للإخراج: "
                    "1) أخرج كل ملف داخل صندوق كود منفصل بصيغة ```لغة:اسم-الملف (مثال: ```html:index.html ثم الكود ثم ```). "
                    "2) للموقع/الصفحة/اللعبة: ملف واحد index.html يحتوي كل شيء (CSS داخل <style> وJS داخل <script>) — كامل ويعمل بالفتح مباشرة، مع دعم عربي RTL إن كان المحتوى عربياً. "
                    "3) للعبة: استخدم <canvas> أو DOM مع requestAnimationFrame، أزرار تحكم، ونقاط/مراحل. "
                    "4) لا تختصر الكود أبداً بـ '...' أو 'باقي الكود' — اكتبه كاملاً حتى النهاية. "
                    "5) بعد الصناديق اكتب سطراً واحداً فقط يشرح كيف تشغّل النتيجة."
                )
            if context_parts:
                messages.append({
                    "role": "system",
                    "content": "الوضع: وكيل تنفيذ (Agent). " + " ".join(context_parts),
                })

    # هل توجد صورة مرفقة في الرسائل؟ — عندها نمرّ على النماذج التي تقرأ الصور فقط
    has_image = any(
        m.get("role") == "user" and _valid_image(m.get("image"))
        for m in history[-MAX_HISTORY:]
    )

    # ترتيب المحاولات: النموذج المطلوب أولاً، ثم بالتداخل بين المزوّدين —
    # عند فشل أحدهم ينتقل تلقائياً للتالي؛ وعند توفّر عدة مفاتيح لنفس المزوّد يتناوب بينها
    pool = [
        (mid, e) for mid, e in MODELS.items()
        if mid != requested and e.get("kind", "chat") == "chat"
        and (not has_image or e.get("vision"))
    ]
    by_provider: dict = {}
    for mid, e in pool:
        by_provider.setdefault(e.get("provider", "?"), []).append((mid, e))

    # التوزيع المتبادل يُبنى من المزوّدين الموجودين فعلاً (لا قائمة ثابتة!)
    # ⚠️ كان هنا خلل: قائمة ثابتة تنسى "openrouter" فتبقى قائمته غير فارغة
    # والحلقة while لا تنتهي أبداً — فيتجمّد كل طلب محادثة للأبد.
    priority = ("apinex", "gemini", "groq", "openrouter", "mistral",
                "cerebras", "nvidia", "together", "fireworks", "colab", "ollama")
    queues = {p: list(v) for p, v in by_provider.items()}
    order = sorted(queues, key=lambda p: priority.index(p) if p in priority else len(priority))
    interleaved: list = []
    guard = 0
    while any(queues[p] for p in order):
        for p in order:
            if queues[p]:
                interleaved.append(queues[p].pop(0))
        guard += 1
        if guard > 200:   # حماية مضاعفة: مستحيل نظرياً، لكن تمنع أي تعليق للموقع
            break

    ordered: list = []
    seen_mids: set = set()

    def _push(mid, entry):
        """إضافة نموذج للترتيب مرة واحدة فقط (مع احترام شرط الصور)"""
        if mid in seen_mids:
            return
        if has_image and not entry.get("vision"):
            return
        seen_mids.add(mid)
        ordered.append((mid, entry))

    # 1) النموذج الذي اختاره المستخدم — أولاً دائماً
    if requested in MODELS:
        _push(requested, MODELS[requested])
    # 2) نماذج APInex (أسرع مزوّد متاح حالياً)
    for mid, entry in MODELS.items():
        if entry.get("provider") == "apinex":
            _push(mid, entry)
    # 3) باقي النماذج — بالتناوب بين كل المزوّدين
    for mid, entry in interleaved:
        _push(mid, entry)

    # صندوق الأوامر الختامية: جرّب النماذج بالترتيب، ومع الضغط/الحد ننتظر قليلاً
    # ثم نجرب التالي — الحدود المجانية لحظية وتتسع بعد ثوانٍ.
    # عند توفّر عدة مفاتيح لنفس المزوّد (مثل GEMINI_API_KEY_2 و _3) يتناوب الموقع
    # بينها تلقائياً، فيجرب نفس النموذج بمفتاح تالٍ عند وصول المفتاح الأول لحده
    last_error = None
    rate_limited = 0
    for mid, entry in ordered[:3]:   # النموذج المطلوب + بديلان
        key_slots = len(_keys_of(entry["provider"])) or 1
        for _slot in range(min(key_slots, 2)):   # مفتاحين بدل 3
            c, used_key = get_client_and_key(entry["provider"])
            try:
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
                # ===== مهلة صارمة على الاتصال نفسه (12 ثانية) =====
                # ملاحظة مهمة: كان هنا ThreadPoolExecutor + result(timeout=10)، لكن الخروج
                # من بلوك with كان ينتظر انتهاء الخيط البطيء (shutdown wait=True) —
                # فتنمحي فائدة المهلة ويتعلّق الطلب دقائق. الآن المهلة على مستوى الطلب.
                r = c.with_options(timeout=12, max_retries=0).chat.completions.create(**kwargs)
                _choice_msg = r.choices[0].message if r.choices else None
                reply = (_choice_msg.content if _choice_msg else "") or ""
                # دعم لنماذج التفكير (مثل GPT-OSS على Groq) التي قد تعيد الرد داخل reasoning إذا استهلك الـ max_tokens
                if not reply.strip() and _choice_msg:
                    reply = getattr(_choice_msg, "reasoning", "") or getattr(_choice_msg, "reasoning_content", "") or ""
                # تتبّع التوكنز المستخدمة لكل مستخدم
                try:
                    _record_user_tokens(session.get("email", ""), r.usage.total_tokens if r.usage else 0)
                except Exception:
                    pass
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
                # 429 = تجاوز الحد، 402 = الحساب بلا حصة، 404 = نموذج غير موجود، 503 = ضغط،
                # 400/401/403 = الطلب غير مقبول (مثل صورة غير مدعومة)، None = خطأ اتصال
                if status in (400, 401, 402, 403, 404, 429, 503) or status is None:
                    # جمّد المفتاح الفاشل مؤقتاً حتى لا يُعاد تجربته مع كل طلب جديد
                    if status in (401, 402, 403, 429):
                        _mark_key_down(entry["provider"], used_key)
                    elif status == 503:
                        _mark_key_down(entry["provider"], used_key, seconds=10)
                    elif status is None:
                        _mark_key_down(entry["provider"], used_key, seconds=15)
                    if status == 429:
                        rate_limited += 1
                        time.sleep(0.3)  # هدّئ شوي ثم جرّب التالي
                        continue
                    if status == 503:
                        time.sleep(0.5)
                    break  # جرّب النموذج التالي
                break  # خطأ غير متوقع — اترك هذا النموذج
            except Exception as e:
                # أي خطأ غير متوقع — جرّب النموذج التالي بدل إسقاط الطلب
                last_error = e
                time.sleep(0.5)
                break

    print(f"خطأ API: {last_error}")
    # رسالة صادقة وواضحة حسب السبب
    if isinstance(last_error, OpenAIError) and getattr(last_error, "status_code", None) == 400 and has_image:
        return jsonify({
            "error": "النموذج المختار لا يدعم الصور — جرّب Al-Khwarizmi Flash أو Gemini 2.5 Flash"
        }), 400
    return jsonify({
        "error": "النماذج المجانية مشبعّة حالياً — جرّب مرة ثانية بعد دقيقة"
    }), 503


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


# ===== توليد الفيديو (Seedance / Wan عبر Pollinations) — مدفوع فيحتاج مفتاحاً =====
# كل نماذج الفيديو في Pollinations مدفوعة (لا يوجد بديل مجاني)، لذلك تُخفى
# هذه النماذج تماماً وتُعطَّل البوابة إذا لم يوجد POLLINATIONS_KEY في .env
VIDEO_ENABLED = bool(os.getenv("POLLINATIONS_KEY"))

VIDEO_MODELS = {
    "video-seedance-mini": {
        "label": "Seedance 2.0 Mini",
        "desc": "الأسرع والأرخص — مقطع ~5 ثوانٍ",
        "api": "bytedance/seedance-2.0-mini",
    },
    "video-seedance": {
        "label": "Seedance 2.0",
        "desc": "أعلى جودة سينمائية",
        "api": "bytedance/seedance-2.0",
    },
    "video-wan": {
        "label": "Wan 2.7",
        "desc": "مفتوح المصدر — من علي بابا",
        "api": "alibaba/wan-2.7",
    },
}

if VIDEO_ENABLED:
    MODELS.update({
        mid: {
            "label": "🎬 " + e["label"],
            "desc": e["desc"],
            "provider": "pollinations",
            "id": mid,
            "kind": "video",
        }
        for mid, e in VIDEO_MODELS.items()
    })


def _find_video_url(obj):
    """استخراج أول رابط فيديو من رد JSON متداخل (بعض النماذج ترجع رابطاً بدل ملف)"""
    if isinstance(obj, str) and obj.startswith("http"):
        return obj
    if isinstance(obj, dict):
        for k in ("video_url", "url", "videoUrl", "result", "data", "output"):
            if k in obj:
                found = _find_video_url(obj[k])
                if found:
                    return found
        for v in obj.values():
            found = _find_video_url(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _find_video_url(v)
            if found:
                return found
    return None


def build_video_payload(prompt: str, vid_model: str = "video-seedance-mini") -> dict:
    """بناء رد توليد الفيديو — يحتاج مفتاح Pollinations (كل نماذج الفيديو مدفوعة)"""
    key = os.getenv("POLLINATIONS_KEY")
    if not key:
        return {"error": "توليد الفيديو معطّل: يحتاج مفتاح Pollinations (POLLINATIONS_KEY) في ملف .env."}
    if vid_model not in VIDEO_MODELS:
        vid_model = "video-seedance-mini"

    seed = random.randint(1000, 9999999)
    english_prompt = enhance_image_prompt(prompt)
    encoded = urllib.parse.quote(english_prompt)
    api_model = VIDEO_MODELS[vid_model]["api"]
    url = (
        f"https://gen.pollinations.ai/video/{encoded}"
        f"?model={api_model}&seed={seed}&nologo=true&key={key}"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=420) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read()

        # بعض النماذج ترجع JSON فيه رابط بدل ملف الفيديو — نستخرجه ثم نحمّل الملف
        if not (ctype.startswith("video/") or data[4:8] == b"ftyp"):
            found = None
            try:
                found = _find_video_url(json.loads(data.decode("utf-8", "ignore")))
            except Exception:
                found = None
            if not found:
                raise ValueError("رد غير متوقع من سيرفر الفيديو")
            vreq = urllib.request.Request(found, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(vreq, timeout=420) as vresp:
                data = vresp.read()

        ext = "webm" if "webm" in ctype else "mp4"
        fname = f"vid_{seed}_{random.randint(1000, 9999)}.{ext}"
        with open(os.path.join(GENERATED_DIR, fname), "wb") as f:
            f.write(data)
        video_url = f"/static/generated/{fname}"
    except Exception as e:
        print(f"توليد الفيديو فشل: {e}")
        return {"error": "تعذر توليد الفيديو الآن — جرّب مرة أخرى بعد قليل."}

    return {
        "video_url": video_url,
        "enhanced_prompt": english_prompt,
        "original_prompt": prompt,
        "model_label": VIDEO_MODELS[vid_model]["label"],
    }


@app.route("/api/generate-video", methods=["POST"])
@login_required
def api_generate_video():
    data = request.get_json(force=True, silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip()
    vid_model = data.get("model") or "video-seedance-mini"

    if not VIDEO_ENABLED:
        return jsonify({
            "error": "توليد الفيديو معطّل: يحتاج مفتاح Pollinations (POLLINATIONS_KEY) في ملف .env ثم إعادة تشغيل السيرفر."
        }), 503
    if not user_prompt:
        return jsonify({"error": "يرجى كتابة وصف للفيديو المراد توليده"}), 400

    return jsonify(build_video_payload(user_prompt, vid_model))


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

