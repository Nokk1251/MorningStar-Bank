import os
import sqlite3

DB_PATH = os.getenv("DATABASE_PATH", "bank.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_column(conn, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r["name"] for r in cur.fetchall()]
    return column in cols


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        account_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner TEXT NOT NULL,
        iban TEXT UNIQUE NOT NULL,
        balance REAL NOT NULL DEFAULT 0,
        overdraft_limit REAL NOT NULL DEFAULT 0,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    if not _has_column(conn, "accounts", "currency"):
        cur.execute("ALTER TABLE accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'EUR'")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        t_type TEXT NOT NULL,
        amount REAL NOT NULL,
        balance_after REAL NOT NULL,
        details TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS savings_goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        target_amount REAL NOT NULL,
        saved_amount REAL NOT NULL DEFAULT 0,
        deadline TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        amount REAL NOT NULL,
        due_date TEXT,
        is_paid INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fx_rates (
        currency TEXT PRIMARY KEY,
        per_eur REAL NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("SELECT COUNT(*) AS c FROM fx_rates")
    if cur.fetchone()["c"] == 0:
        cur.execute("INSERT INTO fx_rates(currency, per_eur) VALUES ('EUR', 1.0)")
        cur.execute("INSERT INTO fx_rates(currency, per_eur) VALUES ('USD', 1.08)")
        cur.execute("INSERT INTO fx_rates(currency, per_eur) VALUES ('GBP', 0.86)")

    conn.commit()
    conn.close()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def get_users_count():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users")
    c = cur.fetchone()["c"]
    conn.close()
    return c


def get_user_by_username(username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row_to_dict(row)


def create_user(username: str, password_hash: str, is_admin: int = 0):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
        (username, password_hash, int(is_admin)),
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid


def load_users():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, is_admin FROM users ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_user(user_id: int, username: str, is_admin: int, password_hash=None):
    conn = get_conn()
    cur = conn.cursor()
    if password_hash:
        cur.execute(
            "UPDATE users SET username = ?, is_admin = ?, password_hash = ? WHERE id = ?",
            (username, int(is_admin), password_hash, user_id),
        )
    else:
        cur.execute(
            "UPDATE users SET username = ?, is_admin = ? WHERE id = ?",
            (username, int(is_admin), user_id),
        )
    conn.commit()
    conn.close()


def delete_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_all_fx_rates():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT currency, per_eur, updated_at FROM fx_rates ORDER BY currency")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_fx_rate(currency: str):
    currency = (currency or "").upper().strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT per_eur FROM fx_rates WHERE currency = ?", (currency,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return float(row["per_eur"])


def upsert_fx_rate(currency: str, per_eur: float):
    currency = (currency or "").upper().strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO fx_rates(currency, per_eur, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(currency) DO UPDATE SET
          per_eur=excluded.per_eur,
          updated_at=CURRENT_TIMESTAMP
    """, (currency, float(per_eur)))
    conn.commit()
    conn.close()


def convert_currency(amount: float, from_cur: str, to_cur: str):
    from_cur = (from_cur or "").upper().strip()
    to_cur = (to_cur or "").upper().strip()

    if from_cur == to_cur:
        return float(amount), 1.0

    rate_from = get_fx_rate(from_cur)
    rate_to = get_fx_rate(to_cur)
    if rate_from is None:
        raise ValueError(f"Missing FX rate for {from_cur}")
    if rate_to is None:
        raise ValueError(f"Missing FX rate for {to_cur}")

    amount_eur = float(amount) / float(rate_from)
    amount_to = amount_eur * float(rate_to)

    fx_rate_used = amount_to / float(amount)
    return amount_to, fx_rate_used


def load_accounts_for_user(user_id: int, is_admin: bool):
    conn = get_conn()
    cur = conn.cursor()

    if is_admin:
        cur.execute("""
            SELECT a.*, u.username AS user_name
            FROM accounts a
            JOIN users u ON u.id = a.user_id
            ORDER BY a.account_id DESC
        """)
    else:
        cur.execute("""
            SELECT a.*, u.username AS user_name
            FROM accounts a
            JOIN users u ON u.id = a.user_id
            WHERE a.user_id = ?
            ORDER BY a.account_id DESC
        """, (user_id,))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_account_by_id(account_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.*, u.username AS user_name
        FROM accounts a
        JOIN users u ON u.id = a.user_id
        WHERE a.account_id = ?
    """, (account_id,))
    row = cur.fetchone()
    conn.close()
    return row_to_dict(row)


def get_account_by_iban(iban: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.*, u.username AS user_name
        FROM accounts a
        JOIN users u ON u.id = a.user_id
        WHERE a.iban = ?
    """, (iban,))
    row = cur.fetchone()
    conn.close()
    return row_to_dict(row)


def create_account(owner: str, iban: str, balance: float, overdraft_limit: float, currency: str, user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO accounts (owner, iban, balance, overdraft_limit, currency, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (owner, iban, float(balance), float(overdraft_limit), currency, int(user_id)))
    conn.commit()
    conn.close()


def update_account_balance(account_id: int, new_balance: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET balance = ? WHERE account_id = ?", (float(new_balance), account_id))
    conn.commit()
    conn.close()


def add_transaction(account_id: int, t_type: str, amount: float, balance_after: float, details: str = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions (account_id, t_type, amount, balance_after, details)
        VALUES (?, ?, ?, ?, ?)
    """, (account_id, t_type, float(amount), float(balance_after), details))
    conn.commit()
    conn.close()


def load_transactions_for_account(account_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM transactions WHERE account_id = ? ORDER BY id DESC", (account_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def transfer_fx(from_account_id: int, to_account_id: int, amount_from: float):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM accounts WHERE account_id = ?", (from_account_id,))
    src = cur.fetchone()
    cur.execute("SELECT * FROM accounts WHERE account_id = ?", (to_account_id,))
    dst = cur.fetchone()

    if not src or not dst:
        conn.close()
        raise ValueError("Account not found")

    src_balance = float(src["balance"])
    dst_balance = float(dst["balance"])

    src_cur = (src["currency"] or "EUR").upper()
    dst_cur = (dst["currency"] or "EUR").upper()

    amount_to, fx_rate_used = convert_currency(float(amount_from), src_cur, dst_cur)

    new_src = src_balance - float(amount_from)
    new_dst = dst_balance + float(amount_to)

    cur.execute("UPDATE accounts SET balance = ? WHERE account_id = ?", (new_src, from_account_id))
    cur.execute("UPDATE accounts SET balance = ? WHERE account_id = ?", (new_dst, to_account_id))

    details_out = f"To account #{to_account_id}"
    details_in = f"From account #{from_account_id}"

    if src_cur != dst_cur:
        details_out += f" | FX {src_cur}->{dst_cur} rate={fx_rate_used:.5f} | dest_amount={amount_to:.2f} {dst_cur}"
        details_in += f" | FX {src_cur}->{dst_cur} rate={fx_rate_used:.5f} | src_amount={amount_from:.2f} {src_cur}"

    cur.execute("""
        INSERT INTO transactions (account_id, t_type, amount, balance_after, details)
        VALUES (?, 'transfer_out', ?, ?, ?)
    """, (from_account_id, float(amount_from), new_src, details_out))

    cur.execute("""
        INSERT INTO transactions (account_id, t_type, amount, balance_after, details)
        VALUES (?, 'transfer_in', ?, ?, ?)
    """, (to_account_id, float(amount_to), new_dst, details_in))

    conn.commit()
    conn.close()
    return float(amount_to), float(fx_rate_used)


def create_savings_goal(account_id: int, title: str, target_amount: float, deadline: str | None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO savings_goals (account_id, title, target_amount, deadline)
        VALUES (?, ?, ?, ?)
    """, (account_id, title, float(target_amount), deadline))
    conn.commit()
    conn.close()


def load_savings_goals(user_id: int, is_admin: bool, selected_account_id: str = ""):
    conn = get_conn()
    cur = conn.cursor()

    params = []
    where = []
    if not is_admin:
        where.append("a.user_id = ?")
        params.append(user_id)

    if selected_account_id:
        where.append("g.account_id = ?")
        params.append(int(selected_account_id))

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cur.execute(f"""
        SELECT g.id, g.account_id, g.title, g.target_amount, g.saved_amount, g.deadline,
               a.owner, a.iban, a.currency, a.user_id
        FROM savings_goals g
        JOIN accounts a ON a.account_id = g.account_id
        {where_sql}
        ORDER BY g.id DESC
    """, tuple(params))

    rows = []
    for r in cur.fetchall():
        d = dict(r)
        target = float(d["target_amount"]) if d["target_amount"] else 0.0
        saved = float(d["saved_amount"]) if d["saved_amount"] else 0.0
        pct = 0.0
        if target > 0:
            pct = (saved / target) * 100.0
        if pct < 0:
            pct = 0.0
        if pct > 100:
            pct = 100.0
        d["pct"] = round(pct, 2)
        d["is_done"] = 1 if (target > 0 and saved >= target) else 0
        rows.append(d)

    conn.close()
    return rows


def get_savings_goal_by_id(goal_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT g.*, a.user_id, a.iban, a.owner, a.currency
        FROM savings_goals g
        JOIN accounts a ON a.account_id = g.account_id
        WHERE g.id = ?
    """, (goal_id,))
    row = cur.fetchone()
    conn.close()
    return row_to_dict(row)


def add_to_savings_goal(goal_id: int, amount: float):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT target_amount, saved_amount FROM savings_goals WHERE id = ?", (int(goal_id),))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False

    target = float(row["target_amount"])
    saved = float(row["saved_amount"])
    new_saved = saved + float(amount)

    was_done = (saved >= target)
    if new_saved >= target:
        new_saved = target

    cur.execute("UPDATE savings_goals SET saved_amount = ? WHERE id = ?", (float(new_saved), int(goal_id)))
    conn.commit()
    conn.close()

    now_done = (new_saved >= target)
    return (not was_done) and now_done


def delete_savings_goal(goal_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM savings_goals WHERE id = ?", (goal_id,))
    conn.commit()
    conn.close()


def create_bill(account_id: int, title: str, amount: float, due_date: str | None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bills (account_id, title, amount, due_date)
        VALUES (?, ?, ?, ?)
    """, (account_id, title, float(amount), due_date))
    conn.commit()
    conn.close()


def load_bills(user_id: int, is_admin: bool, selected_account_id: str = ""):
    conn = get_conn()
    cur = conn.cursor()

    params = []
    where = []
    if not is_admin:
        where.append("a.user_id = ?")
        params.append(user_id)

    if selected_account_id:
        where.append("b.account_id = ?")
        params.append(int(selected_account_id))

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cur.execute(f"""
        SELECT b.id, b.account_id, b.title, b.amount, b.due_date, b.is_paid,
               a.owner, a.iban, a.currency, a.user_id
        FROM bills b
        JOIN accounts a ON a.account_id = b.account_id
        {where_sql}
        ORDER BY b.id DESC
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_bill_by_id(bill_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.*, a.user_id, a.iban, a.owner, a.currency
        FROM bills b
        JOIN accounts a ON a.account_id = b.account_id
        WHERE b.id = ?
    """, (bill_id,))
    row = cur.fetchone()
    conn.close()
    return row_to_dict(row)


def set_bill_paid(bill_id: int, is_paid: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE bills SET is_paid = ? WHERE id = ?", (int(is_paid), bill_id))
    conn.commit()
    conn.close()


def delete_bill(bill_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
    conn.commit()
    conn.close()

def pay_bill_from_balance(bill_id: int):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")

        cur.execute("""
            SELECT
              b.id, b.account_id, b.title, b.amount, b.is_paid, b.due_date,
              a.balance, a.overdraft_limit, a.currency
            FROM bills b
            JOIN accounts a ON a.account_id = b.account_id
            WHERE b.id = ?
        """, (int(bill_id),))
        row = cur.fetchone()

        if not row:
            conn.rollback()
            return False, "Bill not found."

        if int(row["is_paid"]) == 1:
            conn.rollback()
            return False, "Bill is already paid."

        amount = float(row["amount"] or 0.0)
        if amount <= 0:
            conn.rollback()
            return False, "Invalid bill amount."

        balance = float(row["balance"] or 0.0)
        overdraft = float(row["overdraft_limit"] or 0.0)

        new_balance = balance - amount
        if new_balance < -overdraft:
            conn.rollback()
            return False, "Insufficient funds (overdraft limit reached)."

        cur.execute(
            "UPDATE accounts SET balance = ? WHERE account_id = ?",
            (float(new_balance), int(row["account_id"]))
        )

        cur.execute(
            "UPDATE bills SET is_paid = 1 WHERE id = ?",
            (int(bill_id),)
        )

        title = (row["title"] or "").strip()
        due = (row["due_date"] or "").strip()
        details = f"Bill paid: {title}"
        if due:
            details += f" | due {due}"

        cur.execute("""
            INSERT INTO transactions (account_id, t_type, amount, balance_after, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            int(row["account_id"]),
            "bill_pay",
            float(amount),
            float(new_balance),
            details
        ))

        conn.commit()
        return True, "Bill paid successfully."

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_to_savings_from_balance(goal_id: int, amount: float):
    try:
        amount = float(amount)
    except ValueError:
        return False, "Invalid amount.", False, 0.0

    if amount <= 0:
        return False, "Amount must be positive.", False, 0.0

    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")

        cur.execute("""
            SELECT g.id, g.account_id, g.title, g.target_amount, g.saved_amount, a.balance, a.overdraft_limit, a.currency FROM savings_goals g JOIN accounts a ON a.account_id = g.account_id WHERE g.id = ?
        """, (int(goal_id),))
        row = cur.fetchone()

        if not row:
            conn.rollback()
            return False, "Goal not found.", False, 0.0

        target = float(row["target_amount"] or 0.0)
        saved = float(row["saved_amount"] or 0.0)

        if target <= 0:
            conn.rollback()
            return False, "Invalid goal target.", False, 0.0

        remaining = target - saved
        if remaining <= 0:
            conn.rollback()
            return False, "Goal is already completed.", True, 0.0

        used = amount if amount <= remaining else remaining

        balance = float(row["balance"] or 0.0)
        overdraft = float(row["overdraft_limit"] or 0.0)

        new_balance = balance - used
        if new_balance < -overdraft:
            conn.rollback()
            return False, "Insufficient funds (overdraft limit reached).", False, 0.0

        new_saved = saved + used
        if new_saved > target:
            new_saved = target

        cur.execute(
            "UPDATE accounts SET balance = ? WHERE account_id = ?",
            (float(new_balance), int(row["account_id"]))
        )

        cur.execute(
            "UPDATE savings_goals SET saved_amount = ? WHERE id = ?",
            (float(new_saved), int(goal_id))
        )

        title = (row["title"] or "").strip()
        details = f"Savings goal deposit: {title} (goal #{int(goal_id)})"

        cur.execute("""
            INSERT INTO transactions (account_id, t_type, amount, balance_after, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            int(row["account_id"]),
            "savings_out",
            float(used),
            float(new_balance),
            details
        ))

        conn.commit()

        completed = (new_saved >= target)
        return True, "Saved successfully.", completed, float(used)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def refund_bill_to_balance(bill_id: int):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")

        cur.execute("""SELECT b.id, b.account_id, b.title, b.amount, b.is_paid, b.due_date, a.balance, a.currency FROM bills b JOIN accounts a ON a.account_id = b.account_id WHERE b.id = ?
        """, (int(bill_id),))
        row = cur.fetchone()

        if not row:
            conn.rollback()
            return False, "Bill not found."

        if int(row["is_paid"]) == 0:
            conn.rollback()
            return False, "Bill is not paid, nothing to refund."

        amount = float(row["amount"] or 0.0)
        if amount <= 0:
            conn.rollback()
            return False, "Invalid bill amount."

        balance = float(row["balance"] or 0.0)
        new_balance = balance + amount

        cur.execute(
            "UPDATE accounts SET balance = ? WHERE account_id = ?",
            (float(new_balance), int(row["account_id"]))
        )

        cur.execute(
            "UPDATE bills SET is_paid = 0 WHERE id = ?",
            (int(bill_id),)
        )

        title = (row["title"] or "").strip()
        due = (row["due_date"] or "").strip()
        details = f"Bill refund: {title}" if title else "Bill refund"
        if due:
            details += f" | due {due}"

        cur.execute("""
            INSERT INTO transactions (account_id, t_type, amount, balance_after, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            int(row["account_id"]),
            "bill_refund",
            float(amount),
            float(new_balance),
            details
        ))

        conn.commit()
        return True, "Refund completed. Money returned to balance."

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def withdraw_from_savings_to_balance(goal_id: int, amount: float):
    try:
        amount = float(amount)
    except ValueError:
        return False, "Invalid amount.", 0.0

    if amount <= 0:
        return False, "Amount must be positive.", 0.0

    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")

        cur.execute("""SELECT g.id, g.account_id, g.title, g.target_amount, g.saved_amount, a.balance, a.currency FROM savings_goals g JOIN accounts a ON a.account_id = g.account_id WHERE g.id = ?
        """, (int(goal_id),))
        row = cur.fetchone()

        if not row:
            conn.rollback()
            return False, "Goal not found.", 0.0

        saved = float(row["saved_amount"] or 0.0)
        if saved <= 0:
            conn.rollback()
            return False, "Nothing to withdraw (goal has 0 saved).", 0.0

        used = amount if amount <= saved else saved

        balance = float(row["balance"] or 0.0)
        new_balance = balance + used
        new_saved = saved - used
        if new_saved < 0:
            new_saved = 0.0

        cur.execute(
            "UPDATE accounts SET balance = ? WHERE account_id = ?",
            (float(new_balance), int(row["account_id"]))
        )

        cur.execute(
            "UPDATE savings_goals SET saved_amount = ? WHERE id = ?",
            (float(new_saved), int(goal_id))
        )

        title = (row["title"] or "").strip()
        details = f"Savings withdrawal: {title} (goal #{int(goal_id)})" if title else f"Savings withdrawal (goal #{int(goal_id)})"

        cur.execute("""
            INSERT INTO transactions (account_id, t_type, amount, balance_after, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            int(row["account_id"]),
            "savings_refund",
            float(used),
            float(new_balance),
            details
        ))

        conn.commit()
        return True, "Money returned to balance.", float(used)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()