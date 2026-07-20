#!/usr/bin/env python3
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("WHAT_TO_WEAR_DB", BASE_DIR / "data" / "what_to_wear.sqlite3"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8008"))
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-this-secret")
USER_INVITE_CODE = os.environ.get("USER_INVITE_CODE", "wear2026")
ADMIN_INVITE_CODE = os.environ.get("ADMIN_INVITE_CODE", "admin2026")
MODEL_VERSION = "decay-markov-v1"

COLORS = ["黑色", "白色", "灰色", "蓝色", "绿色", "红色", "粉色", "黄色", "卡其", "紫色", "其他"]
STYLES = ["T恤", "衬衫", "卫衣", "针织衫", "外套", "连衣裙", "西装", "运动装", "牛仔", "裙装", "其他"]
VIBES = ["休闲", "通勤", "运动", "正式", "甜酷", "简约", "保暖", "其他"]


def now_ts():
    return int(time.time())


def today_iso():
    return dt.date.today().isoformat()


def parse_date(value):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return dt.date.today()


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row):
    return dict(row) if row else None


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                pin_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outfit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL,
                style TEXT NOT NULL,
                vibe TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by INTEGER REFERENCES users(id),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                color TEXT NOT NULL,
                style TEXT NOT NULL,
                odds_weight REAL NOT NULL,
                probability REAL NOT NULL,
                submitted_at INTEGER NOT NULL,
                UNIQUE(date, user_id)
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                color TEXT NOT NULL,
                style TEXT NOT NULL,
                probability REAL NOT NULL,
                odds_weight REAL NOT NULL,
                model_version TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(date, color, style, model_version)
            );

            CREATE TABLE IF NOT EXISTS settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                result TEXT NOT NULL,
                delta REAL NOT NULL,
                balance_after REAL NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(date, user_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            ("guess_deadline", "10:00"),
        )


def hash_pin(pin, salt):
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000)
    return base64.b64encode(digest).decode()


