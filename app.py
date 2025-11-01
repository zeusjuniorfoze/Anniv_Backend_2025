from flask import Flask, request, jsonify
from datetime import datetime
import random, re, os, json
from html import escape as html_escape
from PIL import Image
from io import BytesIO
import firebase_admin
from firebase_admin import credentials, db

# ---------------------------------------------------------------------
# 🔧 1. Création automatique de la clé Firebase AVANT toute initialisation
# ---------------------------------------------------------------------
if os.getenv("FIREBASE_KEY_JSON"):
    try:
        key_content = json.loads(os.getenv("FIREBASE_KEY_JSON"))
        os.makedirs("config", exist_ok=True)
        with open("config/serviceAccountKey.json", "w") as f:
            json.dump(key_content, f)
        print("✅ serviceAccountKey.json recréé avec succès !")
    except Exception as e:
        print("⚠️ Erreur lors de la création du fichier Firebase :", e)
else:
    print("⚠️ Variable FIREBASE_KEY_JSON non trouvée dans Render !")

# ---------------------------------------------------------------------
# 🔥 2. Initialisation Firebase
# ---------------------------------------------------------------------
SERVICE_KEY_PATH = "config/serviceAccountKey.json"
DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://android-92c2b-default-rtdb.firebaseio.com")

cred = credentials.Certificate(SERVICE_KEY_PATH)
firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})

# ---------------------------------------------------------------------
# 🚀 3. Application Flask
# ---------------------------------------------------------------------
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS, PUT, DELETE"
    return response

# Données dynamiques
DEFAULT_CELEBRANT = os.getenv("CELEBRANT", "Junior")
UPLOADED_PHOTOS = []

# ---------------------------------------------------------------------
# Fonctions utilitaires (inchangées)
# ---------------------------------------------------------------------
def build_anecdotes(celebrant: str):
    return [
        f"{celebrant} a déjà compilé un gâteau en .exe",
        f"On dit que {celebrant} ne vieillit pas, {celebrant} fait juste des updates",
        f"Si tu lis ça, c'est que tu tiens à {celebrant}",
        f"{celebrant} peut déboguer du code les yeux fermés",
        f"Le café préféré de {celebrant} : Binary Brew"
    ]

def build_quiz(celebrant: str):
    return [
        {"question": f"Langage préféré de {celebrant} ? (a) PHP (b) Python (c) JS", "answer": "b"},
        {"question": f"{celebrant} préfère : (a) coder (b) manger (c) dormir", "answer": "a"},
        {"question": f"Année de naissance de {celebrant} ? (a) 1990 (b) 1995 (c) 2000", "answer": "b"},
    ]

def get_user_by_name(name: str):
    ref = db.reference("users")
    snap = ref.order_by_child("name").equal_to(name).get()
    if snap:
        user_id = list(snap.keys())[0]
        user_data = snap[user_id]
        return user_id, user_data
    return None, None

def create_user(name: str):
    ref = db.reference("users")
    new_ref = ref.push({
        "name": name,
        "step": "quiz_q1",
        "score": 0,
        "created_at": datetime.utcnow().isoformat(),
    })
    return new_ref.key

def update_user(user_id: str, data: dict):
    ref = db.reference(f"users/{user_id}")
    ref.update(data)

def sanitize_text(s: str, max_len: int = 300) -> str:
    s = (s or "").strip()
    if len(s) > max_len:
        s = s[:max_len]
    return html_escape(s, quote=False)



