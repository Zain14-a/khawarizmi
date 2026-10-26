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
        "label": "Al-Khwarizmi Art",
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
    })

# نماذج عبر Cerebras — معطّلة حالياً: المفتاح يرجع 402 (يطلب تفعيل الفوترة)
# لإعادة التفعيل بعد شحن الحساب، أعد كتلة MODELS الخاصة بـ cerebras من Git
# if os.getenv("CEREBRAS_API_KEY"):

# نماذج عبر NVIDIA NIM — بقي فقط Llama 11B (الوحيد الذي يستجيب بهذا المفتاح)
# gemma-4-31b و llama-90b أُزيلا: مهلة متكررة (timeout) بهذا المفتاح
if os.getenv("NVIDIA_API_KEY"):
    MODELS.update({
        "nvidia-llama-vision": {
            "label": "Llama 3.2 Vision 11B",
            "desc": "يقرأ الصور والوثائق بدقة",
            "provider": "nvidia",
            "id": "meta/llama-3.2-11b-vision-instruct",
            "vision": True,
        },
    })

# نموذجك الخاص "الخوارزمي — خاص" — يعمل على Colab عبر بوابة Ollama الخاصة
# يُسجَّل دائماً (وليس فقط عند وجود المتغيّرات) حتى يظهر في الواجهة فور ربط النفق.
# الحالة الحقيقية (متصل/غير متصل) تُقرأ من COLABC_RUNTIME.
MODELS.update({
    "khwarizmi-local": {
        "label": "الخوارزمي — خاص",
        "desc": "نموذجك الخاص على Colab — برمجة وبناء مشاريع",
        "provider": "colab",
        "id": "khwarizmi",
        "icon": "bolt",
        "private": True,          # شعار "خاص" في الواجهة
    },
})
COLABC_MODEL_IDS = ("khwarizmi-local",)

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

# ═══════ نماذج APInex — معطّلة حالياً: الحساب يرجع 403 (suspended/missing) ═══════
# لإعادة التفعيل بمفتاح جديد، أعد كتلة MODELS الخاصة بـ apinex من Git
# if os.getenv("APINEX_API_KEY"):

# ═══════ نماذج PlugSky (مجاني — متوافق مع OpenAI) ═══════
# المفتاح: PLUGSKY_API_KEY | Base URL: https://api.plugsky.com/v1
if os.getenv("PLUGSKY_API_KEY"):
    MODELS.update({
        "plugsky-micro": {
            "label": "Plugsky Micro",
            "desc": "مجاني — سريع + يقرأ الصور — 262K سياق",
            "provider": "plugsky",
            "id": "plugsky-micro",
            "vision": True,
        },
        "plugsky-lite": {
            "label": "Plugsky Lite",
            "desc": "مجاني — خفيف وسريع الاستجابة",
            "provider": "plugsky",
            "id": "plugsky-lite",
        },
        "plugsky-coder-fast": {
            "label": "Plugsky Coder",
            "desc": "متخصص بالبرمجة والكود",
            "provider": "plugsky",
            "id": "plugsky-coder-fast",
        },
        "plugsky-vision-fast": {
            "label": "Plugsky Vision",
            "desc": "يقرأ الصور والوثائق بدقة",
            "provider": "plugsky",
            "id": "plugsky-vision-fast",
            "vision": True,
        },
    })

# ═══════ نماذج XKiro AI (مجاني — متوافق مع OpenAI) ═══════
# المفتاح: XKIRO_API_KEY | Base URL: https://api.xkiro.com/v1
if os.getenv("XKIRO_API_KEY"):
    MODELS.update({
        "xk-qwen-plus": {
            "label": "Qwen Plus",
            "desc": "مجاني — قوي بالعربية — يقرأ الصور",
            "provider": "xkiro",
            "id": "qwen/qwen-plus-2025-07-28:free",
            "vision": True,
        },
        "xk-qwen3-max": {
            "label": "Qwen 3 Max",
            "desc": "مجاني — الأقوى — يقرأ الصور",
            "provider": "xkiro",
            "id": "qwen/qwen3-max:free",
            "vision": True,
        },
        "xk-qwen-coder": {
            "label": "Qwen Coder Plus",
            "desc": "مجاني — متخصص بالبرمجة — يقرأ الصور",
            "provider": "xkiro",
            "id": "qwen/qwen3-coder-plus:free",
            "vision": True,
        },
        "xk-ministral-14b": {
            "label": "Ministral 14B",
            "desc": "مجاني — سريع وذكي — يقرأ الصور",
            "provider": "xkiro",
            "id": "mistralai/ministral-14b",
            "vision": True,
        },
    })

