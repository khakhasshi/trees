from pathlib import Path
from datetime import datetime
from functools import wraps
import csv
import io
import os
import sqlite3

import pandas as pd
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "trees.db"
PICTURES_DIR = BASE_DIR / "pictures"

app = Flask(__name__)
app.secret_key = "tree-seedling-demo-secret"

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def detect_existing_photo_by_code(code):
    for extension in ALLOWED_EXTENSIONS:
        candidate = f"{code}.{extension}"
        if (PICTURES_DIR / candidate).exists():
            return candidate
    return ""


def save_uploaded_photo(upload_file, code):
    if upload_file is None or upload_file.filename == "":
        return ""
    safe_name = secure_filename(upload_file.filename)
    if not allowed_file(safe_name):
        raise ValueError("图片格式仅支持 jpg/jpeg/png/webp")
    extension = safe_name.rsplit(".", 1)[1].lower()
    new_filename = f"{code}.{extension}"
    PICTURES_DIR.mkdir(parents=True, exist_ok=True)
    upload_file.save(PICTURES_DIR / new_filename)
    return new_filename


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, username, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return user


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return redirect(url_for("login"))
        if user["role"] != "admin":
            flash("仅管理员可执行该操作。")
            return redirect(url_for("index"))
        return view_func(*args, **kwargs)

    return wrapped


def log_action(action, target_type, target_id, detail=""):
    user = get_current_user()
    user_id = user["id"] if user else None
    username = user["username"] if user else "anonymous"
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO operation_logs (user_id, username, action, target_type, target_id, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, username, action, target_type, str(target_id), detail, now_str()),
    )
    conn.commit()
    conn.close()


def ensure_seedlings_columns(conn):
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(seedlings)").fetchall()
    }
    expected = {
        "sold_date": "TEXT",
        "customer_name": "TEXT",
        "customer_contact": "TEXT",
        "notes": "TEXT",
        "deleted": "INTEGER NOT NULL DEFAULT 0",
        "deleted_at": "TEXT",
        "deleted_by": "INTEGER",
    }
    for col_name, col_type in expected.items():
        if col_name not in existing:
            conn.execute(f"ALTER TABLE seedlings ADD COLUMN {col_name} {col_type}")


def parse_bool(value):
    if value is None:
        return 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "已售出", "售出", "是"}:
        return 1
    return 0


def normalize_import_row(raw_row):
    column_aliases = {
        "code": ["code", "编号"],
        "height": ["height", "高度", "高度(米)"],
        "crown_width": ["crown_width", "树冠宽度", "冠幅", "树冠宽度(米)"],
        "price": ["price", "价格", "价格(元)"],
        "sold": ["sold", "是否售出", "售出"],
        "photo": ["photo", "照片", "图片"],
        "sold_date": ["sold_date", "售出日期"],
        "customer_name": ["customer_name", "客户", "客户姓名"],
        "customer_contact": ["customer_contact", "联系方式", "客户联系方式"],
        "notes": ["notes", "备注"],
    }

    result = {}
    for key, aliases in column_aliases.items():
        value = ""
        for alias in aliases:
            if alias in raw_row and str(raw_row[alias]).strip() not in {"", "nan", "None"}:
                value = str(raw_row[alias]).strip()
                break
        result[key] = value

    if not result["code"] or not result["height"] or not result["crown_width"] or not result["price"]:
        raise ValueError("导入行缺少必填字段：编号/高度/树冠宽度/价格")

    result["height"] = float(result["height"])
    result["crown_width"] = float(result["crown_width"])
    result["price"] = float(result["price"])
    result["sold"] = parse_bool(result["sold"])
    if not result["photo"]:
        result["photo"] = detect_existing_photo_by_code(result["code"])

    return result


def build_filters_from_request():
    return {
        "keyword": request.args.get("keyword", "").strip(),
        "sold": request.args.get("sold", "all"),
        "min_price": request.args.get("min_price", "").strip(),
        "max_price": request.args.get("max_price", "").strip(),
        "min_height": request.args.get("min_height", "").strip(),
        "max_height": request.args.get("max_height", "").strip(),
        "min_crown": request.args.get("min_crown", "").strip(),
        "max_crown": request.args.get("max_crown", "").strip(),
    }


