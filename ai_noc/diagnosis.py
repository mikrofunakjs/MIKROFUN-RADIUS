"""AI diagnosis — symptom + DB context → DeepSeek root cause analysis."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_noc.deepseek_client import chat as ai
from web.database import execute_query


def _user_context(username):
    """Gather all DB context for a given user. Returns dict or None."""
    user = execute_query(
        """SELECT c.username, c.name AS full_name, c.phone, c.status, c.due_date,
                  p.name AS profile, p.rate_limit,
                  r.name AS router, r.status AS router_status
           FROM customers c
           LEFT JOIN profiles p ON c.profile_id = p.id
           LEFT JOIN routers r ON c.router_id = r.id
           WHERE c.username = %s""",
        (username,), fetch_one=True
    )
    if not user:
        return None

    # Active session
    sess = execute_query(
        """SELECT nas_ip, mac_address, framedipaddress,
                  TIMESTAMPDIFF(MINUTE, updated_at, NOW()) AS minutes_idle
           FROM active_sessions WHERE username = %s""",
        (username,), fetch_one=True
    )

    # Recent traffic (last 30 min)
    traffic = execute_query(
        """SELECT SUM(acctoutputoctets) AS out_bytes, SUM(acctinputoctets) AS in_bytes,
                  MAX(snapshot_time) AS last_seen
           FROM radacct_snapshots
           WHERE username = %s AND snapshot_time >= DATE_SUB(NOW(), INTERVAL 30 MINUTE)""",
        (username,), fetch_one=True
    )

    # Recent auth failures
    auth_fails = execute_query(
        """SELECT COUNT(*) AS cnt FROM radpostauth
           WHERE username = %s AND reply = 'Access-Reject'
             AND authdate >= DATE_SUB(NOW(), INTERVAL 1 HOUR)""",
        (username,), fetch_one=True
    )

    return {
        "user": user,
        "session": sess,
        "traffic": traffic,
        "auth_failures": auth_fails.get("cnt", 0) if auth_fails else 0,
    }


def _global_context():
    """Quick system-wide stats."""
    online = execute_query("SELECT COUNT(*) as cnt FROM active_sessions", fetch_one=True)
    routers = execute_query(
        "SELECT COUNT(*) as cnt FROM routers WHERE status='offline'", fetch_one=True
    )
    return {
        "online_users": online["cnt"] if online else 0,
        "offline_routers": routers["cnt"] if routers else 0,
    }


def diagnose(symptom, username=None):
    """
    Diagnose a network issue. If username is provided, includes full user context.

    Returns: {"diagnosis": str, "confidence": int, "context_used": list}
    """
    global_ctx = _global_context()
    user_ctx = _user_context(username) if username else None

    parts = [f"Gejala: {symptom}"]
    parts.append(f"System: {global_ctx['online_users']} user online, "
                 f"{global_ctx['offline_routers']} router offline")

    if user_ctx:
        u = user_ctx["user"]
        parts.append(f"User: {u['full_name']} ({u['username']}), status={u['status']}, "
                     f"due_date={u['due_date']}, profile={u['profile']} ({u['rate_limit']}), "
                     f"router={u['router']} ({u['router_status']})")
        if user_ctx["session"]:
            s = user_ctx["session"]
            parts.append(f"Session: IP={s['framedipaddress']}, MAC={s['mac_address']}, "
                         f"idle={s['minutes_idle']}min, NAS={s['nas_ip']}")
        else:
            parts.append("Session: NOT ONLINE")
        if user_ctx["traffic"] and user_ctx["traffic"]["out_bytes"]:
            t = user_ctx["traffic"]
            mb = round((t["out_bytes"] + t["in_bytes"]) / 1_048_576, 2)
            parts.append(f"Traffic 30min: {mb}MB, last seen: {t['last_seen']}")
        if user_ctx["auth_failures"]:
            parts.append(f"Auth failures (1h): {user_ctx['auth_failures']}x")

    system_prompt = (
        "Anda NOC engineer MikroTik ISP. Diagnosis dalam Bahasa Indonesia. "
        "Format JSON: {\"diagnosis\": \"...\", \"root_cause\": \"...\", "
        "\"confidence\": 0-100, \"steps\": [\"langkah 1\", ...], "
        "\"auto_fix_possible\": true/false}. "
        "Analisa dari data yang diberikan. Confidence <60 jika data kurang. "
        "Jawab HANYA JSON, tanpa markdown."
    )

    result = ai(system_prompt, "\n".join(parts), max_tokens=600)

    if not result:
        return {"diagnosis": "AI tidak tersedia (API key?)", "confidence": 0, "context_used": []}

    try:
        import json
        parsed = json.loads(result)
    except json.JSONDecodeError:
        parsed = {"diagnosis": result, "confidence": 50, "context_used": []}

    parsed["context_used"] = [p.split(":")[0] for p in parts]
    return parsed


# ponytail: demo() fails if core path broken, no test framework needed
if __name__ == "__main__":
    r = diagnose("Internet lambat", username=None)
    assert "diagnosis" in r, "diagnose() returned no diagnosis key"
    print("OK — diagnosis engine functional")
    print(f"  Sample: {r['diagnosis'][:120]}...")
