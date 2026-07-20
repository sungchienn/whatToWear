#!/usr/bin/env python3
import base64
import datetime as dt
import hashlib
import hmac
import json
import math
import os
import re
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
MODEL_VERSION = "weighted-prior-bayes-v3"
ODDS_CAP = 50.0

DEFAULT_OPTION_WEIGHTS = {
    "hair_style": {"短发": 0.26, "长发": 0.22, "马尾": 0.18, "卷发": 0.12, "丸子头": 0.08, "帽子压住看不清": 0.06, "今天头发很有想法": 0.08},
    "upper_color": {"黑色": 0.28, "白色": 0.18, "灰色": 0.14, "蓝色": 0.11, "绿色": 0.06, "红色": 0.04, "粉色": 0.05, "黄色": 0.03, "卡其": 0.06, "紫色": 0.02, "其他": 0.025, "不穿": 0.005},
    "top_style": {"T恤": 0.30, "衬衫": 0.20, "卫衣": 0.14, "针织衫": 0.10, "西装": 0.07, "马甲": 0.04, "背心": 0.05, "不穿上衣": 0.005, "披了个谜": 0.095},
    "outerwear": {"无外套": 0.55, "有外套": 0.34, "抱在手上": 0.08, "披着但不承认": 0.03},
    "outerwear_color": {"黑色": 0.26, "白色": 0.10, "灰色": 0.18, "蓝色": 0.10, "绿色": 0.06, "红色": 0.04, "卡其": 0.12, "透明外套": 0.005, "其他": 0.135},
    "lower_color": {"黑色": 0.32, "白色": 0.07, "灰色": 0.12, "蓝色": 0.22, "卡其": 0.12, "棕色": 0.05, "粉色": 0.02, "其他": 0.075, "下装失踪": 0.005},
    "lower_style": {"长裤": 0.28, "牛仔裤": 0.24, "运动裤": 0.14, "短裤": 0.09, "半身裙": 0.10, "连衣裙": 0.08, "下装失踪风": 0.06, "不穿": 0.01},
    "legwear": {"无明显袜类": 0.45, "短袜": 0.22, "长袜": 0.13, "丝袜": 0.09, "看不出来": 0.08, "袜子很抢戏": 0.03},
    "shoes_color": {"黑色": 0.30, "白色": 0.26, "灰色": 0.13, "棕色": 0.08, "蓝色": 0.06, "红色": 0.03, "其他": 0.12, "拖鞋气质": 0.02},
    "shoes_style": {"运动鞋": 0.38, "皮鞋": 0.13, "靴子": 0.08, "帆布鞋": 0.18, "凉鞋": 0.08, "拖鞋": 0.03, "看不清": 0.12},
    "vibe": {"休闲": 0.35, "通勤": 0.25, "运动": 0.10, "正式": 0.08, "甜酷": 0.07, "简约": 0.08, "保暖": 0.04, "今天是随机皮肤": 0.03},
}


