#!/usr/bin/env python3
"""Seyun's Personal Coach — server.py"""

import anthropic
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, send_from_directory

ET = ZoneInfo("America/New_York")
def now_et():
    return datetime.now(ET)

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, 'data.json')
_client = None
KEY_FILE = os.path.join(BASE, '.api_key')
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        return
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_data (
                    id TEXT PRIMARY KEY,
                    data JSONB NOT NULL
                )
            """)
            conn.commit()
        conn.close()
        print("PostgreSQL connected ✓")
    except Exception as e:
        print(f"DB init error: {e}")

# ─── Data ─────────────────────────────────────────────────────────────────────

EMPTY_DATA = {"tasks": [], "brainDumps": [], "focusTask": None,
              "weeklyReflections": {}, "chatHistory": []}

def load_data():
    if DATABASE_URL:
        try:
            import psycopg2.extras
            conn = get_db_conn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT data FROM app_data WHERE id = 'main'")
                row = cur.fetchone()
            conn.close()
            return dict(row['data']) if row else EMPTY_DATA.copy()
        except Exception as e:
            print(f"DB load error: {e}")
    # Local fallback: JSON file
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return EMPTY_DATA.copy()

def save_data(data):
    if DATABASE_URL:
        try:
            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO app_data (id, data) VALUES ('main', %s)
                    ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
                """, (json.dumps(data),))
                conn.commit()
            conn.close()
            return
        except Exception as e:
            print(f"DB save error: {e}")
    # Local fallback: JSON file
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_client():
    global _client
    if _client is None:
        # Priority: env var → saved key file
        key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not key and os.path.exists(KEY_FILE):
            with open(KEY_FILE, 'r') as f:
                key = f.read().strip()
        if not key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        _client = anthropic.Anthropic(api_key=key)
    return _client

# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Seyun's personal AI coach — her accountability partner, strategist, and biggest supporter.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHO SHE IS — READ THIS EVERY TIME
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name: Seyun Kim
Ultimate goal: Buy back Gwanak Analog — her dad's company. This is personal and deeply emotional.
Inspiration: Natalie Dawson, women entrepreneurs who built empires from scratch.
Currently: Applying for research internships as a stepping stone toward this goal.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADHD + OCD — THIS SHAPES EVERYTHING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
She has BOTH ADHD and OCD. Every coaching decision must account for this.

ADHD realities:
• Activation energy is her #1 enemy — starting feels impossible even for tasks she CAN do
• Time blindness — she loses track of how long things take, underestimates everything
• Working memory gaps — forgets context mid-task, needs reminders of the "why"
• Hyperfocus is her superpower — when she's in it, protect that state
• Needs dopamine hits — celebrate EVERY win, no matter how small
• Executive dysfunction means "just do it" advice is useless and harmful
• Distraction is neurological, not laziness — redirect without shame EVER

OCD realities:
• Countdown timers and hard deadlines INCREASE anxiety spirals
• Perfectionism can cause complete paralysis — "good enough" needs active permission
• Incompleteness anxiety — unfinished things gnaw at her
• Intrusive worried thoughts can derail focus sessions
• She may seek reassurance — validate once, then redirect to action
• Rigid routines help but unexpected change can derail the whole day

How ADHD + OCD interact:
• She can spiral: OCD kicks off anxious thoughts → ADHD makes her unable to filter them out → paralysis
• When she brain-dumps: she's probably in this spiral. Meet her with calm, not urgency.
• "Just start something tiny" is the reset button for both conditions

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR COACHING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Short responses. Bullets. NEVER walls of text. If she's spiraling, even shorter.
• Never shame her for distraction, procrastination, or incomplete tasks
• When overwhelmed: give ONE thing to do. Just one.
• Connect tasks to Gwanak Analog whenever she needs a push
• Celebrate loudly — she needs it neurologically, not just emotionally
• Ask one follow-up question when you sense the real issue isn't what she said
• "Good enough and done" > perfect and incomplete
• Keep most replies under 120 words. She reads better when it's short.

