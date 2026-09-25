"""اختبار نموذج واحد — التشغيل: python test_api.py <اسم_النموذج>"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

model = sys.argv[1] if len(sys.argv) > 1 else "gemini-flash-latest"

client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=12,
    max_retries=0,
)

try:
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "أنت 'الخوارزمي' مساعد ذكي عربي."},
            {"role": "user", "content": "من أنت؟ أجب بجملة واحدة"},
        ],
    )
    print(f"✅ {model} → {r.choices[0].message.content[:150]}")
except Exception as e:
    code = getattr(e, "status_code", "?")
    print(f"❌ {model} → [{code}] {str(e)[:150]}")