DEFAULT_DIMENSIONS = [
    {
        "key": "hair_style",
        "name": "发型",
        "active": True,
        "visual_part": "hair",
        "options": ["短发", "长发", "马尾", "卷发", "丸子头", "帽子压住看不清", "今天头发很有想法"],
    },
    {
        "key": "upper_color",
        "name": "上身颜色",
        "active": True,
        "visual_part": "upper_color",
        "options": ["黑色", "白色", "灰色", "蓝色", "绿色", "红色", "粉色", "黄色", "卡其", "紫色", "其他", "不穿"],
    },
    {
        "key": "top_style",
        "name": "上身款式",
        "active": True,
        "visual_part": "top_style",
        "options": ["T恤", "衬衫", "卫衣", "针织衫", "西装", "马甲", "背心", "不穿上衣", "披了个谜"],
    },
    {
        "key": "outerwear",
        "name": "是否有外套",
        "active": True,
        "visual_part": "outerwear",
        "options": ["无外套", "有外套", "抱在手上", "披着但不承认"],
    },
    {
        "key": "outerwear_color",
        "name": "外套颜色",
        "active": True,
        "visual_part": "outerwear_color",
        "options": ["黑色", "白色", "灰色", "蓝色", "绿色", "红色", "卡其", "透明外套", "其他"],
    },
    {
        "key": "lower_color",
        "name": "下身颜色",
        "active": True,
        "visual_part": "lower_color",
        "options": ["黑色", "白色", "灰色", "蓝色", "卡其", "棕色", "粉色", "其他", "下装失踪"],
    },
    {
        "key": "lower_style",
        "name": "下身款式",
        "active": True,
        "visual_part": "lower_style",
        "options": ["长裤", "牛仔裤", "运动裤", "短裤", "半身裙", "连衣裙", "下装失踪风", "不穿"],
    },
    {
        "key": "legwear",
        "name": "袜类/腿部",
        "active": True,
        "visual_part": "legwear",
        "options": ["无明显袜类", "短袜", "长袜", "丝袜", "看不出来", "袜子很抢戏"],
    },
    {
        "key": "shoes_color",
        "name": "鞋子颜色",
        "active": True,
        "visual_part": "shoes_color",
        "options": ["黑色", "白色", "灰色", "棕色", "蓝色", "红色", "其他", "拖鞋气质"],
    },
    {
        "key": "shoes_style",
        "name": "鞋子款式",
        "active": True,
        "visual_part": "shoes_style",
        "options": ["运动鞋", "皮鞋", "靴子", "帆布鞋", "凉鞋", "拖鞋", "看不清"],
    },
    {
        "key": "vibe",
        "name": "整体风格",
        "active": True,
        "visual_part": "vibe",
        "options": ["休闲", "通勤", "运动", "正式", "甜酷", "简约", "保暖", "今天是随机皮肤"],
    },
]


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


def column_exists(conn, table, column):
    rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    return any(row["name"] == column for row in rows)


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
                observed_at INTEGER,
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
        if not column_exists(conn, "guesses", "fields_json"):
            conn.execute("ALTER TABLE guesses ADD COLUMN fields_json TEXT DEFAULT '{}'")
        if not column_exists(conn, "outfit_records", "fields_json"):
            conn.execute("ALTER TABLE outfit_records ADD COLUMN fields_json TEXT DEFAULT '{}'")
        if not column_exists(conn, "outfit_records", "observed_at"):
            conn.execute("ALTER TABLE outfit_records ADD COLUMN observed_at INTEGER")
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", ("guess_deadline", "10:00"))
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            ("dimensions", json.dumps(DEFAULT_DIMENSIONS, ensure_ascii=False)),
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


def get_dimensions(conn):
    raw = get_setting(conn, "dimensions")
    try:
        dims = json.loads(raw) if raw else DEFAULT_DIMENSIONS
    except json.JSONDecodeError:
        dims = DEFAULT_DIMENSIONS
    return validate_dimensions(dims, forgiving=True)


def validate_dimensions(raw_dims, forgiving=False):
    if not isinstance(raw_dims, list):
        if forgiving:
            return DEFAULT_DIMENSIONS
        raise ValueError("维度配置必须是数组。")

    seen = set()
    dims = []
    for index, raw in enumerate(raw_dims):
        if not isinstance(raw, dict):
            continue
        key = re.sub(r"[^a-zA-Z0-9_]", "_", str(raw.get("key") or "").strip())[:40]
        name = str(raw.get("name") or key).strip()[:30]
        if not key or key in seen or not name:
            continue
        options = raw.get("options") or []
        raw_weights = raw.get("option_weights") or raw.get("probabilities") or {}
        if isinstance(options, str):
            options = [part.strip() for part in options.splitlines()]
        clean_options = []
        clean_weights = {}
        for option in options:
            label, probability = parse_option_config(option)
            label = label[:30]
            if label and label not in clean_options:
                clean_options.append(label)
                weight = probability
                if weight is None and isinstance(raw_weights, dict):
                    weight = raw_weights.get(label)
                if weight is None:
                    weight = DEFAULT_OPTION_WEIGHTS.get(key, {}).get(label)
                clean_weights[label] = parse_probability(weight)
        if len(clean_options) < 2:
            continue
        clean_weights = normalize_option_weights(clean_options, clean_weights)
        seen.add(key)
        dims.append(
            {
                "key": key,
                "name": name,
                "active": bool(raw.get("active", True)),
                "visual_part": str(raw.get("visual_part") or key).strip()[:40],
                "options": clean_options[:40],
                "option_weights": {option: clean_weights[option] for option in clean_options[:40]},
                "prior_strength": float(raw.get("prior_strength", 4.0) or 4.0),
                "order": int(raw.get("order", index)),
            }
        )
    dims.sort(key=lambda item: item.get("order", 0))
    if not dims:
        if forgiving:
            return DEFAULT_DIMENSIONS
        raise ValueError("至少保留一个包含两个以上选项的维度。")
    return dims[:30]