def verify_pin(pin, salt, stored):
    return hmac.compare_digest(hash_pin(pin, salt), stored)


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def make_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    expires = now_ts() + 86400 * 30
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES(?, ?, ?, ?)",
        (token_digest(token), user_id, expires, now_ts()),
    )
    return token


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_current_user(handler):
    raw_cookie = handler.headers.get("Cookie", "")
    cookie = SimpleCookie(raw_cookie)
    morsel = cookie.get("wtw_session")
    if not morsel:
        return None

    digest = token_digest(morsel.value)
    with db() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.active = 1
            """,
            (digest, now_ts()),
        ).fetchone()
        return row_to_dict(row)


def is_locked(conn, date_text):
    if conn.execute("SELECT 1 FROM outfit_records WHERE date = ?", (date_text,)).fetchone():
        return True
    deadline = get_setting(conn, "guess_deadline", "10:00")
    selected = parse_date(date_text)
    if selected < dt.date.today():
        return True
    if selected > dt.date.today():
        return False
    try:
        hour, minute = [int(part) for part in deadline.split(":", 1)]
        cutoff = dt.datetime.combine(selected, dt.time(hour, minute))
        return dt.datetime.now() >= cutoff
    except ValueError:
        return False


def decayed_counts(records, field, options, target_date, alpha=0.9, decay=0.93):
    counts = {option: alpha for option in options}
    for record in records:
        days = max(0, (target_date - parse_date(record["date"])).days)
        value = record[field] if record[field] in counts else "其他"
        counts[value] = counts.get(value, alpha) + decay ** days
    total = sum(counts.values()) or 1
    return {key: value / total for key, value in counts.items()}


def transition_probs(records, field, options, previous_value, alpha=0.7):
    counts = {option: alpha for option in options}
    ordered = sorted(records, key=lambda row: row["date"])
    for before, after in zip(ordered, ordered[1:]):
        before_value = before[field] if before[field] in counts else "其他"
        after_value = after[field] if after[field] in counts else "其他"
        if before_value == previous_value:
            counts[after_value] = counts.get(after_value, alpha) + 1
    total = sum(counts.values()) or 1
    return {key: value / total for key, value in counts.items()}


def blend_probs(marginal, transition=None):
    if not transition:
        return marginal
    return {
        key: (0.65 * marginal.get(key, 0)) + (0.35 * transition.get(key, 0))
        for key in marginal
    }


def generate_predictions(conn, date_text):
    target_date = parse_date(date_text)
    rows = conn.execute(
        "SELECT * FROM outfit_records WHERE date < ? ORDER BY date ASC",
        (date_text,),
    ).fetchall()
    records = [dict(row) for row in rows]
    previous = conn.execute(
        "SELECT * FROM outfit_records WHERE date < ? ORDER BY date DESC LIMIT 1",
        (date_text,),
    ).fetchone()

    color_marginal = decayed_counts(records, "color", COLORS, target_date)
    style_marginal = decayed_counts(records, "style", STYLES, target_date)

    color_transition = None
    style_transition = None
    if previous:
        color_transition = transition_probs(records, "color", COLORS, previous["color"])
        style_transition = transition_probs(records, "style", STYLES, previous["style"])

    color_probs = blend_probs(color_marginal, color_transition)
    style_probs = blend_probs(style_marginal, style_transition)

    combo_bias = {}
    for record in records:
        days = max(0, (target_date - parse_date(record["date"])).days)
        key = (record["color"], record["style"])
        combo_bias[key] = combo_bias.get(key, 0.0) + 0.93 ** days
    max_bias = max(combo_bias.values()) if combo_bias else 0

    scored = []
    for color in COLORS:
        for style in STYLES:
            raw = color_probs[color] * style_probs[style]
            bias = combo_bias.get((color, style), 0.0)
            combo_factor = 0.85 + (0.35 * (bias / max_bias if max_bias else 0))
            scored.append((color, style, raw * combo_factor))

    total = sum(item[2] for item in scored) or 1
    predictions = []
    for color, style, score in scored:
        probability = score / total
        odds_weight = min(max(1 / probability, 1.1), 20.0)
        predictions.append(
            {
                "date": date_text,
                "color": color,
                "style": style,
                "probability": round(probability, 5),
                "odds_weight": round(odds_weight, 2),
                "model_version": MODEL_VERSION,
            }
        )

    conn.execute(
        "DELETE FROM predictions WHERE date = ? AND model_version = ?",
        (date_text, MODEL_VERSION),
    )
    conn.executemany(
        """
        INSERT INTO predictions(date, color, style, probability, odds_weight, model_version, created_at)
        VALUES(:date, :color, :style, :probability, :odds_weight, :model_version, :created_at)
        """,
        [dict(item, created_at=now_ts()) for item in predictions],
    )
    return predictions


def ensure_predictions(conn, date_text):
    rows = conn.execute(
        """
        SELECT * FROM predictions
        WHERE date = ? AND model_version = ?
        ORDER BY probability DESC
        """,
        (date_text, MODEL_VERSION),
    ).fetchall()
    if rows:
        return [dict(row) for row in rows]
    return sorted(generate_predictions(conn, date_text), key=lambda item: item["probability"], reverse=True)


def find_prediction(conn, date_text, color, style):
    ensure_predictions(conn, date_text)
    row = conn.execute(
        """
        SELECT probability, odds_weight FROM predictions
        WHERE date = ? AND color = ? AND style = ? AND model_version = ?
        """,
        (date_text, color, style, MODEL_VERSION),
    ).fetchone()
    if row:
        return float(row["probability"]), float(row["odds_weight"])
    return 0.01, 20.0


def current_balance(conn, user_id):
    row = conn.execute(
        "SELECT balance_after FROM settlements WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return float(row["balance_after"]) if row else 0.0


def settle_date(conn, date_text):
    outfit = conn.execute("SELECT * FROM outfit_records WHERE date = ?", (date_text,)).fetchone()
    if not outfit:
        raise ValueError("请先记录当天实际着装。")
    if conn.execute("SELECT 1 FROM settlements WHERE date = ?", (date_text,)).fetchone():
        raise ValueError("这一天已经结算过。")

    guesses = conn.execute(
        """
        SELECT guesses.*, users.name FROM guesses
        JOIN users ON users.id = guesses.user_id
        WHERE guesses.date = ?
        """,
        (date_text,),
    ).fetchall()
    if not guesses:
        raise ValueError("这一天还没有人提交竞猜。")

    winners = [
        dict(row) for row in guesses
        if row["color"] == outfit["color"] and row["style"] == outfit["style"]
    ]
    losers = [dict(row) for row in guesses if dict(row) not in winners]

    entries = []
    if not winners or not losers:
        for guess in guesses:
            before = current_balance(conn, guess["user_id"])
            result = "void_all_right" if winners else "void_all_wrong"
            entries.append((date_text, guess["user_id"], result, 0.0, before, now_ts()))
    else:
        pool = float(len(losers))
        total_weight = sum(max(winner["odds_weight"], 0.01) for winner in winners)
        for loser in losers:
            before = current_balance(conn, loser["user_id"])
            entries.append((date_text, loser["user_id"], "miss", -1.0, before - 1.0, now_ts()))
        for winner in winners:
            reward = pool * max(winner["odds_weight"], 0.01) / total_weight
            reward = round(reward, 2)
            before = current_balance(conn, winner["user_id"])
            entries.append((date_text, winner["user_id"], "hit", reward, before + reward, now_ts()))

    conn.executemany(
        """
        INSERT INTO settlements(date, user_id, result, delta, balance_after, created_at)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        entries,
    )
    return entries


