"""
روبوت محادثة ذكي — يدعم Gemini (مجاني) / Groq (مجاني) / OpenAI (مدفوع)
يشغّل من الترمينال ويتذكر سياق المحادثة
"""

import os
import sys
from openai import OpenAI, OpenAIError
from dotenv import load_dotenv

# إصلاح طباعة العربي والإيموجي على ترمينال ويندوز
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# تحميل متغيرات البيئة من ملف .env (بالمسار الكامل — مهم على الاستضافات مثل PythonAnywhere)
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_FILE)

# مزوّدو الخدمة المدعومون — gemini و groq مجانيان 100%
PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.5-flash",
        # نماذج احتياطية إذا النموذج الأساسي مشغول أو وصل للحد اليومي
        "fallbacks": ["gemini-2.5-flash-lite"],
        "key_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "openai/gpt-oss-120b",
        "fallbacks": ["openai/gpt-oss-20b"],
        "key_url": "https://console.groq.com/keys",
    },
    "openai": {
        "base_url": None,
        "default_model": "gpt-4o-mini",
        "fallbacks": [],
        "key_url": "https://platform.openai.com/api-keys",
    },
}

PROVIDER = os.getenv("PROVIDER", "gemini").strip().lower()
if PROVIDER not in PROVIDERS:
    print(f"⚠️ مزوّد غير معروف: {PROVIDER}")
    print(f"   المتاح: {', '.join(PROVIDERS)}")
    sys.exit(1)

API_KEY = os.getenv(f"{PROVIDER.upper()}_API_KEY", "")
MODEL = os.getenv("MODEL") or PROVIDERS[PROVIDER]["default_model"]

# قائمة النماذج المرشحة بالترتيب: الأساسي ثم الاحتياطية (بدون تكرار)
MODEL_CANDIDATES = list(dict.fromkeys([MODEL, *PROVIDERS[PROVIDER]["fallbacks"]]))

# شخصية البوت - عدّلها حسب ما بدك
SYSTEM_PROMPT = (
    "أنت 'الخوارزمي' — مساعد ذكاء اصطناعي عربي، سُمّيت تيمناً بعالم الرياضيات "
    "محمد بن موسى الخوارزمي مؤسس علم الخوارزميات. تجيب بالعربية بشكل واضح "
    "ومختصر، وتساعد المستخدم في أي موضوع يطلبه."
)


def create_client() -> OpenAI:
    """إنشاء عميل API مع التحقق من وجود المفتاح"""
    if not API_KEY or API_KEY == "ضع-مفتاحك-هنا":
        print(f"❌ لم يتم العثور على مفتاح {PROVIDER.upper()} API!")
        print("الخطوات:")
        print(f"  1. اذهب إلى {PROVIDERS[PROVIDER]['key_url']}")
        print("  2. أنشئ مفتاح جديد (مجاني وبدون بطاقة ائتمانية)")
        print("  3. افتح ملف .env والصق المفتاح مكان: ضع-مفتاحك-هنا")
        sys.exit(1)
    return OpenAI(
        api_key=API_KEY,
        base_url=PROVIDERS[PROVIDER]["base_url"],
        timeout=30,
        max_retries=1,
    )


def chat(client: OpenAI, messages: list[dict], user_input: str) -> str:
    """إرسال رسالة وإرجاع الرد — مع تبديل تلقائي لنموذج احتياطي عند الضغط/الحد"""
    messages.append({"role": "user", "content": user_input})

    last_error: OpenAIError | None = None
    for model in MODEL_CANDIDATES:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
            )
            reply = response.choices[0].message.content
            messages.append({"role": "assistant", "content": reply})
            return reply
        except OpenAIError as e:
            last_error = e
            # 429 = تجاوز الحد، 404 = نموذج غير موجود، 503 = ضغط مؤقت
            if getattr(e, "status_code", None) in (429, 404, 503):
                continue
            raise

    raise last_error  # كل النماذج فشلت


def main() -> None:
    client = create_client()

    # سجل المحادثة (الذاكرة)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=" * 50)
    print("🤖 الخوارزمي — روبوت المحادثة الذكي")
    print(f"   المزوّد: {PROVIDER} | النموذج: {MODEL}")
    print("   اكتب 'خروج' أو 'exit' لإنهاء المحادثة")
    print("=" * 50)

    while True:
        try:
            user_input = input("\nأنت: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 إلى اللقاء!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("خروج", "exit", "quit"):
            print("👋 إلى اللقاء!")
            break

        try:
            reply = chat(client, messages, user_input)
            print(f"\n🤖 الخوارزمي: {reply}")
        except OpenAIError as e:
            if getattr(e, "status_code", None) == 429:
                print("\n⏳ وصلت للحد المجاني — انتظر دقيقة وحاول مرة أخرى")
            else:
                print(f"\n⚠️ خطأ من {PROVIDER.upper()}: {e}")
        except Exception as e:
            print(f"\n⚠️ خطأ غير متوقع: {e}")


if __name__ == "__main__":
    main()