def parse_option_config(option):
    if isinstance(option, dict):
        label = str(option.get("label") or option.get("name") or option.get("value") or "").strip()
        probability = option.get("probability", option.get("weight"))
        return label, parse_probability(probability)
    text = str(option).strip()
    if "|" in text:
        label, probability = text.rsplit("|", 1)
        return label.strip(), parse_probability(probability, percent=True)
    return text, None


def parse_probability(value, percent=False):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if percent or number > 1:
        number = number / 100.0
    return number


def normalize_option_weights(options, weights):
    fallback = 1.0 / max(1, len(options))
    values = {option: weights.get(option) or fallback for option in options}
    total = sum(values.values()) or 1.0
    return {option: round(values[option] / total, 6) for option in options}


def active_dimensions(dimensions):
    return [dim for dim in dimensions if dim.get("active")]


def dimension_map(dimensions):
    return {dim["key"]: dim for dim in dimensions}


def normalize_fields(raw_fields, dimensions, allow_empty=False):
    raw_fields = raw_fields or {}
    if not isinstance(raw_fields, dict):
        raise ValueError("竞猜字段格式不正确。")
    dims = dimension_map(dimensions)
    fields = {}
    for key, value in raw_fields.items():
        if key not in dims:
            continue
        value = str(value).strip()
        if value in dims[key]["options"]:
            fields[key] = value
    if not fields and not allow_empty:
        raise ValueError("至少选择一个可竞猜维度。")
    return fields


def legacy_fields(row):
    fields = {}
    if row is None:
        return fields
    try:
        fields = json.loads(row["fields_json"] or "{}")
    except (KeyError, TypeError, json.JSONDecodeError):
        fields = {}
    if not isinstance(fields, dict):
        fields = {}
    if not fields:
        color = row["color"] if "color" in row.keys() else ""
        style = row["style"] if "style" in row.keys() else ""
        vibe = row["vibe"] if "vibe" in row.keys() else ""
        if color:
            fields["upper_color"] = color
        if style:
            fields["top_style"] = style
        if vibe:
            fields["vibe"] = vibe
    return fields


def format_fields(fields, dimensions):
    dims = dimension_map(dimensions)
    labels = []
    for dim in dimensions:
        key = dim["key"]
        if key in fields:
            labels.append({"key": key, "name": dim["name"], "value": fields[key]})
    for key, value in fields.items():
        if key not in dims:
            labels.append({"key": key, "name": key, "value": value})
    return labels


def selected_pool_size(fields, dimensions):
    dims = dimension_map(dimensions)
    size = 1
    for key in fields:
        if key in dims:
            size *= max(1, len(dims[key]["options"]))
    return max(1, size)


def option_probability(dim, value):
    weights = dim.get("option_weights") or {}
    if value in weights:
        return max(0.0001, float(weights[value]))
    return 1.0 / max(1, len(dim.get("options") or []))


def fields_prior_probability(fields, dimensions):
    dims = dimension_map(dimensions)
    probability = 1.0
    for key, value in fields.items():
        if key in dims:
            probability *= option_probability(dims[key], value)
    return max(0.000001, probability)


def dimension_posterior_probability(rows, target_date, dim, value):
    total_weight = 0.0
    match_weight = 0.0
    for row in rows:
        record_fields = legacy_fields(row)
        if dim["key"] not in record_fields:
            continue
        days = max(0, (target_date - parse_date(row["date"])).days)
        weight = 0.93 ** days
        total_weight += weight
        if record_fields.get(dim["key"]) == value:
            match_weight += weight
    prior = option_probability(dim, value)
    prior_strength = max(0.5, min(20.0, float(dim.get("prior_strength", 4.0) or 4.0)))
    return {
        "probability": (match_weight + prior_strength * prior) / (total_weight + prior_strength),
        "sample_weight": total_weight,
        "match_weight": match_weight,
        "prior_probability": prior,
    }