def json_response(handler, payload, status=200, headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def read_json(handler):
    size = int(handler.headers.get("Content-Length", "0") or "0")
    if size <= 0:
        return {}
    raw = handler.rfile.read(size)
    try:
        return json.loads(raw.decode())
    except json.JSONDecodeError:
        raise ValueError("请求体不是合法 JSON。")


def static_response(handler, path, content_type):
    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(data)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "WhatToWear/1.0"

    def log_message(self, fmt, *args):
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), fmt % args))

    def send_error_json(self, message, status=400):
        json_response(self, {"ok": False, "error": message}, status)

    def require_user(self):
        user = get_current_user(self)
        if not user:
            self.send_error_json("请先登录。", HTTPStatus.UNAUTHORIZED)
            return None
        return user

    def require_admin(self):
        user = self.require_user()
        if not user:
            return None
        if not user["is_admin"]:
            self.send_error_json("需要管理员权限。", HTTPStatus.FORBIDDEN)
            return None
        return user

    def do_GET(self):
        return self.route_read()

    def do_HEAD(self):
        return self.route_read()

    def route_read(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return static_response(self, BASE_DIR / "templates" / "index.html", "text/html; charset=utf-8")
        if parsed.path == "/static/app.css":
            return static_response(self, BASE_DIR / "static" / "app.css", "text/css; charset=utf-8")
        if parsed.path == "/static/app.js":
            return static_response(self, BASE_DIR / "static" / "app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/health":
            return json_response(self, {"ok": True, "service": "what-to-wear"})
        if parsed.path == "/api/state":
            return self.get_state(parsed)
        self.send_error_json("接口不存在。", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            routes = {
                "/api/register": self.post_register,
                "/api/login": self.post_login,
                "/api/logout": self.post_logout,
                "/api/guesses": self.post_guess,
                "/api/outfits": self.post_outfit,
                "/api/settle": self.post_settle,
                "/api/settings": self.post_settings,
                "/api/users": self.post_user,
                "/api/predictions/regenerate": self.post_regenerate,
            }
            handler = routes.get(parsed.path)
            if not handler:
                return self.send_error_json("接口不存在。", HTTPStatus.NOT_FOUND)
            return handler()
        except ValueError as exc:
            self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
        except sqlite3.IntegrityError as exc:
            self.send_error_json("数据冲突，请检查是否重复提交。", HTTPStatus.CONFLICT)
            print(exc)

    def get_state(self, parsed):
        query = parse_qs(parsed.query)
        date_text = query.get("date", [today_iso()])[0]
        user = get_current_user(self)
        with db() as conn:
            predictions = ensure_predictions(conn, date_text)
            locked = is_locked(conn, date_text)
            guesses = conn.execute(
                """
                SELECT guesses.*, users.name FROM guesses
                JOIN users ON users.id = guesses.user_id
                WHERE guesses.date = ?
                ORDER BY guesses.submitted_at ASC
                """,
                (date_text,),
            ).fetchall()
            visible_guesses = []
            for row in guesses:
                item = dict(row)
                can_see = locked or (user and (user["is_admin"] or user["id"] == item["user_id"]))
                visible_guesses.append(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "user_id": item["user_id"],
                        "color": item["color"] if can_see else "已提交",
                        "style": item["style"] if can_see else "已隐藏",
                        "odds_weight": item["odds_weight"] if can_see else None,
                        "probability": item["probability"] if can_see else None,
                        "submitted_at": item["submitted_at"],
                    }
                )

            users = conn.execute(
                """
                SELECT users.id, users.name, users.is_admin, users.active,
                       COALESCE((SELECT balance_after FROM settlements s WHERE s.user_id = users.id ORDER BY s.id DESC LIMIT 1), 0) AS balance
                FROM users WHERE active = 1 ORDER BY balance DESC, name ASC
                """
            ).fetchall()
            outfits = conn.execute(
                "SELECT * FROM outfit_records ORDER BY date DESC LIMIT 45"
            ).fetchall()
            settlements = conn.execute(
                """
                SELECT settlements.*, users.name FROM settlements
                JOIN users ON users.id = settlements.user_id
                ORDER BY settlements.date DESC, settlements.id ASC
                LIMIT 80
                """
            ).fetchall()
            actual = conn.execute("SELECT * FROM outfit_records WHERE date = ?", (date_text,)).fetchone()
            deadline = get_setting(conn, "guess_deadline", "10:00")

            json_response(
                self,
                {
                    "ok": True,
                    "date": date_text,
                    "today": today_iso(),
                    "user": public_user(user),
                    "is_locked": locked,
                    "deadline": deadline,
                    "colors": COLORS,
                    "styles": STYLES,
                    "vibes": VIBES,
                    "predictions": predictions,
                    "top_predictions": predictions[:12],
                    "guesses": visible_guesses,
                    "actual": row_to_dict(actual),
                    "users": [dict(row) for row in users],
                    "outfits": [dict(row) for row in outfits],
                    "settlements": [dict(row) for row in settlements],
                    "analytics": analytics(conn),
                    "model": {
                        "version": MODEL_VERSION,
                        "summary": "时间衰减频率 + 昨日转移影响 + 贝叶斯平滑，赔率上限 20。",
                    },
                },
            )

    def post_register(self):
        data = read_json(self)
        name = clean_name(data.get("name"))
        pin = str(data.get("pin", "")).strip()
        invite_code = str(data.get("invite_code", "")).strip()
        if not name or len(name) > 24:
            raise ValueError("请输入 1-24 个字符的昵称。")
        if len(pin) < 4:
            raise ValueError("PIN 至少 4 位。")
        if invite_code not in {USER_INVITE_CODE, ADMIN_INVITE_CODE}:
            raise ValueError("邀请码不正确。")
        is_admin = 1 if invite_code == ADMIN_INVITE_CODE else 0
        salt = secrets.token_hex(16)
        with db() as conn:
            if conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
                is_admin = 1
            conn.execute(
                """
                INSERT INTO users(name, pin_hash, salt, is_admin, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (name, hash_pin(pin, salt), salt, is_admin, now_ts()),
            )
            user = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
            token = make_session(conn, user["id"])
            json_response(
                self,
                {"ok": True, "user": public_user(dict(user))},
                headers=self.session_cookie_header(token),
            )

    def post_login(self):
        data = read_json(self)
        name = clean_name(data.get("name"))
        pin = str(data.get("pin", "")).strip()
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE name = ? AND active = 1", (name,)).fetchone()
            if not user or not verify_pin(pin, user["salt"], user["pin_hash"]):
                raise ValueError("昵称或 PIN 不正确。")
            token = make_session(conn, user["id"])
            json_response(
                self,
                {"ok": True, "user": public_user(dict(user))},
                headers=self.session_cookie_header(token),
            )

    def post_logout(self):
        raw_cookie = self.headers.get("Cookie", "")
        cookie = SimpleCookie(raw_cookie)
        morsel = cookie.get("wtw_session")
        if morsel:
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(morsel.value),))
        self.send_response(204)
        self.send_header("Set-Cookie", "wtw_session=; Max-Age=0; Path=/; SameSite=Lax; HttpOnly")
        self.end_headers()

    def post_guess(self):
        user = self.require_user()
        if not user:
            return
        data = read_json(self)
        date_text = data.get("date") or today_iso()
        color = normalize_option(data.get("color"), COLORS)
        style = normalize_option(data.get("style"), STYLES)
        with db() as conn:
            if is_locked(conn, date_text) and not user["is_admin"]:
                raise ValueError("今日竞猜已截止或已记录实际着装。")
            probability, odds_weight = find_prediction(conn, date_text, color, style)
            conn.execute(
                """
                INSERT INTO guesses(date, user_id, color, style, odds_weight, probability, submitted_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, user_id) DO UPDATE SET
                    color = excluded.color,
                    style = excluded.style,
                    odds_weight = excluded.odds_weight,
                    probability = excluded.probability,
                    submitted_at = excluded.submitted_at
                """,
                (date_text, user["id"], color, style, odds_weight, probability, now_ts()),
            )
            json_response(self, {"ok": True, "probability": probability, "odds_weight": odds_weight})

    def post_outfit(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        date_text = data.get("date") or today_iso()
        color = normalize_option(data.get("color"), COLORS)
        style = normalize_option(data.get("style"), STYLES)
        vibe = normalize_option(data.get("vibe") or "其他", VIBES)
        tags = str(data.get("tags", "")).strip()[:120]
        notes = str(data.get("notes", "")).strip()[:300]
        with db() as conn:
            conn.execute(
                """
                INSERT INTO outfit_records(date, color, style, vibe, tags, notes, created_by, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    color = excluded.color,
                    style = excluded.style,
                    vibe = excluded.vibe,
                    tags = excluded.tags,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (date_text, color, style, vibe, tags, notes, user["id"], now_ts(), now_ts()),
            )
            json_response(self, {"ok": True})

    def post_settle(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        date_text = data.get("date") or today_iso()
        with db() as conn:
            entries = settle_date(conn, date_text)
            json_response(self, {"ok": True, "entries": len(entries)})

    def post_settings(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        deadline = str(data.get("deadline", "")).strip()
        try:
            hour, minute = [int(part) for part in deadline.split(":", 1)]
            dt.time(hour, minute)
        except ValueError:
            raise ValueError("截止时间格式应为 HH:MM。")
        with db() as conn:
            set_setting(conn, "guess_deadline", deadline)
            json_response(self, {"ok": True})

    def post_user(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        name = clean_name(data.get("name"))
        pin = str(data.get("pin", "")).strip()
        is_admin = 1 if data.get("is_admin") else 0
        if not name or len(pin) < 4:
            raise ValueError("请输入昵称和至少 4 位 PIN。")
        salt = secrets.token_hex(16)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO users(name, pin_hash, salt, is_admin, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (name, hash_pin(pin, salt), salt, is_admin, now_ts()),
            )
            json_response(self, {"ok": True})

    def post_regenerate(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        date_text = data.get("date") or today_iso()
        with db() as conn:
            predictions = generate_predictions(conn, date_text)
            json_response(self, {"ok": True, "count": len(predictions)})

    def session_cookie_header(self, token):
        return {
            "Set-Cookie": f"wtw_session={token}; Max-Age={86400 * 30}; Path=/; SameSite=Lax; HttpOnly"
        }


def clean_name(value):
    return " ".join(str(value or "").strip().split())


def normalize_option(value, options):
    value = str(value or "").strip()
    return value if value in options else "其他"


def public_user(user):
    if not user:
        return None
    return {
        "id": user["id"],
        "name": user["name"],
        "is_admin": bool(user["is_admin"]),
    }


def analytics(conn):
    outfits = [dict(row) for row in conn.execute("SELECT * FROM outfit_records ORDER BY date DESC LIMIT 120").fetchall()]
    color_counts = {color: 0 for color in COLORS}
    style_counts = {style: 0 for style in STYLES}
    hit_rows = conn.execute(
        """
        SELECT guesses.user_id, users.name,
               SUM(CASE WHEN guesses.color = outfit_records.color AND guesses.style = outfit_records.style THEN 1 ELSE 0 END) AS hits,
               COUNT(*) AS total
        FROM guesses
        JOIN users ON users.id = guesses.user_id
        JOIN outfit_records ON outfit_records.date = guesses.date
        GROUP BY guesses.user_id, users.name
        ORDER BY hits * 1.0 / total DESC, total DESC
        """
    ).fetchall()
    for outfit in outfits:
        color_counts[outfit["color"] if outfit["color"] in color_counts else "其他"] += 1
        style_counts[outfit["style"] if outfit["style"] in style_counts else "其他"] += 1
    return {
        "outfit_count": len(outfits),
        "color_counts": color_counts,
        "style_counts": style_counts,
        "hit_rates": [
            {
                "name": row["name"],
                "hits": row["hits"],
                "total": row["total"],
                "rate": round((row["hits"] or 0) / row["total"], 3) if row["total"] else 0,
            }
            for row in hit_rows
        ],
    }


def main():
    init_db()
    httpd = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"WhatToWear is running at http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()