MorningStar Bank Demo

MorningStar is an educational banking web application built with Flask and SQLite. It simulates common banking workflows such as account management, deposits, withdrawals, transfers, savings goals, bills, currency conversion, administration, and an optional AI finance assistant.

It is not a real banking system and must not be used with real financial or personal data.

1. Features

- User registration and login
- The first registered user becomes an administrator
- Multiple bank accounts with EUR, USD, and GBP support
- Deposits, withdrawals, overdraft validation, and transaction history
- Transfers between accounts with configurable FX rates
- Savings goals with deposits and withdrawals
- Bill creation, payment, refund, and deletion
- Admin panel for users and exchange rates
- Optional OpenAI-powered assistant using masked account context and recent transactions
- Responsive interface built with Jinja templates, CSS, and JavaScript

2. Tech stack

- Python 3
- Flask
- SQLite
- Jinja2
- HTML, CSS, and JavaScript
- OpenAI API for the optional assistant

3. Project structure


MorningStar-Bank-Web-App/
├── app.py
├── db.py
├── requirements.txt
├── .env.example
├── .gitignore
├── static/
│   ├── ai.js
│   ├── style.css
│   └── img/
└── templates/


The SQLite database is created automatically on the first run and is intentionally excluded from Git.

4. Local setup

	I. Create and activate a virtual environment

Windows PowerShell:

powershell
python -m venv .venv .\.venv\Scripts\Activate.ps1


	II. Install dependencies

powershell
pip install -r requirements.txt


	III. Create the environment file

powershell
Copy-Item .env.example .env


Open ".env" and replace "FLASK_SECRET_KEY" with a long random value of your choosing. "OPENAI_API_KEY" is optional, but without it the AI won't work; the rest of the application works without the AI assistant.

	IV. Run the application

powershell
python app.py


Open the local address shown in the terminal, usually "http://127.0.0.1:5000".

- Administrator account

The first user registered in a new database receives administrator privileges. Administrators can manage users and edit exchange rates.

- Security notes

This version uses salted password hashing through Werkzeug and loads secrets from environment variables. The repository excludes local databases, virtual environments, IDE metadata, and ".env" files.

The application remains an educational demo. Before production use, it would still require CSRF protection, automated tests, database migrations, stricter validation, decimal-based money calculations, rate limiting, secure deployment settings, and a full security review.

- Roadmap

- Add automated tests
- Add CSRF protection
- Replace floating-point money values with "Decimal"
- Add database migrations
- Add screenshots and a hosted demo
- Improve accessibility and validation messages

- Background

This project is a web-based evolution of an earlier Python/Tkinter banking exercise. The current version focuses on Flask routing, authentication, persistence, role-based access, transactions, and API integration.
