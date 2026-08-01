"""DeepSeek API — satu panggilan, nol seremoni."""
import os, json, urllib.request, re

URL = f"{os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')}/chat/completions"

# Knowledge base milik owner: ai_noc/knowledge/*.md atau *.txt
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'knowledge')
# Batas karakter yang ikut ke prompt. Naikkan via env kalau knowledge bertambah.
KNOWLEDGE_BUDGET = int(os.environ.get('KNOWLEDGE_BUDGET_CHARS', '12000'))
KNOWLEDGE_TOP_N = int(os.environ.get('KNOWLEDGE_TOP_N', '2'))

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

def _retrieve_knowledge(question):
    """CEK KNOWLEDGE DULU: pilih file yang paling relevan dgn pertanyaan (skor kata kunci).

    Kata kunci = kata >= 4 huruf dari pertanyaan; skor file = berapa kali kata itu
    muncul di file. Ambil top N yang skornya > 0. ponytail: skor naif kata kunci,
    ganti ke embeddings kalau knowledge sudah > ~100 file / sering salah pilih.
    """
    try:
        files = [f for f in sorted(os.listdir(KNOWLEDGE_DIR)) if f.endswith(('.md', '.txt'))]
    except OSError:
        return ""
    if not files:
        return ""
    words = set(w for w in re.findall(r'[a-z0-9]+', question.lower()) if len(w) >= 4)
    if not words:
        return ""
    scored = []
    for f in files:
        try:
            with open(os.path.join(KNOWLEDGE_DIR, f), encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            lower = text.lower()
            score = sum(lower.count(w) for w in words)
            scored.append((score, text))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[0])
    picked = [t for s, t in scored[:KNOWLEDGE_TOP_N] if s > 0]
    return "\n\n".join(picked)[:KNOWLEDGE_BUDGET]

def chat(system, user, max_tokens=500):
    key = _get_key()
    if not key:
        return None
    knowledge = _retrieve_knowledge(user)
    if knowledge:
        system = (
            "ATURAN: cek PENGETAHUAN TEKNIS di bawah DULU sebelum menjawab. "
            "Kalau jawaban ada di pengetahuan → pakai itu. Kalau tidak ada → katakan "
            "'tidak ada di catatan saya' dan jangan mengarang.\n\n"
            "PENGETAHUAN TEKNIS MILIK OWNER (relevan dgn pertanyaan):\n"
            f"{knowledge}\n\n---\n\n{system}"
        )
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.3, "max_tokens": max_tokens, "stream": False
    }).encode()
    req = urllib.request.Request(URL, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]