def build_seedlings_query(filters, deleted=0):
    query = "SELECT * FROM seedlings WHERE deleted = ?"
    params = [deleted]

    if filters["keyword"]:
        query += " AND code LIKE ?"
        params.append(f"%{filters['keyword']}%")

    if filters["sold"] in {"0", "1"}:
        query += " AND sold = ?"
        params.append(int(filters["sold"]))

    numeric_filters = [
        ("min_price", "price >= ?"),
        ("max_price", "price <= ?"),
        ("min_height", "height >= ?"),
        ("max_height", "height <= ?"),
        ("min_crown", "crown_width >= ?"),
        ("max_crown", "crown_width <= ?"),
    ]

    for key, condition in numeric_filters:
        if filters[key]:
            try:
                value = float(filters[key])
            except ValueError:
                continue
            query += f" AND {condition}"
            params.append(value)

    query += " ORDER BY code"
    return query, params


def calculate_stats(seedlings):
    total = len(seedlings)
    unsold = sum(1 for x in seedlings if x["sold"] == 0)
    sold_amount = sum(float(x["price"]) for x in seedlings if x["sold"] == 1)
    avg_price = sum(float(x["price"]) for x in seedlings) / total if total else 0

    size_distribution = {
        "小规格": 0,
        "中规格": 0,
        "大规格": 0,
    }
    for item in seedlings:
        if item["height"] < 1.5 and item["crown_width"] < 2.0:
            size_distribution["小规格"] += 1
        elif item["height"] < 2.5 and item["crown_width"] < 3.0:
            size_distribution["中规格"] += 1
        else:
            size_distribution["大规格"] += 1

    return {
        "total": total,
        "unsold": unsold,
        "sold_amount": sold_amount,
        "avg_price": avg_price,
        "size_distribution": size_distribution,
    }


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seedlings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            height REAL NOT NULL,
            crown_width REAL NOT NULL,
            price REAL NOT NULL,
            sold INTEGER NOT NULL DEFAULT 0,
            photo TEXT,
            sold_date TEXT,
            customer_name TEXT,
            customer_contact TEXT,
            notes TEXT,
            deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by INTEGER
        )
        """
    )

    ensure_seedlings_columns(conn)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            detail TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    sample_data = [
        ("0523", 1.2, 2.2, 3800, 0, "0523.jpg", None, "", "", "", 0, None, None),
        ("0506", 1.2, 1.6, 3800, 0, "0506.jpg", None, "", "", "", 0, None, None),
    ]

    for row in sample_data:
        conn.execute(
            """
            INSERT OR IGNORE INTO seedlings
            (code, height, crown_width, price, sold, photo, sold_date, customer_name, customer_contact, notes, deleted, deleted_at, deleted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    default_users = [
        ("admin", "admin123", "admin"),
        ("employee", "emp123", "employee"),
    ]

    for username, raw_password, role in default_users:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (username, password_hash, role, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (username, generate_password_hash(raw_password), role, now_str()),
        )

    conn.commit()
    conn.close()


@app.route("/pictures/<path:filename>")
@login_required
def pictures(filename):
    return send_from_directory(PICTURES_DIR, filename)


@app.context_processor
def inject_user():
    return {"current_user": get_current_user()}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash("登录成功。")
            log_action("login", "user", user["id"], "用户登录")
            return redirect(url_for("index"))
        flash("用户名或密码错误。")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    user = get_current_user()
    if user:
        log_action("logout", "user", user["id"], "用户退出")
    session.clear()
    flash("已退出登录。")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    filters = build_filters_from_request()
    query, params = build_seedlings_query(filters, deleted=0)

    conn = get_db_connection()
    seedlings = conn.execute(query, params).fetchall()
    conn.close()
    stats = calculate_stats(seedlings)

    return render_template(
        "index.html",
        seedlings=seedlings,
        filters=filters,
        stats=stats,
    )


@app.route("/add", methods=["GET", "POST"])
@admin_required
def add_seedling():
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        height = request.form.get("height", "").strip()
        crown_width = request.form.get("crown_width", "").strip()
        price = request.form.get("price", "").strip()
        sold = 1 if request.form.get("sold") == "on" else 0
        sold_date = request.form.get("sold_date", "").strip() or None
        customer_name = request.form.get("customer_name", "").strip()
        customer_contact = request.form.get("customer_contact", "").strip()
        notes = request.form.get("notes", "").strip()

        upload_file = request.files.get("photo_file")

        if not code or not height or not crown_width or not price:
            flash("请填写完整的必填字段。")
            return redirect(url_for("add_seedling"))

        try:
            photo = save_uploaded_photo(upload_file, code) or detect_existing_photo_by_code(code)
            conn = get_db_connection()
            conn.execute(
                """
                INSERT INTO seedlings
                (code, height, crown_width, price, sold, photo, sold_date, customer_name, customer_contact, notes, deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    code,
                    float(height),
                    float(crown_width),
                    float(price),
                    sold,
                    photo,
                    sold_date,
                    customer_name,
                    customer_contact,
                    notes,
                ),
            )
            conn.commit()
            conn.close()
            log_action("add", "seedling", code, f"新增树苗 {code}")
            flash("新增树苗成功。")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            flash("编号已存在，请使用不同编号。")
            return redirect(url_for("add_seedling"))
        except ValueError as error:
            flash(str(error) if "图片格式" in str(error) else "高度、树冠宽度、价格必须是数字。")
            return redirect(url_for("add_seedling"))

    return render_template("form.html", seedling=None)


@app.route("/edit/<int:seedling_id>", methods=["GET", "POST"])
@admin_required
def edit_seedling(seedling_id):
    conn = get_db_connection()
    seedling = conn.execute("SELECT * FROM seedlings WHERE id = ?", (seedling_id,)).fetchone()

    if seedling is None:
        conn.close()
        flash("未找到该树苗记录。")
        return redirect(url_for("index"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        height = request.form.get("height", "").strip()
        crown_width = request.form.get("crown_width", "").strip()
        price = request.form.get("price", "").strip()
        sold = 1 if request.form.get("sold") == "on" else 0
        sold_date = request.form.get("sold_date", "").strip() or None
        customer_name = request.form.get("customer_name", "").strip()
        customer_contact = request.form.get("customer_contact", "").strip()
        notes = request.form.get("notes", "").strip()
        upload_file = request.files.get("photo_file")

        if not code or not height or not crown_width or not price:
            conn.close()
            flash("请填写完整的必填字段。")
            return redirect(url_for("edit_seedling", seedling_id=seedling_id))

        try:
            photo = seedling["photo"]
            uploaded_photo = save_uploaded_photo(upload_file, code)
            if uploaded_photo:
                photo = uploaded_photo
            conn.execute(
                """
                UPDATE seedlings
                SET code = ?, height = ?, crown_width = ?, price = ?, sold = ?, photo = ?,
                    sold_date = ?, customer_name = ?, customer_contact = ?, notes = ?
                WHERE id = ?
                """,
                (
                    code,
                    float(height),
                    float(crown_width),
                    float(price),
                    sold,
                    photo,
                    sold_date,
                    customer_name,
                    customer_contact,
                    notes,
                    seedling_id,
                ),
            )
            conn.commit()
            conn.close()
            log_action("edit", "seedling", seedling_id, f"编辑树苗 {code}")
            flash("更新成功。")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            conn.close()
            flash("编号冲突，请使用其他编号。")
            return redirect(url_for("edit_seedling", seedling_id=seedling_id))
        except ValueError as error:
            conn.close()
            flash(str(error) if "图片格式" in str(error) else "高度、树冠宽度、价格必须是数字。")
            return redirect(url_for("edit_seedling", seedling_id=seedling_id))

    conn.close()
    return render_template("form.html", seedling=seedling)


@app.route("/delete/<int:seedling_id>", methods=["POST"])
@admin_required
def delete_seedling(seedling_id):
    user = get_current_user()
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE seedlings
        SET deleted = 1, deleted_at = ?, deleted_by = ?
        WHERE id = ?
        """,
        (now_str(), user["id"], seedling_id),
    )
    conn.commit()
    conn.close()
    log_action("delete", "seedling", seedling_id, "移入回收站")
    flash("已移入回收站。")
    return redirect(url_for("index"))


@app.route("/trash")
@admin_required
def trash():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM seedlings WHERE deleted = 1 ORDER BY deleted_at DESC, id DESC"
    ).fetchall()
    conn.close()
    return render_template("trash.html", rows=rows)


