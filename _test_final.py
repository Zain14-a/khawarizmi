import json, urllib.request, http.cookiejar, time

BASE = "https://khawarizmi-8fl4.onrender.com"
time.sleep(115)
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def call(url, payload=None, method=None, tries=3):
    last = None
    for i in range(tries):
        try:
            body = json.dumps(payload).encode('utf-8') if payload is not None else None
            req = urllib.request.Request(url, data=body, method=method or ('POST' if body else 'GET'),
                                         headers={'Content-Type': 'application/json'})
            return json.loads(op.open(req, timeout=150).read().decode('utf-8'))
        except Exception as e:
            last = e
            time.sleep(6)
    return {"error": str(last)}

print("تسجيل:", call(BASE + "/api/register", {"email": "finallive@gmail.com", "password": "123456"}))

# نص — يجب أن يرد عبر Groq (OpenRouter و Gemini مشبعان)
r = call(BASE + "/api/chat", {"messages": [{"role": "user", "content": "مرحبا كيف حالك"}],
                              "model": "khwarizmi-flash", "mode": "chat", "temperature": 0.7, "max_tokens": 80})
print("\nنص → الحالة:", r.get("status", r.get("model") or r.get("error", "")))
print("النموذج الفعلي:", r.get("label"), "| الرد:", (r.get("reply") or "")[:80])

# صورة — متوقع فشل مؤقت اليوم (المزوّدان الداعمان للرؤية مشبعان) لكن برسالة صادقة
TINY = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
r2 = call(BASE + "/api/chat", {"messages": [{"role": "user", "content": "ما لونها؟", "image": TINY}],
                               "model": "khwarizmi-flash", "mode": "chat", "temperature": 0.7, "max_tokens": 80})
print("\nصورة → النموذج:", r2.get("model") or r2.get("error", ""))
print("الرد:", (r2.get("reply") or r2.get("error") or "")[:120])