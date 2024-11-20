import json
import os
import sqlite3
from telebot import TeleBot, types

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

# SQLite-Datenbank einrichten
DB_FILE = "orders.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS sessions (
    chat_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    role TEXT NOT NULL
)
""")
conn.commit()

# Helper: Prüft Login
def authenticate_user(username, password):
    user = USERS.get(username)
    if user and user["password"] == password:
        return user["role"]
    return None

# Helper: Benutzer-Sitzung speichern
def save_session(chat_id, username, role):
    cursor.execute("REPLACE INTO sessions (chat_id, username, role) VALUES (?, ?, ?)", (chat_id, username, role))
    conn.commit()

# Helper: Benutzer-Sitzung löschen
def delete_session(chat_id):
    cursor.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
    conn.commit()

# Helper: Benutzer-Sitzung abrufen
def get_session(chat_id):
    cursor.execute("SELECT username, role FROM sessions WHERE chat_id = ?", (chat_id,))
    return cursor.fetchone()

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
    bot.send_message(
        chat_id,
        "Willkommen beim Maturaball-Bot! Bitte logge dich ein.\n"
        "Sende deinen Benutzernamen und das Passwort im Format:\n\n"
        "`/login <Benutzername> <Passwort>`",
        parse_mode="Markdown",
    )

# Login-Kommando
@bot.message_handler(commands=["login"])
def handle_login(message):
    chat_id = message.chat.id

    # Überprüfen, ob der Benutzer bereits eingeloggt ist
    if get_session(chat_id):
        bot.send_message(chat_id, "Du bist bereits eingeloggt.")
        return

    try:
        _, username, password = message.text.split()
    except ValueError:
        bot.send_message(chat_id, "Ungültiges Format! Bitte verwende `/login <Benutzername> <Passwort>`.")
        return

    role = authenticate_user(username, password)
    if role:
        save_session(chat_id, username, role)
        bot.send_message(chat_id, f"Login erfolgreich!")
        
        # Nach dem Login: Anzeigen der offenen Bestellungen
        if role == "bar":
            show_bar_orders(chat_id, username)  # Bar-Arbeiter bekommt offene Bestellungen angezeigt
            show_drink_menu(chat_id, username)  # Getränkemenü anzeigen
        elif role == "nachschub":
            show_open_orders_for_nachschub(chat_id)  # Nachschub-Mitarbeiter bekommt offene Bestellungen angezeigt
            
    else:
        bot.send_message(chat_id, "Ungültige Zugangsdaten. Bitte versuche es erneut.")

# Zeigt alle offenen Bestellungen für Nachschub-Mitarbeiter nach Login
def show_open_orders_for_nachschub(chat_id):
    # Holen Sie sich alle offenen Bestellungen aus der Datenbank
    cursor.execute("""
    SELECT id, username, drink, quantity, status FROM orders 
    WHERE status = 'offen'
    """)
    rows = cursor.fetchall()

    if not rows:
        bot.send_message(chat_id, "✅ Es gibt derzeit keine offenen Bestellungen für den Nachschub.")
        return

    # Erstellen Sie eine Inline-Tastatur, um die Bestellungen anzuzeigen
    markup = types.InlineKeyboardMarkup(row_width=1)
    for order_id, username, drink, quantity, status in rows:
        if status == "offen":
            markup.add(types.InlineKeyboardButton(
                f"Bestellung von {username}: {quantity} Kisten '{drink}'",
                callback_data=f"process_order:{order_id}"
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

    # Hole die Bestellung aus der Datenbank
    cursor.execute("""
    SELECT id, username, drink, quantity, status FROM orders
    WHERE id = ?
    """, (order_id,))
    order = cursor.fetchone()

    if order is None:
        bot.answer_callback_query(call.id, "❌ Bestellung nicht gefunden.")
        return

    # Status der Bestellung abfragen (ob sie bereits bearbeitet wurde)
    _, username, drink, quantity, status = order
    if status != "offen":
        bot.answer_callback_query(call.id, "❌ Diese Bestellung ist bereits abgeschlossen.")
        return

    # Frage den Nachschub-Mitarbeiter, ob die Bestellung als "abgesendet" markiert werden soll
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Bestellung als 'abgesendet' markieren", callback_data=f"mark_as_sent:{order_id}"))

    # Update der Bestellung in der Datenbank
    cursor.execute("""
    UPDATE orders SET status = 'entsandt' WHERE id = ?
    """, (order_id,))
    conn.commit() 

    bot.answer_callback_query(call.id, "✅ Bestellung wurde als 'abgesendet' markiert.")
    bot.send_message(chat_id, "✅ Bestellung wurde als 'abgesendet' markiert.")

    show_open_orders_for_nachschub(chat_id)  # Aktualisiere die offenen Bestellungen

# Bar-Arbeiter: Eigene Bestellungen anzeigen
def show_bar_orders(chat_id, username):
    session = get_session(chat_id)
    if not session or session[1] != "bar":
        bot.send_message(chat_id, "❌ Dieser Befehl ist nur für Bar-Arbeiter verfügbar.")
        return

    # Getränke, die dem Bar-Arbeiter zugewiesen sind
    bar_name = username  # Zum Beispiel bar1_user -> bar1
    assigned_drinks = BARS.get(bar_name, [])
    
    # Abfragen der offenen Bestellungen, die für diese Bar relevant sind
    cursor.execute("""
    SELECT id, drink, quantity, status FROM orders 
    WHERE username = ? AND drink IN (?) AND status = 'offen'""", 
    (username, ','.join(assigned_drinks)))
    rows = cursor.fetchall()

    if not rows:
        bot.send_message(chat_id, "✅ Du hast keine offenen Bestellungen.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for order_id, drink, quantity, status in rows:
        if status == "offen":
            markup.add(types.InlineKeyboardButton(
                f"{quantity} Kisten '{drink}'",
                callback_data=f"order:{order_id}"
            ))

    bot.send_message(
        chat_id,
        "📋 *Deine offenen Bestellungen:*",
        reply_markup=markup,
        parse_mode="Markdown",
    )

# Getränkemenü anzeigen (optimierte Darstellung)
def show_drink_menu(chat_id, username):
    session = get_session(chat_id)
    if not session:
        bot.send_message(chat_id, "Bitte logge dich zuerst ein mit `/login`.")
        return
    
    # Getränke, die dem Bar-Arbeiter zugewiesen sind
    bar_name = username  # Zum Beispiel bar1_user -> bar1
    assigned_drinks = BARS.get(bar_name, [])
    
    markup = types.InlineKeyboardMarkup(row_width=2)  # Zwei Spalten pro Zeile
    for drink in assigned_drinks:
        markup.add(types.InlineKeyboardButton(drink, callback_data=f"order:{drink}"))
    
    bot.send_message(
        chat_id,
        "🍹 *Wähle ein Getränk aus:*",
        reply_markup=markup,
        parse_mode="Markdown",
    )

# Globale Variable für die Bestellungsmenge
awaiting_quantity = {}

# Bestellung bearbeiten
@bot.callback_query_handler(func=lambda call: call.data.startswith("order:"))
def handle_order(call):
    chat_id = call.message.chat.id
    session = get_session(chat_id)

    if not session:
        bot.send_message(chat_id, "Bitte logge dich zuerst ein mit `/login`.")
        return

    drink = call.data.split(":")[1]
    username = session[0]
    role = session[1]

    # Die Bestellung speichern, aber auf die Menge warten
    awaiting_quantity[chat_id] = {"drink": drink, "username": username, "role": role}
    bot.send_message(chat_id, f"Wie viele Kisten von '{drink}' möchtest du bestellen? (Bitte eine Zahl eingeben)")

# Empfang der Menge und Bestellung abschließen
@bot.message_handler(func=lambda message: message.chat.id in awaiting_quantity)
def handle_quantity(message):
    chat_id = message.chat.id
    quantity = message.text

    # Überprüfen, ob die Eingabe eine gültige Zahl ist
    if not quantity.isdigit():
        bot.send_message(chat_id, "❌ Bitte gib eine gültige Zahl ein.")
        return

    quantity = int(quantity)
    order_info = awaiting_quantity.pop(chat_id, None)

    if not order_info:
        bot.send_message(chat_id, "❌ Keine Bestellung gefunden.")
        return

    drink = order_info["drink"]
    username = order_info["username"]
    role = order_info["role"]

    # Bestellung in die Datenbank einfügen
    cursor.execute("""
    INSERT INTO orders (username, role, drink, quantity, status) 
    VALUES (?, ?, ?, ?, 'offen')
    """, (username, role, drink, quantity))
    conn.commit()

    bot.send_message(chat_id, f"✅ Du hast {quantity} Kisten '{drink}' bestellt.")

    # Bestätigung der Bestellung
    notify_nachschub(f"Bestellung von {username}: {quantity} Kisten '{drink}'")

# Nachschub benachrichtigen
def notify_nachschub(message):
    cursor.execute("SELECT chat_id FROM sessions WHERE role = 'nachschub'")
    for (chat_id,) in cursor.fetchall():
        bot.send_message(chat_id, message)
        show_open_orders_for_nachschub(chat_id)  # Nachschub-Mitarbeiter bekommt offene Bestellungen angezeigt

# Logout-Kommando
@bot.message_handler(commands=["logout"])
def handle_logout(message):
    chat_id = message.chat.id

    sessions = get_session(chat_id)
    if not sessions:
        bot.send_message(chat_id, "Du bist nicht eingeloggt.")
        return
    
    delete_session(chat_id)

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
    register_commands()  # Befehle registrieren
    bot.polling(none_stop=True)
