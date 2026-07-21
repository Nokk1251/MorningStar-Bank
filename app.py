from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import hashlib
import hmac
import sqlite3
import os
from openai import OpenAI
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
import db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

CURRENCIES = ("EUR", "USD", "GBP")


def hash_password(password: str) -> str:
    """Create a salted password hash for newly registered users."""
    return generate_password_hash(password, method="scrypt")


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify current hashes and support the original SHA-512 demo hashes."""
    if stored_hash.startswith(("scrypt:", "pbkdf2:")):
        return check_password_hash(stored_hash, password)

    legacy_hash = hashlib.sha512(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(stored_hash, legacy_hash)


db.init_db()


def require_login():
    return "user_id" in session


def require_admin():
    return bool(session.get("is_admin", False))


def require_login_or_redirect():
    if not require_login():
        return redirect(url_for("login_get"))
    return None


def get_account_or_redirect(account_id: int):
    acc = db.get_account_by_id(account_id)
    if not acc:
        flash("Account does not exist")
        return redirect(url_for("dashboard"))
    return acc


def account_access_or_redirect(account):
    if require_admin():
        return None
    if account["user_id"] != session["user_id"]:
        flash("Access denied")
        return redirect(url_for("dashboard"))
    return None


def guard_account(account_id: int):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    acc = get_account_or_redirect(account_id)
    if hasattr(acc, "status_code"):
        return acc

    access_resp = account_access_or_redirect(acc)
    if access_resp:
        return access_resp

    return acc


def get_openai_client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    return OpenAI(api_key=key)


def mask_iban(iban: str) -> str:
    iban = (iban or "").strip()
    if len(iban) <= 8:
        return iban
    return iban[:4] + "****" + iban[-4:]

@app.get("/")
@app.get("/home")
def home():
    return render_template("home.html")


@app.get("/login")
def login_get():
    return render_template("login.html")


@app.post("/login")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Invalid credentials")
        return redirect(url_for("login_get"))

    user = db.get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        flash("Invalid credentials")
        return redirect(url_for("login_get"))

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = bool(user["is_admin"])
    return redirect(url_for("home"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_get"))


@app.get("/dashboard")
def dashboard():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    rows = db.load_accounts_for_user(session["user_id"], require_admin())
    return render_template(
        "dashboard.html",
        accounts=rows,
        currencies=CURRENCIES,
        is_admin=require_admin(),
    )


@app.get("/register")
def register_get():
    return render_template("register.html")


@app.post("/register")
def register_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Invalid username/password")
        return redirect(url_for("register_get"))

    if db.get_user_by_username(username):
        flash("Username already exists")
        return redirect(url_for("register_get"))

    is_admin = 1 if db.get_users_count() == 0 else 0
    user_id = db.create_user(username, hash_password(password), is_admin=is_admin)

    session["user_id"] = user_id
    session["username"] = username
    session["is_admin"] = bool(is_admin)

    flash("Registered successfully")
    return redirect(url_for("home"))


@app.post("/accounts")
def accounts_post():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    owner = request.form.get("owner", "").strip()
    iban = request.form.get("iban", "").strip()
    balance_str = request.form.get("balance", "").strip()
    overdraft_limit_str = request.form.get("overdraft_limit", "").strip()
    currency = request.form.get("currency", "EUR").strip().upper()

    if currency not in CURRENCIES:
        currency = "EUR"

    if not owner or not iban:
        flash("Owner and IBAN are required")
        return redirect(url_for("dashboard"))

    try:
        balance = float(balance_str)
        overdraft_limit = float(overdraft_limit_str)
    except ValueError:
        flash("Invalid numbers")
        return redirect(url_for("dashboard"))

    if balance < 0 or overdraft_limit < 0:
        flash("Values cannot be negative")
        return redirect(url_for("dashboard"))

    try:
        db.create_account(owner, iban, balance, overdraft_limit, currency, session["user_id"])
    except sqlite3.IntegrityError:
        flash("IBAN already exists")
        return redirect(url_for("dashboard"))

    flash("Account created")
    return redirect(url_for("dashboard"))


@app.get("/accounts/<int:account_id>")
def account_details(account_id):
    acc = guard_account(account_id)
    if hasattr(acc, "status_code"):
        return acc

    all_visible = db.load_accounts_for_user(session["user_id"], require_admin())
    tx = db.load_transactions_for_account(account_id)

    targets = [a for a in all_visible if a["account_id"] != account_id]
    fx = db.get_all_fx_rates()

    return render_template(
        "account_details.html",
        account=acc,
        transactions=tx,
        transfer_targets=targets,
        is_admin=require_admin(),
        fx_rates=fx
    )


@app.post("/accounts/<int:account_id>/deposit")
def deposit_post(account_id):
    acc = guard_account(account_id)
    if hasattr(acc, "status_code"):
        return acc

    amount_str = request.form.get("amount", "").strip()
    try:
        amount = float(amount_str)
    except ValueError:
        flash("Invalid amount")
        return redirect(url_for("account_details", account_id=account_id))

    if amount <= 0:
        flash("Amount must be positive")
        return redirect(url_for("account_details", account_id=account_id))

    new_balance = acc["balance"] + amount
    db.update_account_balance(account_id, new_balance)
    db.add_transaction(account_id, "deposit", amount, new_balance, details="Manual deposit")

    flash("Deposit successful")
    return redirect(url_for("account_details", account_id=account_id))


@app.post("/accounts/<int:account_id>/withdraw")
def withdraw_post(account_id):
    acc = guard_account(account_id)
    if hasattr(acc, "status_code"):
        return acc

    amount_str = request.form.get("amount", "").strip()
    try:
        amount = float(amount_str)
    except ValueError:
        flash("Invalid amount")
        return redirect(url_for("account_details", account_id=account_id))

    if amount <= 0:
        flash("Amount must be positive")
        return redirect(url_for("account_details", account_id=account_id))

    new_balance = acc["balance"] - amount
    if new_balance < -acc["overdraft_limit"]:
        flash("Insufficient funds (overdraft limit reached)")
        return redirect(url_for("account_details", account_id=account_id))

    db.update_account_balance(account_id, new_balance)
    db.add_transaction(account_id, "withdraw", amount, new_balance, details="Manual withdraw")

    flash("Withdraw successful")
    return redirect(url_for("account_details", account_id=account_id))


@app.post("/accounts/<int:account_id>/transfer")
def transfer_post(account_id):
    acc = guard_account(account_id)
    if hasattr(acc, "status_code"):
        return acc

    amount_str = request.form.get("amount", "").strip()
    to_account_id_str = request.form.get("to_account_id", "").strip()
    to_iban_str = request.form.get("to_iban", "").strip()

    try:
        amount_from = float(amount_str)
    except ValueError:
        flash("Invalid amount")
        return redirect(url_for("account_details", account_id=account_id))

    if amount_from <= 0:
        flash("Amount must be positive")
        return redirect(url_for("account_details", account_id=account_id))

    destination = None
    if to_iban_str:
        destination = db.get_account_by_iban(to_iban_str)
        if not destination:
            flash("Destination IBAN not found")
            return redirect(url_for("account_details", account_id=account_id))
    elif to_account_id_str:
        try:
            dest_id = int(to_account_id_str)
        except ValueError:
            flash("Invalid destination ID")
            return redirect(url_for("account_details", account_id=account_id))

        destination = db.get_account_by_id(dest_id)
        if not destination:
            flash("Destination account not found")
            return redirect(url_for("account_details", account_id=account_id))

        if (not require_admin()) and destination["user_id"] != session["user_id"]:
            flash("Access denied")
            return redirect(url_for("account_details", account_id=account_id))
    else:
        flash("Choose destination account or enter IBAN")
        return redirect(url_for("account_details", account_id=account_id))

    if destination["account_id"] == account_id:
        flash("Pick another account")
        return redirect(url_for("account_details", account_id=account_id))

    new_src_balance_preview = acc["balance"] - amount_from
    if new_src_balance_preview < -acc["overdraft_limit"]:
        flash("Insufficient funds (overdraft limit reached)")
        return redirect(url_for("account_details", account_id=account_id))

    try:
        amount_to, fx_rate_used = db.transfer_fx(
            from_account_id=account_id,
            to_account_id=destination["account_id"],
            amount_from=amount_from
        )
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("account_details", account_id=account_id))
    except Exception:
        flash("Transfer failed")
        return redirect(url_for("account_details", account_id=account_id))

    if acc["currency"] == destination["currency"]:
        flash("Transfer successful")
    else:
        flash(f"Transfer successful. Converted: {amount_to:.2f} {destination['currency']} (rate {fx_rate_used:.5f})")

    return redirect(url_for("account_details", account_id=account_id))


@app.get("/savings")
def savings_get():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    selected = request.args.get("account_id", "").strip()
    accounts = db.load_accounts_for_user(session["user_id"], require_admin())
    goals = db.load_savings_goals(session["user_id"], require_admin(), selected_account_id=selected)

    return render_template(
        "savings.html",
        accounts=accounts,
        goals=goals,
        selected_account_id=selected,
    )


@app.post("/savings/add")
def savings_add():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    account_id_str = request.form.get("account_id", "").strip()
    title = request.form.get("title", "").strip()
    target_str = request.form.get("target_amount", "").strip()
    deadline = request.form.get("deadline", "").strip() or None

    try:
        account_id = int(account_id_str)
        target_amount = float(target_str)
    except ValueError:
        flash("Invalid data")
        return redirect(url_for("savings_get"))

    if not title or target_amount <= 0:
        flash("Invalid data")
        return redirect(url_for("savings_get"))

    acc = db.get_account_by_id(account_id)
    if not acc:
        flash("Account not found")
        return redirect(url_for("savings_get"))

    access_resp = account_access_or_redirect(acc)
    if access_resp:
        return access_resp

    db.create_savings_goal(account_id, title, target_amount, deadline)
    flash("Goal created")
    return redirect(url_for("savings_get", account_id=account_id))


@app.post("/savings/<int:goal_id>/add_amount")
def savings_add_amount(goal_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    amount_str = request.form.get("amount", "").strip()

    goal = db.get_savings_goal_by_id(goal_id)
    if not goal:
        flash("Goal not found")
        return redirect(url_for("savings_get"))

    if (not require_admin()) and goal["user_id"] != session["user_id"]:
        flash("Access denied")
        return redirect(url_for("savings_get"))

    try:
        amount = float(amount_str)
    except ValueError:
        flash("Invalid amount")
        return redirect(url_for("savings_get", account_id=goal["account_id"]))

    try:
        success, message, completed, used = db.add_to_savings_from_balance(goal_id, amount)
    except Exception:
        app.logger.exception("Savings add amount error")
        success, message, completed, used = False, "Saving failed. Check Flask logs.", False, 0.0

    flash(message)

    if success and amount != used and used > 0:
        flash(f"Only {used:.2f} was needed to complete the goal, so that is what was taken.")

    if completed:
        flash("Goal completed!")

    return redirect(url_for("savings_get", account_id=goal["account_id"]))

@app.post("/savings/<int:goal_id>/withdraw_amount")
def savings_withdraw_amount(goal_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    goal = db.get_savings_goal_by_id(goal_id)
    if not goal:
        flash("Goal not found")
        return redirect(url_for("savings_get"))

    if (not require_admin()) and goal["user_id"] != session["user_id"]:
        flash("Access denied")
        return redirect(url_for("savings_get"))

    amount_str = request.form.get("amount", "").strip()
    try:
        amount = float(amount_str)
    except ValueError:
        flash("Invalid amount")
        return redirect(url_for("savings_get", account_id=goal["account_id"]))

    try:
        ok, msg, used = db.withdraw_from_savings_to_balance(goal_id, amount)
    except Exception:
        app.logger.exception("Savings withdraw error")
        ok, msg, used = False, "Withdraw failed. Check Flask logs.", 0.0

    flash(msg)

    if ok and used > 0 and used != amount:
        flash(f"Only {used:.2f} was available in the goal, so that is what was withdrawn.")

    return redirect(url_for("savings_get", account_id=goal["account_id"]))


@app.post("/savings/<int:goal_id>/delete")
def savings_delete(goal_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    goal = db.get_savings_goal_by_id(goal_id)
    if not goal:
        flash("Goal not found")
        return redirect(url_for("savings_get"))

    if (not require_admin()) and goal["user_id"] != session["user_id"]:
        flash("Access denied")
        return redirect(url_for("savings_get"))

    db.delete_savings_goal(goal_id)
    flash("Goal deleted")
    return redirect(url_for("savings_get", account_id=goal["account_id"]))


@app.get("/bills")
def bills_get():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    selected = request.args.get("account_id", "").strip()
    accounts = db.load_accounts_for_user(session["user_id"], require_admin())
    bills = db.load_bills(session["user_id"], require_admin(), selected_account_id=selected)

    return render_template(
        "bills.html",
        accounts=accounts,
        bills=bills,
        selected_account_id=selected,
    )


@app.post("/bills/add")
def bills_add():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    account_id_str = request.form.get("account_id", "").strip()
    title = request.form.get("title", "").strip()
    amount_str = request.form.get("amount", "").strip()
    due_date = request.form.get("due_date", "").strip() or None

    try:
        account_id = int(account_id_str)
        amount = float(amount_str)
    except ValueError:
        flash("Invalid data")
        return redirect(url_for("bills_get"))

    if not title or amount <= 0:
        flash("Invalid data")
        return redirect(url_for("bills_get"))

    acc = db.get_account_by_id(account_id)
    if not acc:
        flash("Account not found")
        return redirect(url_for("bills_get"))

    access_resp = account_access_or_redirect(acc)
    if access_resp:
        return access_resp

    db.create_bill(account_id, title, amount, due_date)
    flash("Bill added")
    return redirect(url_for("bills_get", account_id=account_id))


@app.post("/bills/<int:bill_id>/pay")
def bills_pay(bill_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    bill = db.get_bill_by_id(bill_id)
    if not bill:
        flash("Bill not found")
        return redirect(url_for("bills_get"))

    if (not require_admin()) and bill["user_id"] != session["user_id"]:
        flash("Access denied")
        return redirect(url_for("bills_get"))

    try:
        success, message = db.pay_bill_from_balance(bill_id)
    except Exception:
        app.logger.exception("Pay bill error")
        success, message = False, "Payment failed. Check Flask logs."

    flash(message)
    return redirect(url_for("bills_get", account_id=bill["account_id"]))

@app.post("/bills/<int:bill_id>/delete")
def bills_delete(bill_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    bill = db.get_bill_by_id(bill_id)
    if not bill:
        flash("Bill not found")
        return redirect(url_for("bills_get"))

    if (not require_admin()) and bill["user_id"] != session["user_id"]:
        flash("Access denied")
        return redirect(url_for("bills_get"))

    db.delete_bill(bill_id)
    flash("Bill deleted")
    return redirect(url_for("bills_get", account_id=bill["account_id"]))

@app.post("/bills/<int:bill_id>/refund")
def bills_refund(bill_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    bill = db.get_bill_by_id(bill_id)
    if not bill:
        flash("Bill not found")
        return redirect(url_for("bills_get"))

    if (not require_admin()) and bill["user_id"] != session["user_id"]:
        flash("Access denied")
        return redirect(url_for("bills_get"))

    try:
        success, message = db.refund_bill_to_balance(bill_id)
    except Exception:
        app.logger.exception("Refund bill error")
        success, message = False, "Refund failed. Check Flask logs."

    flash(message)
    return redirect(url_for("bills_get", account_id=bill["account_id"]))


@app.get("/admin/users")
def admin_users_get():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    if not require_admin():
        flash("Access denied")
        return redirect(url_for("dashboard"))

    users = db.load_users()
    return render_template("admin_users.html", users=users)


@app.post("/admin/users/<int:user_id>/edit")
def admin_users_edit(user_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    if not require_admin():
        flash("Access denied")
        return redirect(url_for("dashboard"))

    username = request.form.get("username", "").strip()
    is_admin = 1 if request.form.get("is_admin") == "1" else 0
    new_password = request.form.get("new_password", "").strip()

    if not username:
        flash("Username required")
        return redirect(url_for("admin_users_get"))

    if user_id == session["user_id"] and is_admin == 0:
        flash("You cannot remove your own admin role.")
        return redirect(url_for("admin_users_get"))

    pw_hash = hash_password(new_password) if new_password else None
    try:
        db.update_user(user_id, username, is_admin, pw_hash)
        flash("User updated")
    except sqlite3.IntegrityError:
        flash("Username already exists")

    return redirect(url_for("admin_users_get"))


@app.post("/admin/users/<int:user_id>/delete")
def admin_users_delete(user_id):
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    if not require_admin():
        flash("Access denied")
        return redirect(url_for("dashboard"))

    if user_id == session["user_id"]:
        flash("You cannot delete yourself.")
        return redirect(url_for("admin_users_get"))

    db.delete_user(user_id)
    flash("User deleted")
    return redirect(url_for("admin_users_get"))


@app.get("/admin/rates")
def admin_rates_get():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    if not require_admin():
        flash("Access denied")
        return redirect(url_for("dashboard"))

    rates = db.get_all_fx_rates()
    return render_template("admin_rates.html", rates=rates, currencies=CURRENCIES)


@app.post("/admin/rates")
def admin_rates_post():
    redirect_resp = require_login_or_redirect()
    if redirect_resp:
        return redirect_resp

    if not require_admin():
        flash("Access denied")
        return redirect(url_for("dashboard"))

    for cur in CURRENCIES:
        key = f"rate_{cur}"
        v = (request.form.get(key, "") or "").strip()
        try:
            rate = float(v)
        except ValueError:
            flash(f"Invalid rate for {cur}")
            return redirect(url_for("admin_rates_get"))

        if rate <= 0:
            flash(f"Rate must be positive for {cur}")
            return redirect(url_for("admin_rates_get"))

        db.upsert_fx_rate(cur, rate)

    flash("Rates updated")
    return redirect(url_for("admin_rates_get"))


@app.post("/ai/chat")
def ai_chat():
    if not require_login():
        return jsonify({"reply": "Please log in to use the assistant."}), 401

    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"reply": "Please enter a message."}), 400

    client = get_openai_client()
    if not client:
        return jsonify({"reply": "Server is missing OPENAI_API_KEY."}), 500

    is_admin = require_admin()
    role = "admin" if is_admin else "normal_user"
    username = session.get("username", "")

    visible_accounts = db.load_accounts_for_user(session["user_id"], is_admin)

    lines = [f"USER ROLE: {role}", f"USERNAME: {username}", ""]
    if visible_accounts:
        for a in visible_accounts:
            lines.append(
                f'- {a["owner"]} | IBAN {mask_iban(a["iban"])} | balance {a["balance"]:.2f} {a["currency"]} | overdraft {a["overdraft_limit"]:.2f}'
            )
    else:
        lines.append("No accounts.")

    lines.append("")
    lines.append("RECENT TRANSACTIONS (last 5 per account):")

    if visible_accounts:
        for a in visible_accounts:
            acc_id = a["account_id"]
            lines.append(f'Account {mask_iban(a["iban"])} ({a["currency"]}):')

            tx = db.load_transactions_for_account(acc_id)[:5]
            if not tx:
                lines.append("- no transactions")
            else:
                for t in tx:
                    t_type = t.get("t_type", "")
                    amount = float(t.get("amount", 0) or 0)
                    created = t.get("created_at", "")
                    details = (t.get("details") or "").strip()
                    if len(details) > 60:
                        details = details[:60] + "..."

                    if details:
                        lines.append(f"- {t_type} {amount:.2f} {a['currency']} | {created} | {details}")
                    else:
                        lines.append(f"- {t_type} {amount:.2f} {a['currency']} | {created}")

    system_prompt = (
        "You are MorningStar Assistant inside a demo banking web app.\n"
        "You are a practical personal finance coach.\n"
        "Use ONLY the provided ACCOUNT CONTEXT (including RECENT TRANSACTIONS).\n"
        "Do NOT invent merchants, categories, or extra spending reasons.\n"
        "You may infer simple patterns using transaction types (withdraw, transfer_out, bills).\n"
        "Do NOT claim you executed transactions.\n"
        "If asked to deposit/withdraw/transfer, tell the user to use the site's forms.\n"
        "Be concise and actionable."
    )

    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": "ACCOUNT CONTEXT:\n" + "\n".join(lines)},
                {"role": "user", "content": msg},
            ],
            store=False,
        )
        reply = (response.output_text or "").strip() or "No reply."
        return jsonify({"reply": reply})
    except Exception:
        app.logger.exception("AI error")
        return jsonify({"reply": "AI server error. Check Flask logs."}), 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
