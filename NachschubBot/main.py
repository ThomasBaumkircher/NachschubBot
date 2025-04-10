import json
import os
import sqlite3
from telebot import TeleBot, types
from time import sleep

# Konfigurationsdatei laden
CONFIG_FILE = "config.json"
with open(CONFIG_FILE, "r") as file:
    config = json.load(file)

USERS = config["users"]
DRINKS = config["drinks"]
BARS = config["bars"]  # Zuordnung von Getränken zu Bars

# Initialisiere den Bot
TOKEN = os.getenv("BOT_KEY")
bot = TeleBot(TOKEN)

# Helper functions for database interaction
def db_operation(func, *args):
    conn = sqlite3.connect('orders.db')
    cursor = conn.cursor()
    try:
        result = func(cursor, *args)
        conn.commit()
        return result
    except Exception as e:
        print(f"Database error: {e}")
        conn.rollback()
        return None
    finally:
        cursor.close()
        conn.close()

def create_orders_table(cursor):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        drink TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'offen'
    )
    """)

def create_sessions_table(cursor):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        chat_id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        role TEXT NOT NULL
    )
    """)

def save_session(cursor, chat_id, username, role):
    cursor.execute("REPLACE INTO sessions (chat_id, username, role) VALUES (?, ?, ?)", (chat_id, username, role))

def delete_session(cursor, chat_id):
    cursor.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))

def get_session(cursor, chat_id):
    cursor.execute("SELECT username, role FROM sessions WHERE chat_id = ?", (chat_id,))
    return cursor.fetchone()

def get_sessions_by_username(cursor, username):
    cursor.execute("SELECT chat_id FROM sessions WHERE username = ?", (username,))
    return cursor.fetchall()

def insert_order(cursor, username, role, drink, quantity):
    cursor.execute("""
    INSERT INTO orders (username, role, drink, quantity, status) 
    VALUES (?, ?, ?, ?, 'offen')
    """, (username, role, drink, quantity))

def update_order_status(cursor, order_id):
    cursor.execute("""
    UPDATE orders SET status = 'entsandt' WHERE id = ?
    """, (order_id,))

def get_open_orders(cursor, username=None):
    query = """
    SELECT id AS order_id, username, drink, quantity, status FROM orders 
    WHERE status = 'offen' """
    params = []
    if username:
        query += "AND username = ?"
        params.append(username)
    cursor.execute(query, params)
    return cursor.fetchall()

def get_order_by_id(cursor, order_id):
    query = """
    SELECT id AS order_id, username, drink, quantity, status FROM orders 
    WHERE id = ? """
    params = [order_id]
    cursor.execute(query, params)
    return cursor.fetchone()


# Initial database setup
db_operation(create_orders_table)
db_operation(create_sessions_table)


# Helper: Prüft Login
def authenticate_user(username, password):
    user = USERS.get(username)
    if user and user["password"] == password:
        return user["role"]
    return None

# Verfügbare Befehle registrieren
def register_commands():
    commands = [
        types.BotCommand("start", "Starte den Bot"),
        types.BotCommand("login", "Einloggen mit Benutzername und Passwort"),
        types.BotCommand("logout", "Ausloggen"),
    ]
    bot.set_my_commands(commands)

# Startkommando
@bot.message_handler(commands=["start"])
def handle_start(message):
    chat_id = message.chat.id
    session = db_operation(get_session, chat_id)
    if not session:
        bot.send_message(
            chat_id,
            "Willkommen beim Maturaball-Bot! Bitte logge dich ein.\n"
            "Sende deinen Benutzernamen und das Passwort im Format:\n\n"
            "`/login <Benutzername> <Passwort>`",
            parse_mode="Markdown",
        )
    elif session[1] == "nachschub":
        show_open_orders_for_nachschub(chat_id)
    else:
        show_drink_menu(chat_id, session[0])

# Login-Kommando
@bot.message_handler(commands=["login"])
def handle_login(message):
    chat_id = message.chat.id
    session = db_operation(get_session, chat_id)
    if session:
        bot.send_message(chat_id, "Du bist bereits eingeloggt.")
        return

    try:
        _, username, password = message.text.split()
    except ValueError:
        bot.send_message(chat_id, "Ungültiges Format! Bitte verwende `/login <Benutzername> <Passwort>`.")
        return

    role = authenticate_user(username, password)
    if role:
        db_operation(save_session, chat_id, username, role)
        bot.send_message(chat_id, f"Login erfolgreich!")
        if role == "bar":
            show_bar_orders(chat_id, username)
            show_drink_menu(chat_id, username)
        elif role == "nachschub":
            show_open_orders_for_nachschub(chat_id)
    else:
        bot.send_message(chat_id, "Ungültige Zugangsdaten. Bitte versuche es erneut.")