# ---------- Wishes ----------
def add_wish(name: str, message: str):
    ref = db.reference("wishes")
    new_ref = ref.push(
        {
            "name": name,
            "message": message,
            "hearts": 0,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    return new_ref.key


def list_wishes():
    ref = db.reference("wishes")
    data = ref.get() or {}
    items = []
    for k, v in data.items():
        v = v or {}
        v["id"] = k
        items.append(v)
    # Tri par date de création décroissante (du plus récent au plus ancien)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items

@app.route("/wishes", methods=["GET", "POST", "OPTIONS"])
def wishes():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    if request.method == "GET":
        return jsonify({"wishes": list_wishes()})
    
    data = request.get_json() or {}
    name = sanitize_text(data.get("name"), 40)
    message = sanitize_text(data.get("message"), 2000)
    if not name or not message:
        return jsonify({"error": "name and message required"}), 400
    add_wish(name, message)
    return jsonify({"ok": True})


@app.route("/wishes/heart", methods=["POST", "OPTIONS"])
def wish_heart():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    data = request.get_json() or {}
    wish_id = (data.get("id") or "").strip()
    if not wish_id:
        return jsonify({"error": "id required"}), 400
    ref = db.reference(f"wishes/{wish_id}/hearts")
    current = ref.get() or 0
    ref.set(int(current) + 1)
    return jsonify({"ok": True, "hearts": int(current) + 1})


# ---------- Leaderboard ----------
def get_or_create_user_by_name(name: str):
    uid, u = get_user_by_name(name)
    if uid is None:
        uid = create_user(name)
        u = {"name": name, "step": "quiz_q1", "score": 0}
    return uid, u


@app.route("/leaderboard/score", methods=["POST", "OPTIONS"])
def lb_score():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    data = request.get_json() or {}
    name = sanitize_text(data.get("name"), 40)
    delta = int(data.get("delta", 0))
    if not name or delta == 0:
        return jsonify({"error": "name and non-zero delta required"}), 400
    user_id, user = get_or_create_user_by_name(name)
    lref = db.reference(f"leaderboard/{user_id}")
    entry = lref.get() or {"name": user.get("name", name), "score": 0}
    entry["score"] = int(entry.get("score", 0)) + delta
    lref.set(entry)
    return jsonify({"ok": True, "entry": {"user_id": user_id, **entry}})


@app.route("/leaderboard/top", methods=["GET", "OPTIONS"])
def lb_top():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    data = db.reference("leaderboard").get() or {}
    items = []
    for uid, v in data.items():
        v = v or {}
        v["user_id"] = uid
        items.append(v)
    items.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    return jsonify({"top": items[:10]})


# ---------- Polls ----------
@app.route("/polls/<poll_id>", methods=["GET", "POST", "OPTIONS"])
def polls(poll_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    pref = db.reference(f"polls/{poll_id}")
    if request.method == "GET":
        poll = pref.get() or {}
        # init default poll if empty
        if not poll or not poll.get("options"):
            default_q = "Quel gateau pour Junior ?"
            default_opts = {"opt1": {"label": "Choco"}, "opt2": {"label": "Vanille"}, "opt3": {"label": "Fraise"}}
            pref.set({"question": default_q, "options": default_opts})
            poll = pref.get() or {}
        opts = (poll.get("options") or {})
        counts = {k: len((v.get("votes") or {})) for k, v in opts.items()}
        poll["counts"] = counts
        return jsonify({"poll": poll})
    
    data = request.get_json() or {}
    action = (data.get("action") or "").strip()
    if action == "create":
        question = sanitize_text(data.get("question"), 120)
        options = data.get("options") or []
        opts = {}
        for idx, label in enumerate(options):
            lid = f"opt{idx+1}"
            opts[lid] = {"label": sanitize_text(str(label), 60)}
        pref.set({"question": question, "options": opts})
        return jsonify({"ok": True})
    elif action == "vote":
        name = sanitize_text(data.get("name"), 40)
        option_id = (data.get("option_id") or "").strip()
        if not name or not option_id:
            return jsonify({"error": "name and option_id required"}), 400
        user_id, _ = get_or_create_user_by_name(name)
        vref = db.reference(f"polls/{poll_id}/options/{option_id}/votes/{user_id}")
        vref.set(True)
        return jsonify({"ok": True})
    return jsonify({"error": "invalid action"}), 400


# ---------- Memory game ----------
@app.route("/games/memory/best", methods=["GET", "POST", "OPTIONS"])
def memory_best():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    if request.method == "GET":
        name = sanitize_text(request.args.get("name", ""), 40)
        user_best = None
        if name:
            uid, _ = get_or_create_user_by_name(name)
            uref = db.reference(f"games/memory/{uid}")
            u = uref.get() or {}
            ub = u.get("best_time_ms")
            if isinstance(ub, int):
                user_best = ub
        all_ref = db.reference("games/memory").get() or {}
        global_best = None
        for _uid, val in (all_ref or {}).items():
            if not isinstance(val, dict):
                continue
            b = val.get("best_time_ms")
            if isinstance(b, int):
                global_best = b if global_best is None else min(global_best, b)
        return jsonify({"ok": True, "user_best_ms": user_best, "global_best_ms": global_best})
    data = request.get_json() or {}
    name = sanitize_text(data.get("name"), 40)
    best_ms = int(data.get("best_time_ms", 0))
    if not name or best_ms <= 0:
        return jsonify({"error": "name and best_time_ms required"}), 400
    user_id, _ = get_or_create_user_by_name(name)
    ref = db.reference(f"games/memory/{user_id}")
    cur = ref.get() or {}
    prev = cur.get("best_time_ms")
    if not isinstance(prev, int) or best_ms < prev:
        ref.set({"best_time_ms": best_ms})
        prev = best_ms
    return jsonify({"ok": True, "best_time_ms": prev})

# ---------- NOUVEAU: Galerie Photo ----------
@app.route("/gallery", methods=["GET", "POST", "OPTIONS"])
def gallery():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    
    if request.method == "GET":
        # Retourner les photos de la galerie
        ref = db.reference("gallery")
        photos_data = ref.get() or {}
        photos = []
        for pid, photo in photos_data.items():
            photo = photo or {}
            photo["id"] = pid
            photos.append(photo)
        photos.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return jsonify({"photos": photos})
    
    # POST - Upload d'une nouvelle photo
    try:
        data = request.get_json() or {}
        image_data = data.get("image")  # base64
        caption = sanitize_text(data.get("caption", "Photo partagée"), 100)
        name = sanitize_text(data.get("name", "Invité"), 40)
        
        if not image_data:
            return jsonify({"error": "image data required"}), 400
        
        # Validation basique de l'image
        if not image_data.startswith('data:image/'):
            return jsonify({"error": "invalid image format"}), 400
        
        # Stocker dans Firebase
        ref = db.reference("gallery")
        new_photo = ref.push({
            "caption": caption,
            "uploaded_by": name,
            "created_at": datetime.utcnow().isoformat(),
            "image_data": image_data  # En production, stocker dans Cloud Storage
        })
        
        return jsonify({"ok": True, "photo_id": new_photo.key})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- NOUVEAU: Compte à rebours ----------
@app.route("/countdown", methods=["GET", "OPTIONS"])
def get_countdown():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    
    # Date du prochain anniversaire (exemple)
    next_birthday = datetime(2024, 12, 25)  # À adapter
    now = datetime.utcnow()
    diff = next_birthday - now
    
    if diff.total_seconds() <= 0:
        return jsonify({
            "active": False,
            "message": "🎉 C'est l'anniversaire aujourd'hui ! 🎉"
        })
    
    return jsonify({
        "active": True,
        "days": max(0, diff.days),
        "hours": max(0, diff.seconds // 3600),
        "minutes": max(0, (diff.seconds % 3600) // 60),
        "next_birthday": next_birthday.isoformat()
    })


# ---------- Chat principal ----------
@app.route("/message", methods=["POST", "OPTIONS"])
def message():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    provided_name = (data.get("name") or "").strip()
    celebrant = (data.get("celebrant") or DEFAULT_CELEBRANT).strip() or DEFAULT_CELEBRANT
    ANECDOTES = build_anecdotes(celebrant)
    QUIZ = build_quiz(celebrant)

    replies = []
    filter_image = None

    tl = text.lower()

    # Commandes globales
    if tl in {"aide", "help", "?"}:
        replies.append("Commandes disponibles :")
        replies.append("- 'anecdote' : une anecdote sur le célébré")
        replies.append("- 'bougies'  : souffler les bougies")
        replies.append("- 'musique'  : chanson d'anniversaire")
        replies.append("- 'carte'    : petit message")
        replies.append("- 'rejouer'  : recommencer le quiz")
        replies.append("- 'galerie'  : voir les photos")
        replies.append("- 'compte'   : voir le compte à rebours")
        return jsonify({"replies": replies, "filter_image": None})

    # Prénom utilisateur
    if provided_name:
        name = provided_name
    else:
        name = (text.split(" ")[0] if text else "").strip()
    name = name.capitalize() if name else ""

    if not name:
        replies.append("Dis-moi ton prénom pour commencer.")
        return jsonify({"replies": replies, "filter_image": None})

    user_id, user = get_user_by_name(name)

    if user is None:
        # Nouvel utilisateur
        user_id = create_user(name)
        replies.append(f"Bienvenue {name} !")
        replies.append(f"Joyeux anniversaire à {celebrant} !")
        replies.append("Voici une anecdote : " + random.choice(ANECDOTES))
        replies.append(QUIZ[0]["question"])
        filter_image = "https://cdn-icons-png.flaticon.com/512/744/744502.png"
    else:
        step = user.get("step", "quiz_q1")
        score = user.get("score", 0)

        # Commandes utilisateur
        if tl == "rejouer":
            update_user(user_id, {"step": "quiz_q1", "score": 0})
            replies.append("C'est reparti !")
            replies.append(QUIZ[0]["question"])
        elif tl == "anecdote":
            replies.append("Anecdote : " + random.choice(ANECDOTES))
        elif tl == "bougies":
            replies.append("Soufflons les bougies ! Fais un vœu.")
            filter_image = "https://cdn-icons-png.flaticon.com/512/4151/4151051.png"
        elif tl == "musique":
            replies.append("Chanson d'anniversaire : https://www.youtube.com/watch?v=90bG0HzV5MU")
        elif tl == "carte":
            replies.append(f"Carte pour {celebrant} : Que cette année t'apporte succès, joie et code sans bugs !")
        elif tl == "galerie":
            replies.append("📸 Va dans la section 'Galerie Photo' pour voir et partager des photos !")
        elif tl == "compte":
            next_bd = datetime(2024, 12, 25)
            now = datetime.utcnow()
            diff = next_bd - now
            if diff.days > 0:
                replies.append(f"Prochain anniversaire dans {diff.days} jours ! 🎉")
            else:
                replies.append("🎉 C'est l'anniversaire aujourd'hui ! 🎉")
        elif step == "quiz_q1":
            if text.lower() == QUIZ[0]["answer"]:
                score += 1
                replies.append("Bonne réponse !")
            else:
                replies.append("Pas tout à fait...")
            update_user(user_id, {"step": "quiz_q2", "score": score})
            replies.append(QUIZ[1]["question"])
        elif step == "quiz_q2":
            if text.lower() == QUIZ[1]["answer"]:
                score += 1
                replies.append("Bravo !")
            else:
                replies.append(f"Tu ne connais pas si bien {celebrant}.")
            update_user(user_id, {"step": "quiz_q3", "score": score})
            replies.append(QUIZ[2]["question"])
        elif step == "quiz_q3":
            if text.lower() == QUIZ[2]["answer"]:
                score += 1
                replies.append("Excellent ! 🎉")
            else:
                replies.append("Presque !")
            update_user(user_id, {"step": "done", "score": score})
            replies.append(f"Merci d'avoir joué {user['name']} ! Score : {score}/{len(QUIZ)}")
            replies.append("Tape 'rejouer' pour recommencer ou 'aide' pour les commandes.")
        else:
            replies.append("Tu as déjà joué. Tape 'rejouer', 'anecdote' ou 'galerie'.")

    return jsonify({"replies": replies, "filter_image": filter_image})
# ---------- NOUVEAU: Système de Quiz ----------
@app.route("/quiz/questions", methods=["GET", "POST", "OPTIONS"])
def quiz_questions():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    
    ref = db.reference("quiz/questions")
    
    if request.method == "GET":
        questions_data = ref.get() or {}
        questions = []
        for qid, question in questions_data.items():
            question = question or {}
            question["id"] = qid
            questions.append(question)
        return jsonify({"questions": questions})
    
    # POST - Ajouter une nouvelle question
    data = request.get_json() or {}
    question_text = sanitize_text(data.get("question"), 200)
    options = [sanitize_text(opt, 100) for opt in data.get("options", [])]
    correct_answer = int(data.get("correctAnswer", 0))
    
    if not question_text or len(options) != 4:
        return jsonify({"error": "Question et 4 options requises"}), 400
    
    new_question = {
        "question": question_text,
        "options": options,
        "correctAnswer": correct_answer,
        "created_at": datetime.utcnow().isoformat()
    }
    
    new_ref = ref.push(new_question)
    return jsonify({"ok": True, "question_id": new_ref.key})

@app.route("/quiz/questions/<question_id>", methods=["DELETE", "OPTIONS"])
def delete_quiz_question(question_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    
    ref = db.reference(f"quiz/questions/{question_id}")
    ref.delete()
    return jsonify({"ok": True})

@app.route("/quiz/score", methods=["POST", "OPTIONS"])
def save_quiz_score():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    
    data = request.get_json() or {}
    name = sanitize_text(data.get("name"), 40)
    score = int(data.get("score", 0))
    total = int(data.get("total", 0))
    
    if not name:
        return jsonify({"error": "Name required"}), 400
    
    ref = db.reference("quiz/scores")
    new_score = ref.push({
        "name": name,
        "score": score,
        "total": total,
        "percentage": (score / total * 100) if total > 0 else 0,
        "created_at": datetime.utcnow().isoformat()
    })
    
    return jsonify({"ok": True, "score_id": new_score.key})

@app.route("/quiz/leaderboard", methods=["GET", "OPTIONS"])
def quiz_leaderboard():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    
    ref = db.reference("quiz/scores")
    scores_data = ref.get() or {}
    scores = []
    
    for sid, score in scores_data.items():
        score = score or {}
        score["id"] = sid
        scores.append(score)
    
    # Trier par pourcentage décroissant
    scores.sort(key=lambda x: x.get("percentage", 0), reverse=True)
    return jsonify({"leaderboard": scores[:10]})


# Route de santé
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    debug_flag = os.getenv("FLASK_DEBUG", "1") == "1"
    port = int(os.getenv("PORT", 5000))
    app.run(debug=debug_flag, host="0.0.0.0", port=port)