def odds_for_fields(conn, date_text, fields, dimensions):
    fields = normalize_fields(fields, dimensions)
    pool_size = selected_pool_size(fields, dimensions)
    prior_probability = fields_prior_probability(fields, dimensions)
    target_date = parse_date(date_text)
    rows = conn.execute(
        "SELECT * FROM outfit_records WHERE date < ? ORDER BY date ASC",
        (date_text,),
    ).fetchall()

    total_weight = 0.0
    match_weight = 0.0
    independent_probability = 1.0
    field_stats = []
    dims = dimension_map(dimensions)
    for key, value in fields.items():
        if key not in dims:
            continue
        stat = dimension_posterior_probability(rows, target_date, dims[key], value)
        independent_probability *= stat["probability"]
        field_stats.append({"key": key, "value": value, **{k: round(v, 5) for k, v in stat.items()}})

    for row in rows:
        record_fields = legacy_fields(row)
        if not all(key in record_fields for key in fields):
            continue
        days = max(0, (target_date - parse_date(row["date"])).days)
        weight = 0.93 ** days
        total_weight += weight
        if all(record_fields.get(key) == value for key, value in fields.items()):
            match_weight += weight

    combo_prior_strength = 0.8
    combo_probability = (match_weight + combo_prior_strength * prior_probability) / (total_weight + combo_prior_strength)
    combo_confidence = 0.0 if len(fields) == 1 else min(0.70, total_weight / (total_weight + 2.0))
    probability = (1.0 - combo_confidence) * independent_probability + combo_confidence * combo_probability
    probability = max(0.001, min(0.98, probability))
    odds_weight = min(ODDS_CAP, max(1.05, 1.0 / probability))
    return {
        "probability": round(probability, 5),
        "odds_weight": round(odds_weight, 2),
        "pool_size": pool_size,
        "prior_probability": round(prior_probability, 5),
        "independent_probability": round(independent_probability, 5),
        "combo_probability": round(combo_probability, 5),
        "combo_confidence": round(combo_confidence, 3),
        "sample_weight": round(total_weight, 2),
        "match_weight": round(match_weight, 2),
        "field_stats": field_stats,
        "model_version": MODEL_VERSION,
    }


def build_recommendations(conn, date_text, dimensions):
    recommendations = []
    for dim in active_dimensions(dimensions):
        for option in dim["options"]:
            fields = {dim["key"]: option}
            odds = odds_for_fields(conn, date_text, fields, dimensions)
            recommendations.append({"fields": fields, "labels": format_fields(fields, dimensions), **odds})

    common_keys = [key for key in ["upper_color", "top_style", "outerwear", "lower_style", "shoes_color"] if key in dimension_map(dimensions)]
    if len(common_keys) >= 2:
        first, second = common_keys[0], common_keys[1]
        dims = dimension_map(dimensions)
        for left in dims[first]["options"][:12]:
            for right in dims[second]["options"][:12]:
                fields = {first: left, second: right}
                odds = odds_for_fields(conn, date_text, fields, dimensions)
                recommendations.append({"fields": fields, "labels": format_fields(fields, dimensions), **odds})
    recommendations.sort(key=lambda item: item["probability"], reverse=True)
    return recommendations[:18]


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


