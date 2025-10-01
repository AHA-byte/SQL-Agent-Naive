# 📊 SQL Agent Testing with MySQL

This project is a **MySQL + Python environment** designed to test and
experiment with SQL Agents, dummy data, and automated querying. It
provides a ready-to-use setup with MySQL, connection handling, ORM
(SQLAlchemy), and integration with modern LLMs/AI models for natural
language SQL experiments.

> ⚡ Note: The **SQL seed data generation** has its own dedicated
> documentation (see `seed/README.md`).

------------------------------------------------------------------------

## 🚀 Features

-   **MySQL Database** --- tested with MySQL 8.0.x\
-   **SQLAlchemy ORM** --- for smooth query building and database
    interaction\
-   **MySQL Connectors** --- supports both `mysql-connector-python` and
    `PyMySQL`\
-   **Streamlit UI** --- optional interface to visualize data and
    interact with SQL Agent\
-   **Faker Integration** --- (in seed module) for generating fake data\
-   **Environment Management** --- using `.env` for database credentials
    and config\
-   **AI/LLM Support** --- experiment with `openai` and
    `google-generativeai` for NL-to-SQL tasks\
-   **Data Handling** --- with `pandas` for easy manipulation and
    display

------------------------------------------------------------------------

## 📂 Project Structure

    .
    ├── seed/                 # Data seeding module (has its own README.md)
    ├── app/                  # Core Python app logic
    │   ├── db/               # DB connection & ORM setup
    │   ├── agent/            # SQL Agent / AI integrations
    │   ├── ui/               # Streamlit UI components
    │   └── utils/            # Helper functions
    ├── requirements.txt      # Dependencies
    ├── .env.example          # Example env config
    └── README.md             # This file

------------------------------------------------------------------------

## ⚙️ Requirements

Python **3.9+** is recommended.

Install dependencies:

``` bash
pip install -r requirements.txt
```

### ✅ Are `requirements.txt` entries sufficient?

Yes, your `requirements.txt` includes everything needed for:\
- **Database connectivity** (`mysql-connector-python`, `PyMySQL`,
`SQLAlchemy`)\
- **Dummy data** (`Faker`)\
- **Environment variables** (`python-dotenv`)\
- **Data handling & UI** (`pandas`, `streamlit`)\
- **AI integrations** (`openai`, `google-generativeai`, `requests`)

👉 You may want to **remove duplicates** (`mysql-connector-python`,
`sqlalchemy` appear twice) to keep it clean.

------------------------------------------------------------------------

## 🔑 Environment Variables

Create a `.env` file in the project root:

``` ini
# MySQL Database Config
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=yourpassword
DB_NAME=testdb

# OpenAI API
OPENAI_API_KEY=your_openai_api_key

# Google Generative AI API
GOOGLE_API_KEY=your_google_api_key
```

------------------------------------------------------------------------

## 🛠️ Usage

### 1. Start MySQL Server

Make sure your MySQL service is running:

``` bash
net start MySQL80   # Windows
sudo service mysql start  # Linux/macOS
```

### 2. Run Database Migrations / ORM Setup

If you're using SQLAlchemy models, initialize the schema:

``` bash
python -m app.db.init_db
```

### 3. Seed Data (Optional)

Check `seed/README.md` for fake data generation.

### 4. Start the Streamlit App

``` bash
streamlit run app/ui/main.py
```

### 5. Interact with SQL Agent

-   Query data using SQLAlchemy or direct connectors.\
-   Test natural language → SQL with LLMs (via OpenAI/Google API).\
-   Visualize results in Streamlit.

------------------------------------------------------------------------

## 📦 Tech Stack

-   **Database**: MySQL 8.0\
-   **Backend**: Python 3.9+, SQLAlchemy ORM\
-   **Frontend/UI**: Streamlit\
-   **AI Models**: OpenAI, Google Generative AI\
-   **Utilities**: Pandas, Faker, Requests, Dotenv

------------------------------------------------------------------------

## 🤝 Contributing

1.  Fork the repo\
2.  Create a feature branch (`git checkout -b feature-xyz`)\
3.  Commit changes (`git commit -m "Added new feature"`)\
4.  Push branch (`git push origin feature-xyz`)\
5.  Open a Pull Request

------------------------------------------------------------------------

## 🐞 Troubleshooting

-   **Workbench says "no connection"** → Start MySQL service manually
    (`services.msc` → `MySQL80` → Start).\
-   **Port already in use** → Check MySQL is not already running on port
    `3306`.\
-   **Module not found** → Ensure `pip install -r requirements.txt` ran
    successfully.

------------------------------------------------------------------------

## 📜 License

MIT License -- feel free to use and modify.
