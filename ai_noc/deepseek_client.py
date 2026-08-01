"""DeepSeek API — satu panggilan, nol seremoni."""
import os, json, urllib.request

URL = f"{os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')}/chat/completions"

def _get_key():
    """Read API key: env var first, DB settings fallback."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    try:
        from web.database import execute_query
        row = execute_query("SELECT setting_value FROM settings WHERE setting_key='deepseek_api_key'", fetch_one=True)
        if row and row.get("setting_value"):
            return row["setting_value"]
    except Exception:
        pass
    return ""

def chat(system, user, max_tokens=500):
    key = _get_key()
    if not key:
        return None
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.3, "max_tokens": max_tokens, "stream": False
    }).encode()
    req = urllib.request.Request(URL, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]