def current_balance(conn, user_id):
    row = conn.execute(
        "SELECT balance_after FROM settlements WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return float(row["balance_after"]) if row else 0.0


def clean_timestamp(value):
    try:
        timestamp = int(float(value))
    except (TypeError, ValueError):
        return now_ts()
    if timestamp <= 0:
        return now_ts()
    return timestamp


def guess_matches_actual(guess_fields, actual_fields):
    if not guess_fields:
        return False
    return all(actual_fields.get(key) == value for key, value in guess_fields.items())


def allocate_weighted_rewards(pool, winners):
    if not winners:
        return {}
    total_cents = int(round(pool * 100))
    total_weight = sum(max(float(winner.get("odds_weight") or 0), 0.01) for winner in winners)
    portions = []
    used = 0
    for winner in winners:
        raw = total_cents * max(float(winner.get("odds_weight") or 0), 0.01) / total_weight
        cents = int(math.floor(raw))
        portions.append({"user_id": winner["user_id"], "cents": cents, "remainder": raw - cents})
        used += cents
    remaining = total_cents - used
    portions.sort(key=lambda item: (-item["remainder"], item["user_id"]))
    for item in portions[:remaining]:
        item["cents"] += 1
    return {item["user_id"]: round(item["cents"] / 100.0, 2) for item in portions}


def settlement_transfers(entries):
    debtors = [
        {"name": entry["name"], "amount": round(abs(float(entry["delta"])), 2)}
        for entry in entries
        if float(entry["delta"]) < 0
    ]
    creditors = [
        {"name": entry["name"], "amount": round(float(entry["delta"]), 2)}
        for entry in entries
        if float(entry["delta"]) > 0
    ]
    transfers = []
    debtor_index = 0
    creditor_index = 0
    while debtor_index < len(debtors) and creditor_index < len(creditors):
        amount = round(min(debtors[debtor_index]["amount"], creditors[creditor_index]["amount"]), 2)
        if amount > 0:
            transfers.append(
                {
                    "from": debtors[debtor_index]["name"],
                    "to": creditors[creditor_index]["name"],
                    "amount": amount,
                }
            )
        debtors[debtor_index]["amount"] = round(debtors[debtor_index]["amount"] - amount, 2)
        creditors[creditor_index]["amount"] = round(creditors[creditor_index]["amount"] - amount, 2)
        if debtors[debtor_index]["amount"] <= 0:
            debtor_index += 1
        if creditors[creditor_index]["amount"] <= 0:
            creditor_index += 1
    return transfers


def settlement_preview(conn, date_text, dimensions):
    outfit = conn.execute("SELECT * FROM outfit_records WHERE date = ?", (date_text,)).fetchone()
    if not outfit:
        return {
            "date": date_text,
            "status": "no_outfit",
            "message": "请先记录当天实际着装。",
            "can_settle": False,
            "settled": False,
            "stake": 1.0,
            "pool": 0.0,
            "winner_weight": 0.0,
            "entries": [],
            "transfers": [],
        }

    existing = conn.execute(
        """
        SELECT settlements.*, users.name FROM settlements
        JOIN users ON users.id = settlements.user_id
        WHERE settlements.date = ?
        ORDER BY settlements.id ASC
        """,
        (date_text,),
    ).fetchall()
    if existing:
        entries = [dict(row) for row in existing]
        return {
            "date": date_text,
            "status": "settled",
            "message": "这一天已经结算过。",
            "can_settle": False,
            "settled": True,
            "stake": 1.0,
            "pool": round(sum(abs(float(entry["delta"])) for entry in entries if float(entry["delta"]) < 0), 2),
            "winner_weight": 0.0,
            "entries": entries,
            "transfers": settlement_transfers(entries),
        }

    actual_fields = legacy_fields(outfit)
    guesses = conn.execute(
        """
        SELECT guesses.*, users.name FROM guesses
        JOIN users ON users.id = guesses.user_id
        WHERE guesses.date = ?
        """,
        (date_text,),
    ).fetchall()
    if not guesses:
        return {
            "date": date_text,
            "status": "no_guesses",
            "message": "这一天还没有人提交竞猜。",
            "can_settle": False,
            "settled": False,
            "stake": 1.0,
            "pool": 0.0,
            "winner_weight": 0.0,
            "entries": [],
            "transfers": [],
        }

    winners = []
    losers = []
    for row in guesses:
        item = dict(row)
        item["fields"] = legacy_fields(row)
        if guess_matches_actual(item["fields"], actual_fields):
            winners.append(item)
        else:
            losers.append(item)

    entries = []
    if not winners or not losers:
        status = "void_all_right" if winners else "void_all_wrong"
        for guess in guesses:
            before = current_balance(conn, guess["user_id"])
            fields = legacy_fields(guess)
            entries.append(
                {
                    "date": date_text,
                    "user_id": guess["user_id"],
                    "name": guess["name"],
                    "result": status,
                    "delta": 0.0,
                    "balance_before": before,
                    "balance_after": before,
                    "odds_weight": guess["odds_weight"],
                    "fields": fields,
                    "labels": format_fields(fields, dimensions),
                }
            )
    else:
        pool = float(len(losers))
        rewards = allocate_weighted_rewards(pool, winners)
        for loser in losers:
            before = current_balance(conn, loser["user_id"])
            entries.append(
                {
                    "date": date_text,
                    "user_id": loser["user_id"],
                    "name": loser["name"],
                    "result": "miss",
                    "delta": -1.0,
                    "balance_before": before,
                    "balance_after": before - 1.0,
                    "odds_weight": loser["odds_weight"],
                    "fields": loser["fields"],
                    "labels": format_fields(loser["fields"], dimensions),
                }
            )
        for winner in winners:
            reward = rewards[winner["user_id"]]
            before = current_balance(conn, winner["user_id"])
            entries.append(
                {
                    "date": date_text,
                    "user_id": winner["user_id"],
                    "name": winner["name"],
                    "result": "hit",
                    "delta": reward,
                    "balance_before": before,
                    "balance_after": before + reward,
                    "odds_weight": winner["odds_weight"],
                    "fields": winner["fields"],
                    "labels": format_fields(winner["fields"], dimensions),
                }
            )

    pool = round(sum(abs(float(entry["delta"])) for entry in entries if float(entry["delta"]) < 0), 2)
    winner_weight = round(sum(max(float(entry.get("odds_weight") or 0), 0.01) for entry in entries if entry["result"] == "hit"), 2)
    return {
        "date": date_text,
        "status": entries[0]["result"] if entries and entries[0]["result"].startswith("void") else "pending",
        "message": settlement_message(entries, pool),
        "can_settle": True,
        "settled": False,
        "stake": 1.0,
        "pool": pool,
        "winner_weight": winner_weight,
        "entries": entries,
        "transfers": settlement_transfers(entries),
    }


def settlement_message(entries, pool):
    if not entries:
        return "暂无可结算数据。"
    if entries[0]["result"] == "void_all_right":
        return "全员猜中，当日作废，不产生积分变动。"
    if entries[0]["result"] == "void_all_wrong":
        return "全员猜错，当日作废，不产生积分变动。"
    winners = sum(1 for entry in entries if entry["result"] == "hit")
    losers = sum(1 for entry in entries if entry["result"] == "miss")
    return "猜中 %d 人，猜错 %d 人，输家积分池 %.2f。" % (winners, losers, pool)


def settle_date(conn, date_text, dimensions):
    preview = settlement_preview(conn, date_text, dimensions)
    if not preview["can_settle"]:
        raise ValueError(preview["message"])

    now = now_ts()
    rows = [
        (
            entry["date"],
            entry["user_id"],
            entry["result"],
            entry["delta"],
            entry["balance_after"],
            now,
        )
        for entry in preview["entries"]
    ]

    conn.executemany(
        """
        INSERT INTO settlements(date, user_id, result, delta, balance_after, created_at)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return preview["entries"]


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
    server_version = "WhatToWear/2.0"

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
                "/api/dimensions": self.post_dimensions,
                "/api/odds-preview": self.post_odds_preview,
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
            dimensions = get_dimensions(conn)
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
                fields = legacy_fields(row)
                can_see = locked or (user and (user["is_admin"] or user["id"] == item["user_id"]))
                visible_guesses.append(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "user_id": item["user_id"],
                        "fields": fields if can_see else {},
                        "labels": format_fields(fields, dimensions) if can_see else [],
                        "summary": fields_summary(fields, dimensions) if can_see else "已提交，截止后公开",
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
            outfits = conn.execute("SELECT * FROM outfit_records ORDER BY date DESC LIMIT 45").fetchall()
            settlements = conn.execute(
                """
                SELECT settlements.*, users.name FROM settlements
                JOIN users ON users.id = settlements.user_id
                ORDER BY settlements.date DESC, settlements.id ASC
                LIMIT 80
                """
            ).fetchall()
            actual = conn.execute("SELECT * FROM outfit_records WHERE date = ?", (date_text,)).fetchone()
            actual_fields = legacy_fields(actual)
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
                    "dimensions": dimensions,
                    "recommendations": build_recommendations(conn, date_text, dimensions),
                    "guesses": visible_guesses,
                    "actual": record_payload(actual, dimensions),
                    "users": [dict(row) for row in users],
                    "outfits": [record_payload(row, dimensions) for row in outfits],
                    "settlements": [dict(row) for row in settlements],
                    "settlement_preview": settlement_preview(conn, date_text, dimensions),
                    "analytics": analytics(conn, dimensions),
                    "model": {
                        "version": MODEL_VERSION,
                        "summary": "人工初始可能性 + 实际着装历史的时间衰减贝叶斯更新；多维竞猜融合各维度后验概率和完整组合记录。",
                    },
                    "empty_actual_fields": actual_fields,
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
                "INSERT INTO users(name, pin_hash, salt, is_admin, created_at) VALUES(?, ?, ?, ?, ?)",
                (name, hash_pin(pin, salt), salt, is_admin, now_ts()),
            )
            user = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
            token = make_session(conn, user["id"])
            json_response(self, {"ok": True, "user": public_user(dict(user))}, headers=self.session_cookie_header(token))

    def post_login(self):
        data = read_json(self)
        name = clean_name(data.get("name"))
        pin = str(data.get("pin", "")).strip()
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE name = ? AND active = 1", (name,)).fetchone()
            if not user or not verify_pin(pin, user["salt"], user["pin_hash"]):
                raise ValueError("昵称或 PIN 不正确。")
            token = make_session(conn, user["id"])
            json_response(self, {"ok": True, "user": public_user(dict(user))}, headers=self.session_cookie_header(token))

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
        with db() as conn:
            dimensions = get_dimensions(conn)
            fields = normalize_fields(data.get("fields") or legacy_request_fields(data), dimensions)
            if is_locked(conn, date_text) and not user["is_admin"]:
                raise ValueError("今日竞猜已截止或已记录实际着装。")
            odds = odds_for_fields(conn, date_text, fields, dimensions)
            conn.execute(
                """
                INSERT INTO guesses(date, user_id, color, style, fields_json, odds_weight, probability, submitted_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, user_id) DO UPDATE SET
                    color = excluded.color,
                    style = excluded.style,
                    fields_json = excluded.fields_json,
                    odds_weight = excluded.odds_weight,
                    probability = excluded.probability,
                    submitted_at = excluded.submitted_at
                """,
                (
                    date_text,
                    user["id"],
                    fields.get("upper_color", "其他"),
                    fields.get("top_style", "其他"),
                    json.dumps(fields, ensure_ascii=False),
                    odds["odds_weight"],
                    odds["probability"],
                    now_ts(),
                ),
            )
            json_response(self, {"ok": True, "fields": fields, **odds})

    def post_outfit(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        date_text = data.get("date") or today_iso()
        observed_at = clean_timestamp(data.get("observed_at"))
        tags = str(data.get("tags", "")).strip()[:120]
        notes = str(data.get("notes", "")).strip()[:300]
        with db() as conn:
            dimensions = get_dimensions(conn)
            fields = normalize_fields(data.get("fields") or legacy_request_fields(data), dimensions)
            conn.execute(
                """
                INSERT INTO outfit_records(date, color, style, vibe, fields_json, tags, notes, created_by, observed_at, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    color = excluded.color,
                    style = excluded.style,
                    vibe = excluded.vibe,
                    fields_json = excluded.fields_json,
                    tags = excluded.tags,
                    notes = excluded.notes,
                    observed_at = excluded.observed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    date_text,
                    fields.get("upper_color", "其他"),
                    fields.get("top_style", "其他"),
                    fields.get("vibe", "其他"),
                    json.dumps(fields, ensure_ascii=False),
                    tags,
                    notes,
                    user["id"],
                    observed_at,
                    now_ts(),
                    now_ts(),
                ),
            )
            json_response(self, {"ok": True, "fields": fields})

    def post_settle(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        date_text = data.get("date") or today_iso()
        with db() as conn:
            entries = settle_date(conn, date_text, get_dimensions(conn))
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

    def post_dimensions(self):
        user = self.require_admin()
        if not user:
            return
        data = read_json(self)
        dimensions = validate_dimensions(data.get("dimensions"))
        with db() as conn:
            set_setting(conn, "dimensions", json.dumps(dimensions, ensure_ascii=False))
            json_response(self, {"ok": True, "dimensions": dimensions})

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
                "INSERT INTO users(name, pin_hash, salt, is_admin, created_at) VALUES(?, ?, ?, ?, ?)",
                (name, hash_pin(pin, salt), salt, is_admin, now_ts()),
            )
            json_response(self, {"ok": True})

    def post_odds_preview(self):
        user = self.require_user()
        if not user:
            return
        data = read_json(self)
        date_text = data.get("date") or today_iso()
        with db() as conn:
            dimensions = get_dimensions(conn)
            fields = normalize_fields(data.get("fields"), dimensions)
            json_response(self, {"ok": True, "fields": fields, **odds_for_fields(conn, date_text, fields, dimensions)})

    def post_regenerate(self):
        user = self.require_admin()
        if not user:
            return
        json_response(self, {"ok": True, "model_version": MODEL_VERSION})

    def session_cookie_header(self, token):
        return {"Set-Cookie": f"wtw_session={token}; Max-Age={86400 * 30}; Path=/; SameSite=Lax; HttpOnly"}


def fields_summary(fields, dimensions):
    labels = format_fields(fields, dimensions)
    return " / ".join("%s: %s" % (item["name"], item["value"]) for item in labels) or "未选择"


def record_payload(row, dimensions):
    if not row:
        return None
    fields = legacy_fields(row)
    payload = dict(row)
    payload["observed_at"] = payload.get("observed_at") or payload.get("created_at")
    payload["fields"] = fields
    payload["labels"] = format_fields(fields, dimensions)
    payload["summary"] = fields_summary(fields, dimensions)
    return payload


def legacy_request_fields(data):
    fields = {}
    if data.get("color"):
        fields["upper_color"] = data.get("color")
    if data.get("style"):
        fields["top_style"] = data.get("style")
    if data.get("vibe"):
        fields["vibe"] = data.get("vibe")
    return fields


def clean_name(value):
    return " ".join(str(value or "").strip().split())


def public_user(user):
    if not user:
        return None
    return {"id": user["id"], "name": user["name"], "is_admin": bool(user["is_admin"])}


def analytics(conn, dimensions):
    outfits = [record_payload(row, dimensions) for row in conn.execute("SELECT * FROM outfit_records ORDER BY date DESC LIMIT 120").fetchall()]
    dimension_counts = []
    for dim in active_dimensions(dimensions):
        counts = {option: 0 for option in dim["options"]}
        for outfit in outfits:
            value = (outfit.get("fields") or {}).get(dim["key"])
            if value in counts:
                counts[value] += 1
        dimension_counts.append({"key": dim["key"], "name": dim["name"], "counts": counts})

    hit_rows = conn.execute(
        """
        SELECT guesses.user_id, users.name, guesses.fields_json, outfit_records.fields_json AS actual_fields,
               guesses.color, guesses.style, outfit_records.color AS actual_color, outfit_records.style AS actual_style
        FROM guesses
        JOIN users ON users.id = guesses.user_id
        JOIN outfit_records ON outfit_records.date = guesses.date
        """
    ).fetchall()
    by_user = {}
    for row in hit_rows:
        guess_fields = legacy_fields(row)
        actual_fields = {}
        try:
            actual_fields = json.loads(row["actual_fields"] or "{}")
        except json.JSONDecodeError:
            actual_fields = {}
        if not actual_fields:
            actual_fields = {"upper_color": row["actual_color"], "top_style": row["actual_style"]}
        item = by_user.setdefault(row["user_id"], {"name": row["name"], "hits": 0, "total": 0})
        item["total"] += 1
        if guess_matches_actual(guess_fields, actual_fields):
            item["hits"] += 1

    return {
        "outfit_count": len(outfits),
        "dimension_counts": dimension_counts,
        "hit_rates": [
            {"name": item["name"], "hits": item["hits"], "total": item["total"], "rate": round(item["hits"] / item["total"], 3) if item["total"] else 0}
            for item in sorted(by_user.values(), key=lambda value: (-value["hits"] / max(value["total"], 1), -value["total"]))
        ],
    }


def main():
    init_db()
    httpd = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"WhatToWear is running at http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