# Zeigt alle offenen Bestellungen für Nachschub-Mitarbeiter nach Login
def show_open_orders_for_nachschub(chat_id):
    rows = db_operation(get_open_orders)
    if not rows:
        bot.send_message(chat_id, "📋 *Keine offenen Bestellungen vorhanden.*", parse_mode="Markdown")
        return

    usernames = set()
    for _, username, _, _, _ in rows:
        usernames.add(username)

    bar_orders = {}
    for username in usernames:
        bar_orders[username] = []

    for order_id, username, drink, quantity, status in rows:
        if status == "offen":
            bar_orders[username].append({
                "order_id": order_id,
                "drink": drink,
                "quantity": quantity,
            })

    markup = types.InlineKeyboardMarkup(row_width=1)
    for user, orders in bar_orders.items():
        markup.add(types.InlineKeyboardButton(
            f"-- Bestellungen für {user} ({len(orders)}): --",
            callback_data=f"process_order:0"
        ))
        for order in orders:
            markup.add(types.InlineKeyboardButton(
                f"{order['quantity']} mal '{order['drink']}'",
                callback_data=f"process_order:{order['order_id']}"
            ))

    bot.send_message(
        chat_id,
        "📋 *Offene Bestellungen für Nachschub:*",
        reply_markup=markup,
        parse_mode="Markdown",
    )

# Handle Callback für Nachschub, wenn eine Bestellung ausgewählt wurde
@bot.callback_query_handler(func=lambda call: call.data.startswith("process_order:"))
def process_order(call):
    chat_id = call.message.chat.id
    order_id = int(call.data.split(":")[1])

    if order_id == 0:
        bot.answer_callback_query(call.id, "❌ Dieser Knopf ist nicht zum drücken gedacht.")
        return

    order = db_operation(get_order_by_id, order_id)
    if not order:
        bot.answer_callback_query(call.id, "❌ Bestellung nicht gefunden.")
        return

    _, username, drink, quantity, status = order
    if status != "offen":
        bot.answer_callback_query(call.id, "❌ Diese Bestellung ist bereits abgeschlossen.")
        return

    db_operation(update_order_status, order_id)
    notify_bar_worker(f"Bestellung von {username}: {quantity} mal '{drink}' wurde als 'abgesendet' markiert.", username)
    bot.answer_callback_query(call.id, "✅ Bestellung wurde als 'abgesendet' markiert.")
    msg = bot.send_message(chat_id, "✅ Bestellung wurde als 'abgesendet' markiert.")
    sleep(1)
    bot.delete_message(chat_id, msg.message_id)
    bot.delete_message(chat_id, call.message.message_id)
    show_open_orders_for_nachschub(chat_id)

# Bar-Arbeiter: Eigene Bestellungen anzeigen
def show_bar_orders(chat_id, username):
    session = db_operation(get_session, chat_id)
    if not session or session[1] != "bar":
        bot.send_message(chat_id, "❌ Dieser Befehl ist nur für Bar-Arbeiter verfügbar.")
        return

    bar_name = username
    assigned_drinks = BARS.get(bar_name, [])
    rows = db_operation(get_open_orders, username)

    if not rows:
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for order_id, _, drink, quantity, status in rows:
        if status == "offen":
            markup.add(types.InlineKeyboardButton(
                f"{quantity} mal '{drink}'",
                callback_data=f"order:{order_id}"
            ))

    bot.send_message(
        chat_id,
        "📋 *Deine offenen Bestellungen:*",
        reply_markup=markup,
        parse_mode="Markdown",
    )

# Globale Variable für die Bestellungsmenge
chat_info = {}

# Getränkemenü anzeigen (optimierte Darstellung)
def show_drink_menu(chat_id, username):
    session = db_operation(get_session, chat_id)
    if not session:
        bot.send_message(chat_id, "Bitte logge dich zuerst ein mit `/login`.")
        return

    bar_name = username
    assigned_drinks = BARS.get(bar_name, [])

    markup = types.InlineKeyboardMarkup(row_width=2)
    for drink in assigned_drinks:
        markup.add(types.InlineKeyboardButton(drink, callback_data=f"order:{drink}"))

    msg = bot.send_message(
        chat_id,
        "🍹 *Wähle ein Getränk aus:*",
        reply_markup=markup,
        parse_mode="Markdown",
    )

    open_orders = db_operation(get_open_orders, username)
    markup_open_orders = types.InlineKeyboardMarkup(row_width=2)
    for _, _, drink, quantity, _ in open_orders:
        markup_open_orders.add(types.InlineKeyboardButton(f"{quantity} '{drink}'", callback_data=f"order:{drink}"))

    msg2 = bot.send_message(
        chat_id,
        "📋 *Deine offenen Bestellungen:*",
        reply_markup=markup_open_orders,
        parse_mode="Markdown",
    )

    chat_info[chat_id] = {"drink_menu_msg": msg, "open_order_msg": msg2}