@app.route("/restore/<int:seedling_id>", methods=["POST"])
@admin_required
def restore_seedling(seedling_id):
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE seedlings
        SET deleted = 0, deleted_at = NULL, deleted_by = NULL
        WHERE id = ?
        """,
        (seedling_id,),
    )
    conn.commit()
    conn.close()
    log_action("restore", "seedling", seedling_id, "从回收站恢复")
    flash("恢复成功。")
    return redirect(url_for("trash"))


@app.route("/logs")
@admin_required
def logs():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM operation_logs ORDER BY id DESC LIMIT 300"
    ).fetchall()
    conn.close()
    return render_template("logs.html", rows=rows)


@app.route("/import", methods=["POST"])
@admin_required
def import_seedlings():
    import_file = request.files.get("import_file")
    if not import_file or not import_file.filename:
        flash("请先选择 Excel/CSV 文件。")
        return redirect(url_for("index"))

    filename = import_file.filename.lower()
    try:
        if filename.endswith(".csv"):
            content = import_file.read().decode("utf-8-sig")
            df = pd.read_csv(io.StringIO(content))
        elif filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(import_file)
        else:
            flash("仅支持 .csv / .xlsx / .xls")
            return redirect(url_for("index"))

        records = df.fillna("").to_dict(orient="records")
        if not records:
            flash("导入文件为空。")
            return redirect(url_for("index"))

        conn = get_db_connection()
        success_count = 0
        for record in records:
            row = normalize_import_row(record)
            conn.execute(
                """
                INSERT INTO seedlings
                (code, height, crown_width, price, sold, photo, sold_date, customer_name, customer_contact, notes, deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(code) DO UPDATE SET
                    height=excluded.height,
                    crown_width=excluded.crown_width,
                    price=excluded.price,
                    sold=excluded.sold,
                    photo=excluded.photo,
                    sold_date=excluded.sold_date,
                    customer_name=excluded.customer_name,
                    customer_contact=excluded.customer_contact,
                    notes=excluded.notes,
                    deleted=0,
                    deleted_at=NULL,
                    deleted_by=NULL
                """,
                (
                    row["code"],
                    row["height"],
                    row["crown_width"],
                    row["price"],
                    row["sold"],
                    row["photo"],
                    row["sold_date"] or None,
                    row["customer_name"],
                    row["customer_contact"],
                    row["notes"],
                ),
            )
            success_count += 1
        conn.commit()
        conn.close()
        log_action("import", "seedling", "batch", f"批量导入 {success_count} 条")
        flash(f"批量导入完成，共处理 {success_count} 条记录。")
    except Exception as error:
        flash(f"导入失败：{error}")

    return redirect(url_for("index"))


@app.route("/import/template")
@admin_required
def download_import_template():
    columns = [
        "code",
        "height",
        "crown_width",
        "price",
        "sold",
        "photo",
        "sold_date",
        "customer_name",
        "customer_contact",
        "notes",
    ]
    sample = {
        "code": "0601",
        "height": 1.5,
        "crown_width": 2.0,
        "price": 4200,
        "sold": 0,
        "photo": "0601.jpg",
        "sold_date": "",
        "customer_name": "",
        "customer_contact": "",
        "notes": "",
    }
    output = io.BytesIO()
    pd.DataFrame([sample], columns=columns).to_excel(output, index=False)
    output.seek(0)
    log_action("download_template", "seedling", "template", "下载导入模板")
    return send_file(
        output,
        as_attachment=True,
        download_name="seedlings_import_template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/export/excel")
@login_required
def export_excel():
    filters = build_filters_from_request()
    query, params = build_seedlings_query(filters, deleted=0)
    conn = get_db_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    data = []
    for item in rows:
        data.append(
            {
                "编号": item["code"],
                "高度(米)": item["height"],
                "树冠宽度(米)": item["crown_width"],
                "价格(元)": item["price"],
                "是否售出": "已售出" if item["sold"] else "未售出",
                "售出日期": item["sold_date"] or "",
                "客户": item["customer_name"] or "",
                "联系方式": item["customer_contact"] or "",
                "备注": item["notes"] or "",
                "照片": item["photo"] or "",
            }
        )

    output = io.BytesIO()
    df = pd.DataFrame(data)
    df.to_excel(output, index=False)
    output.seek(0)
    log_action("export_excel", "seedling", "filtered", f"导出 {len(data)} 条")
    return send_file(
        output,
        as_attachment=True,
        download_name="seedlings_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/export/pdf")
@login_required
def export_pdf():
    filters = build_filters_from_request()
    query, params = build_seedlings_query(filters, deleted=0)
    conn = get_db_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:
        font_name = "Helvetica"

    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    y = height - 40
    pdf.setFont(font_name, 14)
    pdf.drawString(40, y, "树苗导出报表")
    y -= 24

    pdf.setFont(font_name, 10)
    for idx, item in enumerate(rows, start=1):
        line = (
            f"{idx}. 编号:{item['code']} 高:{item['height']} 冠:{item['crown_width']} "
            f"价格:{item['price']} 状态:{'已售出' if item['sold'] else '未售出'} 客户:{item['customer_name'] or '-'}"
        )
        pdf.drawString(40, y, line[:95])
        y -= 16
        if y < 40:
            pdf.showPage()
            pdf.setFont(font_name, 10)
            y = height - 40

    pdf.save()
    output.seek(0)
    log_action("export_pdf", "seedling", "filtered", f"导出 {len(rows)} 条")
    return send_file(
        output,
        as_attachment=True,
        download_name="seedlings_report.pdf",
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    init_db()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "7006"))
    app.run(host=host, port=port, debug=True)