# ═══════════ نماذج OpenRouter (فقط الشغالة — حُذفت الميتة بتاريخ اليوم) ═══════════
# المحذوف: or-glm-5.2 و or-qwen-3.8 و or-nex-pro (404: لم تعد مجانية)
# + or-ling-fin و or-ling-sante (404: لا endpoints) — تُسترجع من Git عند توفرها
if os.getenv("OPENROUTER_API_KEY"):
    MODELS.update({
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
        # رابط نفق Cloudflare — يُقرأ من المتغيّر العام COLABC_RUNTIME حتى يمكن
        # تحديثه من النوتبوك بدون إعادة تشغيل الموقع (شوف api_colab_update_tunnel)
        "base_url": "",   # تُملأ أدناه من COLABC_RUNTIME
        "key_env": "COLABC_KEY",
        "timeout": 60,   # نماذج محلية بطيئة — مهلة أطول من المزوّدين السحابيين
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
    "plugsky": {
        "base_url": "https://api.plugsky.com/v1",
        "key_env": "PLUGSKY_API_KEY",
        "timeout": 10,
    },
    "xkiro": {
        "base_url": "https://api.xkiro.com/v1",
        "key_env": "XKIRO_API_KEY",
        "timeout": 10,
    },
}

_clients: dict = {}
_rot_count: dict = {}

# ===== حالة "الخوارزمي المحلي" القابلة للتحديث وقت التشغيل =====
# النوتبوك على كولاب يرسل الرابط والمفتاح الجديدين إلى /api/colab/update-tunnel
# فنحدّثهما هنا فوراً — بدون إعادة تشغيل الموقع.
COLABC_RUNTIME = {
    "url": os.getenv("COLABC_URL", "").strip(),
    "key": os.getenv("COLABC_KEY", "").strip(),
    "model": os.getenv("COLABC_MODEL", "qwen2.5-coder:14b").strip(),
    "updated_at": 0.0,
    "live": False,          # هل النفق يستجيب فعلاً؟ (يُحدَّث عند كل فحص)
}
PROVIDER_CONFIGS["colab"]["base_url"] = COLABC_RUNTIME["url"]

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
    # مزوّد كولاب: المفتاح يأتي من الحالة القابلة للتحديث (النوتبوك يرسله)
    if provider == "colab" and COLABC_RUNTIME["key"]:
        raw = COLABC_RUNTIME["key"]
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
    # نضع Al-Khwarizmi Flash دائماً في رأس القائمة، وباقي النماذج بترتيبها (فرز مستقر)
    entries = list(MODELS.items())
    colab_live = _colab_is_live()
    return jsonify([
        {"id": mid, "label": e["label"], "desc": e["desc"], "kind": e.get("kind", "chat"),
         "icon": e.get("icon"), "vision": bool(e.get("vision")),
         "private": bool(e.get("private")),
         # حالة المزوّد الخاص: true/false/null (null = نموذج عادي ليس خاصاً)
         "live": (colab_live if e.get("provider") == "colab" else None)}
        for mid, e in entries
    ])


# ===== ربط "الخوارزمي الخاص" على Colab =====
def _colab_is_live() -> bool:
    """هل رابط النفق الحالي يستجيب فعلاً؟ (فحص سريع مع كاش قصير لتجنّب الإبطاء)"""
    url = COLABC_RUNTIME.get("url") or ""
    if not url:
        return False
    now = time.time()
    # كاش لمدّة 20 ثانية — لا نفحص مع كل طلب واجهة
    if now - COLABC_RUNTIME.get("live_checked", 0) < 20:
        return bool(COLABC_RUNTIME.get("live"))
    COLABC_RUNTIME["live_checked"] = now
    base = url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        req = urllib.request.Request(base + "/health", headers={"User-Agent": "KhawarizmiBot/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            COLABC_RUNTIME["live"] = (r.status == 200)
    except Exception:
        COLABC_RUNTIME["live"] = False
    return bool(COLABC_RUNTIME["live"])


def _push_models_if_needed():
    """تسجيل نموذج colab يحدث دائماً عند الاستيراد، فلا حاجة لعمل شيء هنا."""
    return


@app.route("/api/colab/update-tunnel", methods=["POST"])
def api_colab_update_tunnel():
    """يستدعيه النوتبوك على Colab لربط/تحديث رابط النفق تلقائياً.
    الحماية عبر هيدر X-Colab-Secret المطابق لمتغيّر COLAB_SECRET في .env"""
    secret = os.getenv("COLAB_SECRET", "").strip()
    if not secret:
        return jsonify({"error": "COLAB_SECRET غير مضبوط على السيرفر — أضفه إلى .env"}), 503
    if request.headers.get("X-Colab-Secret", "") != secret:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip().rstrip("/")
    key = (data.get("key") or "").strip()
    model = (data.get("model") or "").strip()

    if not url or not url.startswith("http"):
        return jsonify({"error": "رابط غير صالح"}), 400
    if not key:
        return jsonify({"error": "مفتاح مفقود"}), 400

    # توحيد الشكل: يجب أن ينتهي الرابط بـ /v1
    if not url.endswith("/v1"):
        url = url + "/v1"

    old_key = COLABC_RUNTIME.get("key")
    COLABC_RUNTIME["url"] = url
    COLABC_RUNTIME["key"] = key
    COLABC_RUNTIME["updated_at"] = time.time()
    COLABC_RUNTIME.pop("live_checked", None)   # فحص جديد فوراً
    if model:
        COLABC_RUNTIME["model"] = model

    # حدّث إعدادات المزوّد + أعد بناء العميل (الرابط/المفتاح الجديدان)
    PROVIDER_CONFIGS["colab"]["base_url"] = url
    for (p, k) in list(_clients.keys()):
        if p == "colab":
            _clients.pop((p, k), None)
    # ارفع التجميد عن المفاتيح القديمة حتى لا يبقى المفتاح السابق معطلاً
    if old_key and old_key != key:
        _KEY_COOLDOWN.pop(("colab", old_key), None)

    live = _colab_is_live()
    print(f"🔗 تم تحديث نفق الخوارزمي: {url} | النموذج: {COLABC_RUNTIME['model']} | حيّ: {live}")
    return jsonify({"ok": True, "url": url, "model": COLABC_RUNTIME["model"], "live": live})


@app.route("/api/colab/status")
@login_required
def api_colab_status():
    """حالة النموذج الخاص — تعرضها الواجهة كنقطة خضراء/حمراء"""
    return jsonify({
        "configured": bool(COLABC_RUNTIME.get("url") and COLABC_RUNTIME.get("key")),
        "live": _colab_is_live(),
        "model": COLABC_RUNTIME.get("model"),
        "updated_at": COLABC_RUNTIME.get("updated_at", 0),
    })


_SEARCH_CACHE: dict = {}
_SEARCH_CACHE_TTL = 600     # 10 دقائق — يوفّر زمن الرد عند تكرار السؤال نفسه
_SEARCH_CACHE_MAX = 200


def _web_search_uncached(query: str, limit: int = 4, full_query: str = ""):
    """بحث في ويكيبيديا (عربي/إنجليزي) — مجاني بدون مفتاح"""
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
            with urllib.request.urlopen(req, timeout=8) as r:
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
    results = results[:limit]
    # الأرقام والتواريخ لا تظهر في مقتطف البحث (srprop=snippet) لأنه يقتطع
    # أول ~200 حرف من الفقرة، وفيها الاسم واللقب فقط. مثال "روميل": المقتطف
    # يقول "كان مشيرًا ميدانيًا" بدون سنة الميلاد، فيضطر النموذج للتخمين.
    # فإذا كان السؤال يطلب رقماً، نجلب مقدمة الصفحة كاملة (lead) وهي الفقرة
    # الأولى بتمامها، وفي الغالب تحوي سنة الميلاد وسنة الوفاة داخلها.
    # ⚠️ الفحص على النص الكامل (full_query) لا على جوهر البحث: _search_query
    # يقصّ السؤال لجملته الأولى، فيضيع منه مثلاً "كم" أو "سنة ميلاده".
    if results and _query_wants_number(full_query or query):
        _enrich_with_lead(results)
    return results


# أسئلة تطلب رقماً أو تاريخاً — تستحق جلب المقدمة الكاملة بدل المقتطف القصير
_NUM_ASK_RE = re.compile(
    r"(سنة|سنت|عام|تاريخ|ميلاد|مولد|وفاة|توفي|مات|عمر|كم|عدد|رقم|"
    r"year|born|died|age|population|how many)", re.IGNORECASE)


def _query_wants_number(query: str) -> bool:
    """هل يطلب السؤال رقماً أو تاريخاً محدَّداً؟"""
    return bool(_NUM_ASK_RE.search(query or ""))


def _enrich_with_lead(results: list, chars: int = 700) -> None:
    """استبدال المقتطف بمقدمة الصفحة الكاملة (lead) — فيها الأرقام والتواريخ.

    يعدّل النتائج في مكانها؛ الفشل الصامت مقبول (نتبقى بالمقتطف القصير).
    """
    for item in results[:3]:   # أول 3 فقط — كل نتيجة تطلب طلباً إضافياً من ويكيبيديا
        title = item.get("title", "")
        if not title:
            continue
        lang = "en" if "en.wikipedia.org" in item.get("url", "") else "ar"
        try:
            api = (f"https://{lang}.wikipedia.org/w/api.php?action=query"
                   f"&prop=extracts&exintro=1&explaintext=1&format=json&utf8=1"
                   f"&titles={urllib.parse.quote(title)}")
            req = urllib.request.Request(
                api, headers={"User-Agent": "KhawarizmiBot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            lead = ""
            for page in data.get("query", {}).get("pages", {}).values():
                lead = page.get("extract", "") or ""
                if lead:
                    break
            if lead.strip():
                item["snippet"] = lead.strip()[:chars]
        except Exception:
            continue


# ===== بوابة البحث الذكي: متى نبحث ومتى نتخطى؟ =====
# الهدف: لا مصادر بلا علاقة — البحث فقط للأسئلة المعرفية الحقيقية.
_GREET_PREFIX = (
    "مرحبا", "مرحباً", "اهلا", "أهلا", "هلا", "سلام",
    "صباح الخير", "مساء الخير", "تحياتي",
    "كيف حالك", "كيفك", "شو اخبارك", "شو أخبارك",
    "شكرا", "شكراً", "thanks", "thank you",
    "hi", "hello", "hey", "good morning", "good evening", "how are you",
)
_CHITCHAT_EXACT = {
    "مشكور", "يسلمو", "تسلم", "ممتاز", "جميل", "تمام", "طيب",
    "اوك", "أوك", "حسنا", "حسناً", "نعم", "لا", "باي",
    "ok", "okay", "bye", "yes", "no",
}
# مهارات لا يفيدها بحث ويكيبيديا — البحث عنها كان ينتج مصادر بلا علاقة
_NO_SEARCH_PATTERNS = (
    # كود وبرمجة (طلباً أو لصقاً) وطريقة عمل
    "```", " code", "code:", "اكتب كود", "اكتبلي كود", "كود", "أكواد",
    "برمج", "برنامج",
    "سكريبت", "سكربت", "دالة", "فنكشن",
    "function", "def ", "import ", "print(", "console.", "class ",
    "for (", "while (", "select ",
    "خطأ", " error", "exception", "traceback", "debug", "صلح", " bug",
    " json", "sql ", "regex",
    "كيف أعمل", "كيف اعمل", "كيف أسوي", "كيف اسوي",
    "كيف اصلح", "كيف أصلح", "طريقة عمل", "كيفية ",
    "how to", "how do i", "how can i", "fix ",
    # كود صريح بالإنجليزية (how to center a div...)
    " a div", "div ", "css ", "html ", "موقع شخصي", "موقع ",
    # طلبات مهارة/قدرة عامة (كيف أعمل X؟ ماذا تستطيع؟) — ليست أسئلة معرفية
    # رياضيات
    "احسب", "حل المعادلة", "حل معادلة", "مشتقة", "تكامل",
    "solve ", "calculate",
    # ترجمة (مهارة لغوية — لا بحث)
    "ترجم", "translate", "مامعنى كلمة", "معنى كلمة",
    # إبداع
    "اكتب لي قصة", "اكتب قصة", "قصة قصيرة", "قصيدة", "شعر ",
    "ديوان", "رواية", "خاطرة", "نكتة", "نكت ",
    "write a story", "write a poem", " poem", " story about",
    # رأي ونصيحة وتوصية
    "برأيك", "برايك", "رأيك", "ما رأيك", "شو رأيك",
    "نصيحة", "انصحني", "أيهما أفضل", "ايهما افضل",
    "اقترح", "رشح", "what do you think", "your opinion", "advice", "recommend",
    "هل يمكنك", "هل تستطيع", "هل تقدر", "can you", "could you", "would you",
    # تلخيص (النص مُعطى من المستخدم — البحث عنه هراء)
    "لخص", "ملخص", "اختصر", "summariz", "summary of",
    # هوية المساعد وقدراته
    "من أنت", "من انت", "من انا", "عرف بنفسك", "شو اسمك", "ما اسمك",
    "who are you", "your name",
    "ماذا تستطيع", "شو بتقدر", "what can you do",
    # شخصي/عاطفي
    "انا حزين", "أنا حزين", "انا تعبان", "أنا تعبان",
    "قلقان", "متضايق", "i am sad", "i'm sad", "i feel ",
)
# نسخة موحّدة للهوية (بعد _norm_ar: همزة→ا، ة→ه) — تُفحص قبل بوابة _FACT_PREFIX
# لأن "من أنت؟" تبدأ بـ "من" فيلتقطها _FACT_PREFIX خطأً
_IDENTITY_PATTERNS = (
    "من انت", "من انا", "عرف بنفسك", "شو اسمك", "ما اسمك",
    "who are you", "your name",
    "ماذا تستطيع", "شو بتقدر", "what can you do",
)
# أدوات استفهام في بداية السؤال — مؤشر قوي على سؤال معرفي
# ملاحظة الترتيب: الأطول أولاً (من هو قبل من، كيف حالك ليس سؤالاً معرفياً)
_FACT_PREFIX = (
    "من هو", "من هي", "ما هو", "ما هي", "ماهو", "ماهي", "ماذا",
    "مين هو", "مين هي",
    "متى", "أين", "اين", "وين", "لماذا", "ليش", "كيف", "كم", "قديش",
    "هل", "شو", "مين", "من",
    "عرف", "اشرح", "فسر", "أخبرني", "اخبرني", "حدثني",
    "what", "who", "when", "where", "why", "how", "which",
    "define", "explain", "tell me",
)
# تحايا بصيغة سؤال — ليست أسئلة معرفية (تُفحص قبل _FACT_PREFIX)
_NON_FACT_QUESTION = (
    "كيف حالك", "كيفك", "شو اخبارك", "شو أخبارك", "كيف الحال",
    "how are you",
)
# عبارات معرفية داخل النص (مواضيع وأخبار وأحداث)
_FACT_CONTAINS = (
    "من هو", "من هي", "ما هو", "ما هي", "ما المقصود", "ما تعريف",
    "معلومات عن", "نبذة عن", "كم عدد",
    "آخر", "الأخير", "حالياً", "حاليا",
    "أخبار", "اخبار",
    "عاصمة", "تأسس", "تأسست", "عدد سكان", "مساحة",
    "who is", "what is", "when did", "how many",
    "latest", "current", "today",
    "capital of", "founded in", "population of",
)


def web_search(query: str, limit: int = 4, full_query: str = ""):
    """بحث ويب مع تخزين مؤقت — يُستدعى قبل كل رد لتقليل الأجوبة الخاطئة

    full_query = نص المستخدم كاملاً (بلا قصّ)، تُستخدم لتقرير نية الرقم فقط.
    """
    q = (query or "").strip().lower()[:200]
    if not q:
        return []
    # نية الرقم جزء من هوية النتيجة: نفس الجوهر بسؤال رقمي ⇐ محتوى مختلف
    key = (q, limit, _query_wants_number(full_query or query))
    now = time.time()
    hit = _SEARCH_CACHE.get(key)
    if hit and now - hit[0] < _SEARCH_CACHE_TTL:
        return hit[1]
    results = _web_search_uncached(query, limit, full_query)
    _SEARCH_CACHE[key] = (now, results)
    if len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX:
        for k in list(_SEARCH_CACHE)[: _SEARCH_CACHE_MAX // 2]:
            _SEARCH_CACHE.pop(k, None)
    return results


def _search_context(sources: list, query: str) -> str:
    """سياق نتائج بحث مُفلترة الصلة — يُلزم النموذج بالدقة ويمنع اختلاق الحقائق"""
    lines = "\n".join(
        f"- {s['title']}: {s['snippet']} ({s['url']})" for s in sources
    )
    # بند 3أ — يعمل دائماً مع الأسئلة الرقمية: صندوق معلومات ويكيبيديا العربي
    # (سنوات الميلاد/الوفاة/السكان) لا يظهر في نص المقتطف ولا في المقدمة، فلو
    # التزمنا بالمنع الحرفي لأخفينا معلومة صحيحة معروفة. نسمح بالمعرفة الداخلية
    # *مع التصريح*، وهو أأمن من الصمت ومن التخمين الصامت.
    gap_rule = (
        "\n3أ) بند خاص لأن السؤال يطلب رقماً أو تاريخاً: إذا لم يحتوِ نص النتائج "
        "على الرقم المطلوب تحديداً، فاعتمد معرفتك الداخلية عن هذه الشخصية أو "
        "الموضوع، واذكر الرقم مع التصريح بأنه من معرفتك لا من المصادر "
        "(مثل: «١٨٩١ الميلاد، ١٩٤٤ الوفاة — من معرفت العامة لا من النص أعلاه»). "
        "لا تكتب عبارة لم أجد معلومات في هذه الحالة، ولا تخترع رقماً لا تجده "
        "باليقين في معرفتك.\n"
        if _query_wants_number(query) else ""
    )
    return (
        f"نتائج بحث حقيقية من الإنترنت (ويكيبيديا) عن: {query[:150]}\n"
        + lines
        + "\n\nقواعد إلزامية:\n"
        "1) هذه النتائج مرتبطة مباشرة بالسؤال — اعتمد عليها كمصدرك الأساسي للحقائق والأرقام والتواريخ والأسماء.\n"
        "2) إن تعارضت معلوماتك الداخلية مع النتائج فالأولوية للنتائج.\n"
        "3) ممنوع منعاً باتاً اختراع أرقام أو تواريخ أو أسماء، والنتائج هي المرجع — "
        "انسخ الأرقام والتواريخ حرفياً كما وردت ولا تُعد صياغتها تقريبياً. "
        'وإن طُلبت معلومة دقيقة غير موجودة فقل: "لم أجد معلومات موثوقة كافية" بدل التخمين '
        "(والاستثناء الوحيد للرقم المطلوب هو البند 3أ أدناه).\n"
        + gap_rule
        + "4) اذكر المصادر التي استخدمتها فعلاً في نهاية الجواب بصيغة: (المصدر: العنوان).\n"
        "5) إن كان الجواب كوداً برمجياً فلا تذكر المصادر داخله ولا تُقحمها في الشرح — اكتب الكود نظيفاً كاملاً."
    )


def _needs_search(query: str) -> bool:
    """هل يستحق هذا النص بحثاً في الإنترنت؟
    نبحث عن الأسئلة المعرفية — ونتخطى التحيات والكود والرياضيات
    والترجمة والإبداع والرأي والتلخيص."""
    q = (query or "").strip()
    if not q:
        return False
    ql = q.lower()
    norm = re.sub(r"[؟?!.،,؛:\s]+$", "", ql).strip()

    # تحية بصيغة سؤال (كيف حالك؟) — ليست سؤالاً معرفياً أبداً
    if norm in _CHITCHAT_EXACT or norm.startswith(_NON_FACT_QUESTION):
        return False
    # هوية المساعد ومهاراته (من أنت؟ ماذا تستطيع؟) — تُفحص قبل بوابة _FACT_PREFIX
    if any(p in _norm_ar(q) for p in _IDENTITY_PATTERNS):
        return False
    # 0) سؤال معرفي صريح (من هو X؟) — يُبحث، لكن بعد فحص المهارات أولاً:
    # "كيف أعمل موقع؟" تبدأ بكيف لكنها مهارة لا معرفة — المهارات أولاً
    # 2) مهارات لا يفيدها بحث ويكيبيديا
    if any(p in ql for p in _NO_SEARCH_PATTERNS):
        return False
    if ql.startswith(_FACT_PREFIX):
        rest = _SEARCH_STRIP_RE.sub("", q).strip()
        rest = re.split(r"[؟?!.؛;]", rest)[0].strip()
        # إسقاط بقايا ضمير بلا موضوع (مين هو؟ ← هو، من هو؟ ← هو)
        if re.fullmatch(r"(هو|هي|هم|هذا|هذه|ذلك|ذاك)", rest):
            return False
        if len(rest) >= 2:
            return True
        return False
    # 0.5) نص قصير جداً بلا أداة سؤال — تحية أو كلمة مفردة غالباً
    if len(q) < 15:
        return False
    # 1) تحايا وشكر — إلا إذا تبعها سؤال فعلي (استفهام أو أداة سؤال)
    if norm in _CHITCHAT_EXACT or norm.startswith(_GREET_PREFIX):
        if not ("؟" in q or "?" in q
                or ql.startswith(_FACT_PREFIX)
                or any(t in ql for t in _FACT_CONTAINS)):
            return False
    # إن احتوى على علامة استفهام صريحة وطال بما يكفي فهو سؤال — ابحث
    if ("؟" in q or "?" in q) and len(q) >= 40:
        return True
    # 3) مسألة حسابية صريحة (أرقام وعمليات)
    if re.search(r"\d\s*[+\-*/^%=÷×]\s*\d", ql):
        return False
    # 4) سؤال معرفي صريح — ابحث
    if ql.startswith(_FACT_PREFIX) or any(t in ql for t in _FACT_CONTAINS):
        return True
    # 5) نص طويل وصفي (سؤال حقيقي غالباً) — ابحث
    if len(q) >= 40:
        return True
    return False


_SEARCH_STRIP_RE = re.compile(
    r"^(من هو|من هي|من|ما هو|ما هي|ما هى|ماهو|ماهي|ماذا|متى|اين|أين|وين|"
    r"لماذا|ليش|كيف|كم عدد|كم|قديش|هل|شو|مين هو|مين هي|مين|"
    r"عرفني|عرف|اشرح|فسر|"
    r"اخبرني عن|أخبرني عن|حدثني عن|معلومات عن|نبذه عن|نبذة عن|"
    r"ما المقصود|ما تعريف|"
    r"what is|what are|who is|who was|when did|when was|where is|how many|"
    r"define|explain|tell me about)\s+",
    re.IGNORECASE,
)
_GREET_STRIP_RE = re.compile(
    r"^(مرحبا|مرحباً|اهلا|أهلا|هلا|سلام|صباح الخير|مساء الخير|"
    r"تحياتي|شكرا|شكراً)[،,\s]+",
    re.IGNORECASE,
)


def _search_query(query: str) -> str:
    """صياغة استعلام بحث مركّز: بدون تحية أو أدوات استفهام، الجملة الأولى فقط"""
    q = (query or "").strip()
    q = _GREET_STRIP_RE.sub("", q).strip()
    q = _SEARCH_STRIP_RE.sub("", q).strip()
    q = re.split(r"[؟?!.؛;]", q)[0].strip()
    return (q or (query or "").strip())[:200]


# ===== خيار B: Al-Khwarizmi Flash بطل البرمجة، والأسئلة المعرفية لنموذج أدق =====
# Flash هو openai/gpt-oss-20b: ممتاز في كتابة الكود، لكنه ضعيف في الحقائق
# الدقيقة (يلتبس بالأرقام والتواريخ). فنوجّه السؤال المعرفي إلى نموذج أقوى
# مع مصادر ويكيبيديا، بدل تخمين Flash.
# ⚠️ السلسلة مقصورة على مزوّدين مُتحقَّق من عملهما فعلياً (Gemini وGroq)،
# لأن المزوّدات الأخرى تُرجع 402/429/404 فتنتهي بالسقوط بلا جواب.
_FACTUAL_CHAIN = ("gemini-2.5-flash", "groq-gpt-oss-120b")


def _pick_factual_model(has_image: bool):
    """أول نموذج قوي متاح فعلياً لهذا المسار — أو None إن لم يوجد."""
    for mid in _FACTUAL_CHAIN:
        entry = MODELS.get(mid)
        if not entry or entry.get("kind", "chat") != "chat":
            continue
        if has_image and not entry.get("vision"):
            continue
        return mid
    return None


def _is_factual_query(query: str, build_task: bool) -> bool:
    """هل هذا سؤال معرفي يستحق التوجيه؟

    يعتمد على بوابة البحث نفسها: ما يحتاج بحثاً ليس سؤالاً معرفياً
    (كود، تحية، هوية، ترجمة، رياضيات، إبداع، مهمة Agent) — فيبقى على Flash.
    """
    if build_task:
        return False
    return _needs_search(query)


def _norm_ar(s: str) -> str:
    """توحيد بسيط للعربية قبل المقارنة: همزات، تاء مربوطة، ألف مقصورة، وبدون تنقيط"""
    s = (s or "").lower()
    s = re.sub(r"[أإآ]", "ا", s)
    s = re.sub(r"[؟?!.،,؛:\"'«»()\[\]-]", " ", s)  # ؟ ضمن النطاق العربي — يجب إسقاطها
    return s.replace("ة", "ه").replace("ى", "ي")


def _stem_ar(w: str) -> str:
    # إسقاط أداة التعريف فقط (الجامعة/جامعة، النجاح/نجاح)
    if w.startswith("ال") and len(w) > 5:
        w = w[2:]
    # الضمائر المتصلة بالأسماء (عاصمتها/عاصمه، جامعتهم/جامعه، رئيسها/رئيس)
    for suf in ("هم", "هن", "هما", "ها", "نا", "كم", "كن"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    # تاء التأنيث المتبقية بعد الضمير (عاصمت ← عاصمه)
    if w.endswith("ت") and len(w) >= 5 and not w.endswith("ات"):
        w = w[:-1] + "ه"
    # جمع المؤنث السالم ← المفرد (جامعات ← جامعه): أسقط "ات" وأضف هاء
    if w.endswith("ات") and len(w) >= 6 and not w.endswith("هات"):
        w = w[:-2] + "ه"
    return w


# كلمات boilerplate لا تدل على الموضوع — تُستبعد قبل حساب تداخل الصلة
# ملاحظة: تُكتب هنا *بعد* التوحيد (همزة→ا، ة→ه، ى→ي) لأن المقارنة تتم بعد _norm_ar
_AR_STOPWORDS = {
    "من", "ما", "ماذا", "متي", "اين", "لماذا", "كيف", "كم", "قديش",
    "هل", "شو", "مين", "وين", "ليش",
    "في", "علي", "الي", "عن", "مع", "بين", "هذا", "هذه", "تلك",
    "التي", "الذي", "الذين", "هو", "هي", "هم", "نحن", "انت", "انا",
    "كان", "كانت", "يكون", "كل", "بعض", "غير", "جدا", "اي", "ان",
    "او", "اليوم", "سنه", "عام", "تاريخ", "معلومات", "نبذه", "تعريف",
    "معني", "شرح", "عرف", "عرفني", "اشرح", "فسر", "اخبرني", "حدثني",
    "اذكر", "بحث", "سوال", "جواب",
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and",
    "or", "is", "are", "was", "were", "what", "who", "when", "where",
    "why", "how", "which", "does", "did", "about",
    "tell", "define", "explain",
}


def _query_tokens(query: str) -> set:
    """الكلمات المفتاحية للسؤال بعد التوحيد وإسقاط الحشو"""
    toks = set()
    # الاستفهام/التنقيط ليس كلمة مفتاحية (؟ ؟ ! .) — تُستبعد من التوكنز
    for w in re.findall(r"[\u0600-\u06FFa-zA-Z0-9]+", _norm_ar(query)):
        if len(w) < 3 or w in _AR_STOPWORDS:
            continue
        t = _stem_ar(w)
        if len(t) >= 3 and t not in _AR_STOPWORDS:
            toks.add(t)
    return toks


def _fuzzy_contains(hay: str, tok: str) -> bool:
    """احتواء عربي متسامح: يتجاوز اختلافات الإملاء الشائعة.
    - يطابق التطابق المباشر أولاً (رومل ⊂ إرفين رومل)
    - يتجاوز حروف العلة الضعيفة (ا/و/ي): روميل ≈ رومل
    - يسمح بفرق حرف واحد للكلمات ≥4 (خطأ إملائي واحد)"""
    if not tok or len(tok) < 3:
        return tok in hay if tok else False
    if tok in hay:
        return True
    weak = "اوي"
    core = "".join(c for c in tok if c not in weak)
    # جوهر ≥3 أحرف مشاركة — يطابق (رومل/روميل ← رمل)
    if len(core) >= 3:
        for w in hay.split():
            if len(w) < 3:
                continue
            if "".join(c for c in w if c not in weak) == core:
                return True
    # فرق حرف واحد (استبدال) للكلمات الطويلة — إملاء قريب
    if len(tok) >= 4:
        tl = len(tok)
        for w in hay.split():
            if len(w) == tl and sum(1 for a, b in zip(w, tok) if a != b) == 1:
                return True
    return False


def _filter_relevant(sources: list, query: str) -> list:
    """إسقاط نتائج البحث التي لا تشترك مع السؤال في كلمتين مفتاحيتين على الأقل
    (كلمة واحدة إن كان السؤال بكلمة مفتاحية وحيدة) — مع تطابق صرفي تقريبي.

    نحسب التوكنز من *جوهر البحث* (_search_query) لا من النص كاملاً: فسؤال مثل
    "من هو روميل؟ أعطِ سنة ميلاده ووفاته" يحوي توكنز زائدة (سنة/ميلاده/وفاته)
    ترفع حدّ التطابق المطلوب فتحذف النتيجة الصحيحة (إرفين رومل).
    """
    qtoks = _query_tokens(_search_query(query))
    if not qtoks:
        return []
    # التوازن: سؤال قصير (≤3 كلمات) — كلمة واحدة تكفي؛
    # سؤال أطول — كلمتان، بلا تراجع (التراجع كان يُدخل الغريب مثل "باريس")
    # ملاحظة: "القدس" بقيت لأنها تشترك فعلاً في "عاصمه"+"فلسطين" — صلة حقيقية
    need = 1 if len(qtoks) <= 3 else 2
    return _overlap(sources, qtoks, need)[:4]


def _overlap(sources: list, qtoks: set, need: int) -> list:
    kept = []
    for s in sources or []:
        hay = _norm_ar(f"{s.get('title', '')} {s.get('snippet', '')}")
        hits = sum(1 for t in qtoks if _fuzzy_contains(hay, t))
        if hits >= need:
            kept.append(s)
    return kept


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
    # 5) ملف معاينة مدمج: نبني/نحدّث preview.html ليشمل CSS/JS المنفصلة
    #    حتى لو أنشأ النموذج preview.html بنفسه — كانت تُترك بلا حقن فتظهر فارغة
    langs = {a["lang"] for a in artifacts}
    names = {a["name"] for a in artifacts}
    if "html" in langs or "css" in langs or "javascript" in langs:
        merged = _merge_web_preview(artifacts)
        if merged:
            if "preview.html" in names:
                for a in artifacts:
                    if a["name"] == "preview.html":
                        a["code"] = merged[:60000]
                        break
            else:
                artifacts.insert(0, {"name": "preview.html", "lang": "html", "code": merged})
    return artifacts


def _inject_before(html: str, fragment: str, container: str) -> str:
    """حقن fragment قبل نهاية حاوية — مع بدائل آمنة عند الردود المقصوصة"""
    m = re.search(r"</\s*" + container + r"\s*>", html, flags=re.I)
    if m:
        return html[: m.start()] + fragment + "\n" + html[m.start():]
    m2 = re.search(r"</\s*html\s*>", html, flags=re.I)
    if m2:
        return html[: m2.start()] + fragment + "\n" + html[m2.start():]
    return html + "\n" + fragment


def _merge_web_preview(artifacts: list) -> str:
    """دمج html + css + js في ملف واحد للمعاينة الحية.

    معالجات مهمة:
    - إغلاق أي وسم مفتوح (رد مقصوص على حد max_tokens) قبل الحقن، وإلا يبتلع
      السكربت اللاحق ويبقى بلا تنفيذ.
    - إزالة المراجع المحلية الميتة مثل <script src="game.js"> لأن الملف غير
      موجود داخل الإطار المعزول → كانت الصفحة تُرسم فارغة بلا أي أداء.
    - حقن CSS/JS دائماً حتى لو كانت الصفحة تحتوي وسوم <style>/<script> أخرى.
    """
    preview_p = next((a for a in artifacts if a["name"] == "preview.html"), None)
    html_p = preview_p or next((a for a in artifacts if a["lang"] == "html"), None)
    css_list = [a["code"] for a in artifacts if a["lang"] in ("css", "scss")]
    js_list = [
        a["code"]
        for a in artifacts
        if a["lang"] in ("javascript", "typescript", "jsx", "tsx")
    ]
    if not html_p and not css_list and not js_list:
        return ""

    base = html_p["code"] if html_p else (
        '<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head><body></body></html>"
    )

    # 1) إغلاق وسوم مفتوحة (يحصل عند قصّ الرد)
    if base.lower().count("<script") > base.lower().count("</script>"):
        base += "\n</script>"
    if base.lower().count("<style") > base.lower().count("</style>"):
        base += "\n</style>"

    # 2) إزالة المراجع المحلية الميتة (نحتفظ بـ http/https/data/blob)
    base = re.sub(
        r'<script\b[^>]*\bsrc\s*=\s*["\'](?!(?:https?:)?//|data:|blob:)[^"\']+["\']'
        r'[^>]*>\s*</script>',
        "",
        base,
        flags=re.I,
    )
    base = re.sub(
        r'<link\b[^>]*\brel\s*=\s*["\']stylesheet["\'][^>]*\bhref\s*=\s*["\']'
        r'(?!(?:https?:)?//|data:|blob:)[^"\']+["\'][^>]*/?>',
        "",
        base,
        flags=re.I,
    )

    # 3) حقن كل ملفات الأنماط
    css_code = "\n".join(c.strip() for c in css_list if c and c.strip())
    if css_code.strip() and css_code not in base:
        base = _inject_before(base, "<style>\n" + css_code + "\n</style>", "head")

    # 4) حقن كل ملفات السكربتات
    js_code = "\n".join(j.strip() for j in js_list if j and j.strip())
    if js_code.strip() and js_code not in base:
        base = _inject_before(base, "<script>\n" + js_code + "\n</script>", "body")

    return base

# ===== أدوات الوكيل (Agent Tools) — بحث وقراءة صفحات =====
# تُستخدم في وضع Agent (function calling) — Groq GPT-OSS 120B يدعمها (OpenAI-compatible)
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "البحث في الإنترنت عن معلومة أو موضوع. استخدمه عندما تحتاج لمعلومات حديثة أو حقائق أو مصادر.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "استعلام البحث"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "جلب محتوى صفحة ويب (نص) من رابط. استخدمه لقراءة مقال أو توثيق.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "رابط الصفحة"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "إنشاء ملف جديد (كود/نص) ضمن المشروع. استخدمه لكتابة ملفات HTML/CSS/JS/Python إلخ. يمكن إنشاء عدة ملفات.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "اسم الملف (مثال: index.html, style.css, app.py)"},
                    "language": {"type": "string", "description": "لغة الملف (html, css, javascript, python, ...)"},
                    "content": {"type": "string", "description": "محتوى الملف كاملاً"},
                },
                "required": ["name", "language", "content"],
            },
        },
    },
]

def _html_to_text(html: str) -> str:
    """استخراج نص من HTML (تجاهل script/style)"""
    from html.parser import HTMLParser

    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript"):
                self.skip += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self.skip > 0:
                self.skip -= 1

        def handle_data(self, data):
            if self.skip == 0:
                self.parts.append(data)

    p = _P()
    try:
        p.feed(html)
    except Exception:
        pass
    text = " ".join(" ".join(p.parts).split())
    return text


def tool_web_search(query: str) -> str:
    """بحث في DuckDuckGo (HTML) — يرجع قائمة نتائج"""
    query = (query or "").strip()
    if not query:
        return "استعلام فارغ."
    try:
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/", data=data,
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception as e:
        # fallback: ويكيبيديا
        try:
            return _wiki_search_text(query)
        except Exception:
            return f"تعذر البحث: {e}"

    # استخراج النتائج
    links = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.S)
    snippets = re.findall(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    if not snippets:
        snippets = re.findall(
            r'<div[^>]*class="result__snippet"[^>]*>(.*?)</div>', html, re.S)

    def _strip(t):
        t = re.sub(r"<[^>]+>", "", t)
        return " ".join(t.split())

    out = []
    for i, (href, title) in enumerate(links[:6]):
        # DuckDuckGo يُغلّف الرابط — استخراج uddg
        m = re.search(r"uddg=([^&]+)", href)
        real = urllib.parse.unquote(m.group(1)) if m else href
        if real.startswith("//"):
            real = "https:" + real
        snip = _strip(snippets[i]) if i < len(snippets) else ""
        out.append(f"{i+1}. {_strip(title)}\n   {real}\n   {snip}")
    if not out:
        return "لم تُعثر على نتائج."
    return "\n\n".join(out)


def _wiki_search_text(query: str) -> str:
    """fallback: بحث ويكيبيديا"""
    res = _web_search_uncached(query, limit=4, full_query=query)
    if not res:
        return "لم تُعثر على نتائج."
    return "\n\n".join(f"- {s['title']}: {s['snippet']} ({s['url']})" for s in res)


def tool_fetch_url(url: str) -> str:
    """جلب نص صفحة (محدود)"""
    url = (url or "").strip()
    if not url or not url.startswith("http"):
        return "رابط غير صالح."
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            data = r.read(200000)
        if "html" in ctype or b"<" in data[:200]:
            text = _html_to_text(data.decode("utf-8", "ignore"))
        else:
            text = data.decode("utf-8", "ignore")
        text = " ".join(text.split())
        if not text:
            return "الصفحة فارغة أو تعذّر استخراج النص."
        return text[:4000]
    except Exception as e:
        return f"تعذر جلب الصفحة: {e}"


# ===== مستويات التفكير (Reasoning Effort) =====
# المستخدم يختار المستوى، ونحن نترجمه إلى بارامترات يفهمها كل مزوّد:
#   off    = بلا تفكير إضافي (الأسرع/الأضعف)
#   low    = منخفض
#   medium = متوسط
#   high   = عالي (أداء أقوى)
#   max    = أقصى جهد + سقف رموز ومهلة أعلى (الأقوى أداءً)
#   auto   = نترك القرار للنموذج نفسه
THINK_LEVELS = ("auto", "off", "low", "medium", "high", "max")
_THINK_EFFORT = {"low": "low", "medium": "medium", "high": "high", "max": "high"}


def _thinking_kwargs(entry: dict, level: str) -> dict:
    """بارامترات التفكير المناسبة لمزوّد النموذج — {} إذا كانت غير مدعومة"""
    if level in ("", "auto", "off"):
        return {}
    effort = _THINK_EFFORT.get(level)
    if not effort:
        return {}
    provider = entry.get("provider")
    if provider == "openrouter":
        # OpenRouter يستخدم كائن reasoning موحّداً
        return {"extra_body": {"reasoning": {"effort": effort}}}
    if provider in ("groq", "cerebras", "gemini", "apinex", "colab", "together", "plugsky", "xkiro"):
        return {"reasoning_effort": effort}
    return {}


def _create_completion(client, base_kwargs: dict, think_kwargs: dict, timeout: int):
    """تنفيذ الطلب — وإن رفض المزوّد بارامترات التفكير نعيد المحاولة بدونها"""
    opts = {"timeout": timeout, "max_retries": 0}
    if think_kwargs:
        try:
            return client.with_options(**opts).chat.completions.create(
                **{**base_kwargs, **think_kwargs}
            )
        except OpenAIError as e:
            # 400/404/422 = المزوّد لا يعرف هذه البارامترات — نتجاهلها ونكمل
            if getattr(e, "status_code", None) not in (400, 404, 422):
                raise
    return client.with_options(**opts).chat.completions.create(**base_kwargs)




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
    # مستوى التفكير المطلوب (auto/off/low/medium/high/max)
    thinking = (data.get("thinking") or "auto").strip().lower()
    if thinking not in THINK_LEVELS:
        thinking = "auto"
    # البحث في الإنترنت قبل الجواب — مفعّل افتراضياً لتقليل الأجوبة الخاطئة
    do_search = data.get("web_search", True)
    do_search = True if do_search is None else bool(do_search)

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

    # === البحث في الإنترنت *قبل* الجواب (في كل الأوضاع) ===
    # الهدف: تقليل الأجوبة الخاطئة عبر إلزام النموذج بنتائج بحث حقيقية.
    query = _text_of(_extract_last_user(messages))
    # إزالة أوامر الصور/الفيديو من الاستعلام حتى لا يشوّش البحث
    for prefix in ("/image", "/img", "/video", "/vid", "صورة:", "ارسم:", "فيديو:", "مقطع:"):
        if query.startswith(prefix):
            query = query[len(prefix):].strip()

    # هل الطلب مهمة بناء كود؟ (نتائج ويكيبيديا لا تفيد الكود بل تشوّش النموذج)
    build_task = mode == "agent" and any(k in query.lower() for k in (
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

    # بوابة البحث الذكي: نبحث فقط عن الأسئلة المعرفية الحقيقية —
    # التحيات والكود والرياضيات والترجمة والإبداع والرأي لا تُبحث
    # (البحث عنها كان ينتج مصادر بلا علاقة بالجواب).
    # في وضع Agent: لا بحث تلقائي — الوكيل يقرر متى يبحث عبر أداة web_search
    use_tools = (mode == "agent")
    sources = []
    searched = False
    if (not use_tools) and do_search and not build_task and _needs_search(query):
        searched = True
        sources = _filter_relevant(
            web_search(_search_query(query), full_query=query), query)
    if sources:
        messages.append({"role": "system", "content": _search_context(sources, query)})
    elif searched:
        # بُحث فعلاً لكن دون نتائج مرتبطة — إبلاغ صريح للنموذج بدل اختلاق الحقائق
        messages.append({"role": "system", "content": (
            f"بُحث في الإنترنت (ويكيبيديا) عن: {query[:150]} — ولم تُعثر على "
            "نتائج مرتبطة بالسؤال. أجب من معلوماتك العامة، وإن كان السؤال يطلب "
            "حقيقة دقيقة (رقماً أو تاريخاً أو اسماً) لا تعرفها بثقة فقل صراحة "
            "إنك لا تعرفها ولا تخترعها. لا تذكر أي مصادر في جوابك."
        )})

    # === وضع Agent: قواعد تنفيذ المهام (برمجة/بناء) ===
    if build_task:
        messages.append({
            "role": "system",
            "content": (
                "أنت الآن وكيل بناء تنفيذي (Builder Agent) — مهمتك كتابة كود حقيقي كامل يعمل فوراً، لا شرح نظري. "
                "قواعد صارمة للإخراج: "
                "1) أخرج كل ملف داخل صندوق كود منفصل بصيغة ```لغة:اسم-الملف (مثال: ```html:index.html ثم الكود ثم ```). "
                "2) للموقع/الصفحة/اللعبة: ملف واحد index.html يحتوي كل شيء (CSS داخل <style> وJS داخل <script>) — كامل ويعمل بالفتح مباشرة، مع دعم عربي RTL إن كان المحتوى عربياً. "
                "3) للعبة: استخدم <canvas> أو DOM مع requestAnimationFrame، أزرار تحكم، ونقاط/مراحل. "
                "4) لا تختصر الكود أبداً بـ '...' أو 'باقي الكود' — اكتبه كاملاً حتى النهاية. "
                "5) بعد الصناديق اكتب سطراً واحداً فقط يشرح كيف تشغّل النتيجة. "
                "6) لديك أدوات بحث (web_search)، قراءة صفحات (fetch_url)، وإنشاء ملفات (create_file) — استخدمها: ابحث قبل الجواب عندما تحتاج لمعلومات حديثة، وأنشئ ملفات المشروع عبر create_file، واذكر المصادر."
            ),
        })
    # هل توجد صورة مرفقة في الرسائل؟ — عندها نمرّ على النماذج التي تقرأ الصور فقط
    has_image = any(
        m.get("role") == "user" and _valid_image(m.get("image"))
        for m in history[-MAX_HISTORY:]
    )

    # ===== خيار B: Al-Khwarizmi Flash بطل البرمجة، والأسئلة المعرفية لنموذج أدق =====
    # Flash ممتاز في الكود لكنه ضعيف في الحقائق الدقيقة. فنوجّه السؤال المعرفي
    # إلى نموذج أقوى. وFlash *لا* يبقى كبديل في هذا المسار: لو فشل المزوّد القوي
    # نُبلغ المستخدم بصراحة (503 أسفل) بدل إعطائه تخميناً من نموذج أضعف.
    routed = False
    route_reason = ""
    if requested == "al-khwarizmi" and requested in MODELS and _is_factual_query(query, build_task):
        target = _pick_factual_model(has_image)
        if target:
            requested = target
            routed = True
            route_reason = "سؤال معرفي — أجاب نموذج أدق مع مصادر من الإنترنت"

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
    priority = ("apinex", "plugsky", "xkiro", "gemini", "groq", "openrouter", "mistral",
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
    # 1.b) في المسار المعرفي: بدائل قوية مُتحقَّق منها قبل أي مزوّد عرضة للخطأ
    # (APInex/Cerebras تُرجع 402 وOpenRouter 429 — فلو سبقونا لأسقطنا الطلب)
    if routed:
        for mid in _FACTUAL_CHAIN:
            if mid in MODELS and (not has_image or MODELS[mid].get("vision")):
                _push(mid, MODELS[mid])
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
    agent_steps: list = []
    for mid, entry in ordered[:3]:   # النموذج المطلوب + بديلان
        key_slots = len(_keys_of(entry["provider"])) or 1
        for _slot in range(min(key_slots, 2)):   # مفتاحين بدل 3
            c, used_key = get_client_and_key(entry["provider"])
            try:
                eff_max = max_tokens
                if mode == "agent":
                    eff_max = max(eff_max, 4000)
                if thinking in ("high", "max"):
                    eff_max = max(eff_max, 6000)
                elif thinking in ("low", "medium"):
                    eff_max = max(eff_max, 3000)

                req_timeout = 45 if mode == "agent" else 12
                if thinking in ("high", "max"):
                    req_timeout = max(req_timeout, 75)
                elif thinking == "medium":
                    req_timeout = max(req_timeout, 40)
                if entry.get("provider") == "colab":
                    req_timeout = max(req_timeout, 180 if mode == "agent" else 90)

                base_kwargs = {
                    "model": entry["id"],
                    "messages": messages,
                    "temperature": min(temperature, 0.3) if sources else temperature,
                }
                if eff_max > 0:
                    base_kwargs["max_tokens"] = min(eff_max, 8000)

                this_use_tools = use_tools
                reply = ""
                total_tokens = 0
                steps_this: list = []
                created_files_this: list = []

                if this_use_tools:
                    tool_messages = [m for m in messages]
                    for _it in range(6):
                        call_kwargs = dict(base_kwargs)
                        call_kwargs["messages"] = tool_messages
                        call_kwargs["tools"] = AGENT_TOOLS
                        call_kwargs["tool_choice"] = "auto"
                        r = _create_completion(c, call_kwargs, _thinking_kwargs(entry, thinking), req_timeout)
                        total_tokens += (r.usage.total_tokens if r.usage else 0)
                        choice_msg = r.choices[0].message if r.choices else None
                        if choice_msg and getattr(choice_msg, "tool_calls", None):
                            tool_messages.append(choice_msg)
                            for tc in choice_msg.tool_calls:
                                try:
                                    args = json.loads(tc.function.arguments or "{}")
                                except Exception:
                                    args = {}
                                name = tc.function.name
                                if name == "web_search":
                                    res = tool_web_search(str(args.get("query", "")))
                                    steps_this.append({"type": "search", "query": str(args.get("query", "")), "result": res[:240]})
                                elif name == "fetch_url":
                                    res = tool_fetch_url(str(args.get("url", "")))
                                    steps_this.append({"type": "fetch", "url": str(args.get("url", "")), "result": res[:240]})
                                elif name == "create_file":
                                    fname = str(args.get("name", "file.txt"))
                                    lang = str(args.get("language", "text"))
                                    content = str(args.get("content", ""))
                                    created_files_this.append({"name": fname, "lang": lang, "code": content})
                                    steps_this.append({"type": "file", "name": fname, "result": f"تم إنشاء {fname} ({len(content)} حرف)"})
                                    res = f"تم إنشاء الملف {fname} بنجاح."
                                else:
                                    res = "أداة غير معروفة"
                                    steps_this.append({"type": "unknown", "name": name, "result": res})
                                tool_messages.append({"role": "tool", "tool_call_id": tc.id, "content": res})
                            continue
                        reply = (choice_msg.content if choice_msg else "") or ""
                        if not reply.strip() and choice_msg:
                            reply = getattr(choice_msg, "reasoning", "") or getattr(choice_msg, "reasoning_content", "") or ""
                        break
                    else:
                        try:
                            final_kwargs = dict(base_kwargs)
                            final_kwargs["messages"] = tool_messages + [{"role": "system", "content": "أجب الآن (بدون أدوات) بناءً على المعلومات المجموعة."}]
                            r = _create_completion(c, final_kwargs, _thinking_kwargs(entry, thinking), req_timeout)
                            total_tokens += (r.usage.total_tokens if r.usage else 0)
                            cm = r.choices[0].message if r.choices else None
                            reply = (cm.content if cm else "") or ""
                        except Exception:
                            pass
                else:
                    r = _create_completion(c, base_kwargs, _thinking_kwargs(entry, thinking), req_timeout)
                    total_tokens += (r.usage.total_tokens if r.usage else 0)
                    choice_msg = r.choices[0].message if r.choices else None
                    reply = (choice_msg.content if choice_msg else "") or ""
                    if not reply.strip() and choice_msg:
                        reply = getattr(choice_msg, "reasoning", "") or getattr(choice_msg, "reasoning_content", "") or ""

                try:
                    _record_user_tokens(session.get("email", ""), total_tokens)
                except Exception:
                    pass

                extracted = extract_artifacts(reply) if mode == "agent" else []
                artifacts = created_files_this if created_files_this else extracted
                # دمج: ملفات من الأدوات + ملفات مستخرجة من الرد (بدون تكرار)
                if created_files_this and extracted:
                    seen = {(a["name"], a["code"][:80]) for a in artifacts}
                    for a in extracted:
                        if (a["name"], a["code"][:80]) not in seen:
                            artifacts.append(a)
                            seen.add((a["name"], a["code"][:80]))
                agent_steps.extend(steps_this)
                return jsonify({
                    "reply": reply,
                    "model": mid,
                    "label": entry["label"],
                    "sources": sources,
                    "thinking": thinking,
                    "searched": searched,
                    "routed": routed,
                    "route_reason": route_reason,
                    "artifacts": artifacts,
                    "agent_steps": agent_steps,
                })
            except OpenAIError as e:
                last_error = e
                status = getattr(e, "status_code", None)
                # إن كان الفشل بسبب عدم دعم الأدوات — أعد المحاولة بدونها
                if this_use_tools and status in (400, 404, 422):
                    try:
                        fallback_kwargs = dict(base_kwargs)
                        # إزالة الأدوات
                        fallback_kwargs.pop("tools", None)
                        fallback_kwargs.pop("tool_choice", None)
                        r = _create_completion(c, fallback_kwargs, _thinking_kwargs(entry, thinking), req_timeout)
                        total_tokens = (r.usage.total_tokens if r.usage else 0)
                        cm = r.choices[0].message if r.choices else None
                        reply = (cm.content if cm else "") or ""
                        if not reply.strip() and cm:
                            reply = getattr(cm, "reasoning", "") or getattr(cm, "reasoning_content", "") or ""
                        try:
                            _record_user_tokens(session.get("email", ""), total_tokens)
                        except Exception:
                            pass
                        artifacts = extract_artifacts(reply) if mode == "agent" else []
                        return jsonify({
                            "reply": reply,
                            "model": mid,
                            "label": entry["label"],
                            "sources": sources,
                            "thinking": thinking,
                            "searched": searched,
                            "routed": routed,
                            "route_reason": route_reason,
                            "artifacts": artifacts,
                            "agent_steps": [],
                        })
                    except Exception:
                        pass
                if status in (400, 401, 402, 403, 404, 429, 503) or status is None:
                    if status in (401, 402, 403, 429):
                        _mark_key_down(entry["provider"], used_key)
                    elif status == 503:
                        _mark_key_down(entry["provider"], used_key, seconds=10)
                    elif status is None:
                        _mark_key_down(entry["provider"], used_key, seconds=15)
                    if status == 429:
                        rate_limited += 1
                        time.sleep(0.3)
                        continue
                    if status == 503:
                        time.sleep(0.5)
                    break
                break
            except Exception as e:
                last_error = e
                time.sleep(0.5)
                break

    print(f"خطأ API: {last_error}")
    # رسالة صادقة وواضحة حسب السبب
    if isinstance(last_error, OpenAIError) and getattr(last_error, "status_code", None) == 400 and has_image:
        return jsonify({
            "error": "النموذج المختار لا يدعم الصور — جرّب Al-Khwarizmi Flash أو Gemini 2.5 Flash"
        }), 400
    # النموذج الخاص على Colab غير متاح (الجلسة منقطعة أو النفق لم يُربط بعد)
    if requested in COLABC_MODEL_IDS and not _colab_is_live():
        return jsonify({
            "error": "الخوارزمي الخاص غير متاح حالياً — شغّل النوتبوك على Colab ليشتغل تلقائياً"
        }), 503
    return jsonify({
        "error": "النماذج المجانية مشبعّة حالياً — جرّب مرة ثانية بعد دقيقة"
    }), 503


# ===== توليد الصور عبر FLUX.1 (Pollinations) — مجاني بالكامل بدون أي مفتاح =====
IMAGE_MODELS = {
    "flux": {
        "label": "Al-Khwarizmi Art",
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
        ("plugsky", "plugsky-micro"),
        ("xkiro", "qwen/qwen-plus-2025-07-28:free"),
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