# Bestellung bearbeiten
@bot.callback_query_handler(func=lambda call: call.data.startswith("order:"))
def handle_order(call):
    chat_id = call.message.chat.id
    session = db_operation(get_session, chat_id)

    if not session:
        bot.send_message(chat_id, "Bitte logge dich zuerst ein mit `/login`.")
        return

    drink = call.data.split(":")[1]
    username = session[0]
    role = session[1]

    msg = bot.send_message(chat_id, f"Wie oft möchtest du '{drink}' bestellen? (Bitte eine Zahl eingeben)")
    chat_info[chat_id] = {"drink": drink, "username": username, "role": role, "quantity_msg": msg, "drink_menu_msg": chat_info[chat_id]["drink_menu_msg"], "open_order_msg": chat_info[chat_id]["open_order_msg"]}


# Empfang der Menge und Bestellung abschließen
@bot.message_handler(func=lambda message: message.chat.id in chat_info and
                     "drink" in chat_info[message.chat.id].keys() and
                     "role" in chat_info[message.chat.id].keys() and
                     "quantity_msg" in chat_info[message.chat.id].keys() and not
                     message.text.startswith("/"))
def handle_quantity(message):
    chat_id = message.chat.id
    quantity = message.text

    if not quantity.isdigit():
        msg = bot.send_message(chat_id, "❌ Bitte gib eine gültige Zahl ein.")
    else:
        quantity = int(quantity)

    order_info = chat_info.pop(chat_id, None)
    if not order_info:
        msg = bot.send_message(chat_id, "❌ Keine Bestellung gefunden.")
    drink = order_info["drink"]
    username = order_info["username"]
    role = order_info["role"]

    if quantity < 0:
        msg = bot.send_message(chat_id, "❌ Bitte gib eine positive Zahl ein.")
    elif quantity == 0:
        msg = bot.send_message(chat_id, "✅ Nichts wurde bestellt.")
    else:
        db_operation(insert_order, username, role, drink, quantity)
        msg = bot.send_message(chat_id, f"✅ Du hast {quantity} mal '{drink}' bestellt.")
        notify_nachschub(f"Bestellung von {username}: {quantity} mal '{drink}'")

    sleep(1)
    bot.delete_message(chat_id, msg.message_id)
    bot.delete_message(chat_id, message.message_id)
    bot.delete_message(chat_id, order_info["quantity_msg"].message_id)
    bot.delete_message(chat_id, order_info["drink_menu_msg"].message_id)
    bot.delete_message(chat_id, order_info["open_order_msg"].message_id)
    show_drink_menu(chat_id, username)

# Nachschub benachrichtigen
def notify_nachschub(message):
    cursor = db_operation(get_sessions_by_username, 'nachschub')
    for (chat_id,) in cursor:
        msg = bot.send_message(chat_id, message)
        sleep(1)
        bot.delete_message(chat_id, msg.message_id)
        show_open_orders_for_nachschub(chat_id)

def notify_bar_worker(message, username):
    cursor = db_operation(get_sessions_by_username, username)
    for (chat_id,) in cursor:
        bot.send_message(chat_id, message)
        show_bar_orders(chat_id, username)

# Logout-Kommando
@bot.message_handler(commands=["logout"])
def handle_logout(message):
    chat_id = message.chat.id
    session = db_operation(get_session, chat_id)
    if not session:
        bot.send_message(chat_id, "Du bist nicht eingeloggt.")
        return
    db_operation(delete_session, chat_id)
    bot.send_message(chat_id, "Logout erfolgreich!")

# Fehlerbehandlung für unbekannte Befehle
@bot.message_handler(func=lambda message: True)
def handle_unknown_command(message):
    if message.text.startswith("/"):
        bot.send_message(
            message.chat.id,
            "⚠️ Ich habe diesen Befehl nicht erkannt. Bitte verwende die verfügbaren Befehle oder schreibe '/start'."
        )

if __name__ == "__main__":
    print("Bot läuft...")
    register_commands()
    bot.polling(none_stop=True)