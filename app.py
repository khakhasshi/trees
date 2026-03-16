from pathlib import Path
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "trees.db"
PICTURES_DIR = BASE_DIR / "pictures"

app = Flask(__name__)
app.secret_key = "tree-seedling-demo-secret"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
            photo TEXT
        )
        """
    )

    sample_data = [
        ("0523", 1.2, 2.2, 3800, 0, "0523.jpg"),
        ("0506", 1.2, 1.6, 3800, 0, "0506.jpg"),
    ]

    for row in sample_data:
        conn.execute(
            """
            INSERT OR IGNORE INTO seedlings (code, height, crown_width, price, sold, photo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    conn.commit()
    conn.close()


@app.route("/pictures/<path:filename>")
def pictures(filename):
    return send_from_directory(PICTURES_DIR, filename)


@app.route("/")
def index():
    keyword = request.args.get("keyword", "").strip()
    sold_filter = request.args.get("sold", "all")

    query = "SELECT * FROM seedlings WHERE 1=1"
    params = []

    if keyword:
        query += " AND code LIKE ?"
        params.append(f"%{keyword}%")

    if sold_filter in {"0", "1"}:
        query += " AND sold = ?"
        params.append(int(sold_filter))

    query += " ORDER BY code"

    conn = get_db_connection()
    seedlings = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "index.html",
        seedlings=seedlings,
        keyword=keyword,
        sold_filter=sold_filter,
    )


@app.route("/add", methods=["GET", "POST"])
def add_seedling():
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        height = request.form.get("height", "").strip()
        crown_width = request.form.get("crown_width", "").strip()
        price = request.form.get("price", "").strip()
        sold = 1 if request.form.get("sold") == "on" else 0
        photo = request.form.get("photo", "").strip()

        if not code or not height or not crown_width or not price:
            flash("请填写完整的必填字段。")
            return redirect(url_for("add_seedling"))

        try:
            conn = get_db_connection()
            conn.execute(
                """
                INSERT INTO seedlings (code, height, crown_width, price, sold, photo)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (code, float(height), float(crown_width), float(price), sold, photo),
            )
            conn.commit()
            conn.close()
            flash("新增树苗成功。")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            flash("编号已存在，请使用不同编号。")
            return redirect(url_for("add_seedling"))
        except ValueError:
            flash("高度、树冠宽度、价格必须是数字。")
            return redirect(url_for("add_seedling"))

    return render_template("form.html", seedling=None)


@app.route("/edit/<int:seedling_id>", methods=["GET", "POST"])
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
        photo = request.form.get("photo", "").strip()

        if not code or not height or not crown_width or not price:
            conn.close()
            flash("请填写完整的必填字段。")
            return redirect(url_for("edit_seedling", seedling_id=seedling_id))

        try:
            conn.execute(
                """
                UPDATE seedlings
                SET code = ?, height = ?, crown_width = ?, price = ?, sold = ?, photo = ?
                WHERE id = ?
                """,
                (code, float(height), float(crown_width), float(price), sold, photo, seedling_id),
            )
            conn.commit()
            conn.close()
            flash("更新成功。")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            conn.close()
            flash("编号冲突，请使用其他编号。")
            return redirect(url_for("edit_seedling", seedling_id=seedling_id))
        except ValueError:
            conn.close()
            flash("高度、树冠宽度、价格必须是数字。")
            return redirect(url_for("edit_seedling", seedling_id=seedling_id))

    conn.close()
    return render_template("form.html", seedling=seedling)


@app.route("/delete/<int:seedling_id>", methods=["POST"])
def delete_seedling(seedling_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM seedlings WHERE id = ?", (seedling_id,))
    conn.commit()
    conn.close()
    flash("删除成功。")
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "7006"))
    app.run(host=host, port=port, debug=True)