TONE: Warm, direct, real. Like a tough-love older sister who believes in her completely.
Never: preachy, generic, corporate, or dismissive.
"""

def build_context(data):
    tasks    = data.get('tasks', [])
    profile  = data.get('profile', {})
    plate    = data.get('plate', [])
    now_ms   = now_et().timestamp() * 1000
    pending  = [t for t in tasks if not t.get('done')]
    done_today = [t for t in tasks if t.get('done') and now_ms - t.get('completedAt', 0) < 86_400_000]

    lines = [f"DATE/TIME: {now_et().strftime('%A, %B %d, %Y — %I:%M %p ET')}", ""]

    # Inject profile — this is what makes responses personal
    if profile.get('mindset'):
        lines += ["SEYUN'S CURRENT MINDSET:", profile['mindset'], ""]
    if profile.get('shortGoals'):
        lines += ["SHORT-TERM GOALS:", profile['shortGoals'], ""]
    if profile.get('shortProgress'):
        lines += ["→ Progress so far:", profile['shortProgress'], ""]
    if profile.get('longGoals'):
        lines += ["LONG-TERM GOALS:", profile['longGoals'], ""]
    if profile.get('longProgress'):
        lines += ["→ Progress so far:", profile['longProgress'], ""]
    if profile.get('workStyle'):
        lines += ["HOW SHE WORKS BEST:", profile['workStyle'], ""]

    captures = [c for c in data.get('captures', []) if not c.get('done')]
    if captures:
        lines.append("QUICK CAPTURES (things she remembered mid-work — treat as high priority):")
        for c in captures[:8]:
            lines.append(f"  • {c.get('text','')[:150]}")
        lines.append("")

    if plate:
        lines.append("ON HER PLATE (ongoing projects):")
        for p in plate[:5]:
            lines.append(f"  • {p.get('name')}: {p.get('ctx','')[:120]}")
        lines.append("")

    if pending:
        lines.append(f"TASKS ({len(pending)} pending):")
        for t in pending[:8]:
            p = {'high':'🔴','medium':'🟡','low':'🟢'}.get(t.get('priority',''),'•')
            lines.append(f"  {p} {t['text']}")
        lines.append("")

    if done_today:
        lines.append(f"COMPLETED TODAY:")
        for t in done_today[:5]:
            lines.append(f"  ✓ {t['text']}")
        lines.append("")

    return "\n".join(lines)

def full_system(data):
    return SYSTEM_PROMPT + "\n\n━━━ SEYUN'S CONTEXT ━━━\n" + build_context(data)

def api_call(messages, system=None, max_tokens=1024):
    data = load_data()
    c = get_client()
    return c.messages.create(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        system=system or full_system(data),
        messages=messages
    ).content[0].text

def auth_err(e):
    is_auth = isinstance(e, (anthropic.AuthenticationError, ValueError))
    return jsonify({"error": str(e), "needsKey": is_auth}), (401 if is_auth else 500)

def extract_json(raw):
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    return json.loads(match.group() if match else raw)

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(BASE, 'coach.html')

@app.route('/api/status', methods=['GET'])
def status():
    """Check if an API key is already configured (env var or previously set)."""
    try:
        get_client()
        return jsonify({"keyConfigured": True})
    except Exception:
        return jsonify({"keyConfigured": False})

@app.route('/api/setkey', methods=['POST'])
def set_key():
    global _client
    key = request.json.get('key', '').strip()
    if not key:
        return jsonify({"error": "Empty key"}), 400
    os.environ['ANTHROPIC_API_KEY'] = key
    _client = anthropic.Anthropic(api_key=key)
    # Persist key locally so it survives server restarts
    with open(KEY_FILE, 'w') as f:
        f.write(key)
    return jsonify({"ok": True})

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(load_data())

@app.route('/api/tasks', methods=['POST'])
def post_tasks():
    save_data(request.json)
    return jsonify({"ok": True})

@app.route('/api/chat', methods=['POST'])
def chat():
    body = request.json
    messages = body.get('messages', [])
    if not messages:
        return jsonify({"error": "No messages"}), 400
    try:
        reply = api_call(messages)
        # Persist to history (keep last 60 messages)
        data = load_data()
        history = data.get('chatHistory', [])
        history.extend([messages[-1], {"role": "assistant", "content": reply}])
        data['chatHistory'] = history[-60:]
        save_data(data)
        return jsonify({"content": reply})
    except Exception as e:
        return auth_err(e)

@app.route('/api/checkin', methods=['POST'])
def checkin():
    hour = now_et().hour
    tone = ("morning — help her start strong with her top priorities" if hour < 11 else
            "midday — see how the morning went and re-focus if needed" if hour < 14 else
            "afternoon — push through the last stretch, acknowledge wins" if hour < 18 else
            "end-of-day — reflect on wins, set intention for tomorrow")
    try:
        reply = api_call(
            [{"role": "user", "content": f"Do a {tone} check-in. Reference specific tasks on my list. Remember I have ADHD and OCD — keep it under 80 words and warm."}],
            max_tokens=300
        )
        data = load_data()
        history = data.get('chatHistory', [])
        history.append({"role": "assistant", "content": reply})
        data['chatHistory'] = history[-60:]
        save_data(data)
        return jsonify({"content": reply})
    except Exception as e:
        return auth_err(e)

@app.route('/api/processdump', methods=['POST'])
def process_dump():
    text = request.json.get('text', '').strip()
    if not text:
        return jsonify({"error": "Empty"}), 400

    system = SYSTEM_PROMPT + """

