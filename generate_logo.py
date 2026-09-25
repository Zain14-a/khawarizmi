"""
توليد شعار للخوارزمي عبر Gemini Image API
التشغيل: python generate_logo.py <اسم_النموذج> <اسم_ملف_الإخراج>
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

KEY = os.getenv("GEMINI_API_KEY")
model = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash-image"
out_name = sys.argv[2] if len(sys.argv) > 2 else "logo.png"

PROMPT = (
    "Flat minimal app icon logo for an Arabic AI assistant. "
    "A single geometric letter mark inspired by the Arabic letter kha (خ), "
    "constructed from clean geometric lines, inside a rounded square. "
    "Flat design, solid colors only: deep teal #0f766e background and white mark. "
    "No gradients, no neon, no glow, no text, no letters other than the mark, "
    "centered composition, generous padding, professional tech company style, "
    "like a modern SaaS product logo icon."
)


def generate(model_id: str) -> bytes | None:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_id}:generateContent?key={KEY}"
    )
    body = json.dumps({"contents": [{"parts": [{"text": PROMPT}]}]}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=50) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    return None


try:
    img = generate(model)
    if img:
        static_dir = os.path.join(BASE_DIR, "static")
        os.makedirs(static_dir, exist_ok=True)
        out_path = os.path.join(static_dir, out_name)
        with open(out_path, "wb") as f:
            f.write(img)
        print(f"OK|{model}|{out_name}|{len(img)} bytes")
    else:
        print(f"NOIMG|{model}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")
    print(f"FAIL|{model}|HTTP{e.code}|{body[:400]}")
except Exception as e:
    print(f"FAIL|{model}|{type(e).__name__}|{str(e)[:250]}")