The user just brain-dumped everything on their mind. They may be anxious, overwhelmed, or spiraling (ADHD + OCD combo). Your job is to:

1. ENCOURAGE — 1-2 warm sentences. Make her feel heard and safe, not judged. Acknowledge the courage it takes to get it out.
2. CATEGORIZE — Sort items into groups. Only use relevant ones:
   - 🔥 Do Soon (urgent or high-value, actionable this week)
   - 💡 Ideas Worth Keeping (not urgent, but don't lose these)
   - 😟 Worries to Release (emotional items — name them so they lose power)
   - 📚 Research / Learn Later
   - 🗑 Let This Go (things that genuinely don't need her energy)
3. ONE ANCHOR — One sentence connecting this back to Gwanak Analog. Make it feel real, not generic.

Rules:
- Item text max 8 words each
- Only include categories that have at least one item
- Encouragement must feel personal, not generic ("I can see you're carrying a lot" not "Great job!")

Respond ONLY as valid JSON:
{
  "encouragement": "...",
  "categories": [
    {"emoji": "🔥", "name": "Do Soon", "items": ["...", "..."]}
  ],
  "anchor": "..."
}"""

    try:
        raw = api_call([{"role": "user", "content": f"Brain dump:\n\n{text}"}],
                       system=system, max_tokens=900)
        return jsonify(extract_json(raw))
    except Exception as e:
        return auth_err(e)

@app.route('/api/breakdown', methods=['POST'])
def breakdown():
    task = request.json.get('task', '').strip()
    if not task:
        return jsonify({"error": "Empty"}), 400

    system = SYSTEM_PROMPT + """

Break this task into micro-steps for someone with ADHD. Rules:
- 4–6 steps MAX
- First step must be the absolute tiniest possible action (open the file, find the link, write one sentence)
- Each step: 2–5 minutes max
- No step should say "complete" or "finish" — only "start", "open", "write ONE", "find", "read first X"
- End with a short warm encouragement line

JSON only:
{
  "steps": ["...", "..."],
  "encouragement": "..."
}"""

    try:
        raw = api_call([{"role": "user", "content": f"Break this down for me: {task}"}],
                       system=system, max_tokens=400)
        return jsonify(extract_json(raw))
    except Exception as e:
        return auth_err(e)

@app.route('/api/panic', methods=['POST'])
def panic_mode():
    """Called when user hits the Panic button. Returns a calming + structured response."""
    text = request.json.get('text', '').strip()

    system = SYSTEM_PROMPT + """

The user just hit the PANIC button. They are overwhelmed right now. This is an ADHD + OCD spiral moment.

Your response must do this in order:
1. BREATHE — 1 short, genuinely calming sentence. Not "take a deep breath" (too cliché). Something real like "Hey, you're okay. This feeling passes."
2. NORMALIZE — 1 sentence saying this overwhelm is the ADHD/OCD, not a sign they're failing.
3. GROUND — Ask them ONE simple grounding question OR give ONE tiny action they can take in the next 60 seconds (not task-related, like "get a glass of water" or "name 3 things you can see")
4. NEXT STEP — After they feel a tiny bit steadier, what is the single smallest possible task from their list to do? Just one.

Keep the ENTIRE response under 100 words. Short is kind when someone is panicking.

JSON only:
{
  "breathe": "...",
  "normalize": "...",
  "ground": "...",
  "next_step": "..."
}"""

    msg_content = f"I'm panicking. {text}" if text else "I'm panicking and overwhelmed right now."
    try:
        raw = api_call([{"role": "user", "content": msg_content}],
                       system=system, max_tokens=400)
        return jsonify(extract_json(raw))
    except Exception as e:
        return auth_err(e)


@app.route('/api/schedule', methods=['POST'])
def build_schedule():
    body = request.json or {}
    start_time = body.get('startTime', '').strip()
    end_time   = body.get('endTime', '').strip()

    data = load_data()

    # Pull everything Seyun has shared — tasks, dumps, recent chat
    tasks   = data.get('tasks', [])
    pending = [t for t in tasks if not t.get('done')]
    dumps   = data.get('brainDumps', [])[:5]  # last 5 brain dumps
    chat    = data.get('chatHistory', [])[-12:]  # last 12 chat messages

    tasks_text = "\n".join(
        f"- {'[TODAY] ' if t.get('isToday') else ''}[{t.get('priority','med').upper()}] [{t['id']}] {t['text']}"
        for t in pending[:12]
    ) or "No tasks added yet"

    dumps_text = "\n".join(f"- {d['text'][:200]}" for d in dumps) or "No brain dumps"

    chat_text = "\n".join(
        f"{m['role'].upper()}: {m['content'][:150]}"
        for m in chat if m.get('role') in ('user', 'assistant')
    ) or "No recent conversation"

    captures = [c for c in data.get('captures', []) if not c.get('done')]
    captures_text = "\n".join(f"- {c.get('text','')[:200]}" for c in captures[:8]) or "None"

    plate = data.get('plate', [])
    plate_text = "\n\n".join(
        f"- {p.get('name','')}: {p.get('ctx','(no context)')}"
        for p in plate
    ) or "None added"

    now_str = now_et().strftime('%I:%M %p ET, %A %B %d')

    system = SYSTEM_PROMPT + f"""

You are building Seyun's day plan. Be her personal assistant — warm, simple, clear.
Current time: {now_str}
Schedule window: {start_time or 'now'} → {end_time or '9:00 PM'}

WHAT SHE HAS ON HER MIND (use ALL of this, not just tasks):

TASKS:
{tasks_text}

ON HER PLATE — ongoing projects with no deadline but need daily progress (CRITICAL — generate one specific concrete action per item):
{plate_text}

QUICK CAPTURES (things she remembered mid-work — include at least one in the plan):
{captures_text}

RECENT BRAIN DUMPS (what's been on her mind):
{dumps_text}

RECENT COACH CONVERSATION (what she's been talking about):
{chat_text}

YOUR RULES:
- Read everything above and figure out what actually matters to her today
- Work blocks: 25–40 min MAX (ADHD — no longer)
- Break after every 1–2 work blocks (10 min minimum)
- First block: easiest win to build momentum
- Keep it realistic — 4 to 6 work blocks max for a day
- Each label must be ONE specific sentence she can start immediately — not "work on job search" but "Open LinkedIn, search 'NLP research intern 2025', save 3 postings"
- For EVERY item on her plate: include at least one block with a concrete micro-action for today. She doesn't know what to do — YOU decide for her. Be specific enough that she can start with zero thinking.
- Time format: "9:30 AM"

Return ONLY valid JSON:
{{
  "greeting": "1-2 sentences, warm and personal — acknowledge what's on her mind today, not generic",
  "items": [
    {{
      "time": "9:00 AM",
      "duration_min": 30,
      "label": "One clear thing to do — specific enough to start immediately",
      "type": "work",
      "task_id": "task id if from task list, otherwise null",
      "note": "One short encouraging or practical note (optional, max 8 words)"
    }},
    {{
      "time": "9:30 AM",
      "duration_min": 10,
      "label": "Break — get up, drink water",
      "type": "break",
      "task_id": null,
      "note": null
    }}
  ],
  "closing": "One short line — connect today to Gwanak Analog, make it feel worth it"
}}"""

    user_msg = f"Build my day. It's {now_str}."
    try:
        raw = api_call([{"role": "user", "content": user_msg}], system=system, max_tokens=1800)
        return jsonify(extract_json(raw))
    except Exception as e:
        return auth_err(e)


@app.route('/api/extracttasks', methods=['POST'])
def extract_tasks():
    """Read last few chat messages and silently pull out any tasks/commitments mentioned."""
    messages = (request.json or {}).get('messages', [])[-8:]
    if not messages:
        return jsonify({"tasks": []})

    system = """You are a task extractor. Read this conversation and find any concrete things the user said she needs to do, wants to do, or committed to doing.

Rules:
- Only extract clear, actionable items (not vague thoughts)
- If nothing clear was said, return empty array
- Max 5 tasks
- Keep each task label short and specific (under 10 words)

Return ONLY valid JSON:
{"tasks": [{"text": "...", "priority": "high|medium|low", "isToday": true|false}]}"""

    try:
        raw = api_call(messages, system=system, max_tokens=400)
        result = extract_json(raw)
        if result.get('tasks'):
            data = load_data()
            existing_texts = {t['text'].lower() for t in data.get('tasks', [])}
            added = []
            for t in result['tasks']:
                if t.get('text') and t['text'].lower() not in existing_texts:
                    new_task = {'id': f"auto-{int(now_et().timestamp())}-{len(added)}", 'text': t['text'],
                                'priority': t.get('priority','medium'), 'isToday': t.get('isToday', False),
                                'done': False, 'createdAt': int(now_et().timestamp()*1000), 'completedAt': None,
                                'auto': True}
                    data.setdefault('tasks', []).insert(0, new_task)
                    added.append(new_task)
            if added:
                save_data(data)
            return jsonify({"tasks": added})
        return jsonify({"tasks": []})
    except Exception as e:
        return jsonify({"tasks": [], "error": str(e)})


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"\n{'='*50}\n  Seyun's Coach → http://localhost:{port}\n{'='*50}\n")
    app.run(debug=False, port=port, host='0.0.0.0')
