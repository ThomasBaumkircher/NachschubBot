import telebot
import json
import os
from telebot import types
import sqlite3
from time import sleep

BOT_TOKEN = os.getenv("BOT_KEY")
bot = telebot.TeleBot(BOT_TOKEN)

# Dictionary to store message IDs for each chat
chat_message_ids = {}


def clear_chat_messages(chat_id):
    if chat_id in chat_message_ids:
        for message_id in chat_message_ids[chat_id]:
            try:
                bot.delete_message(chat_id, message_id)
            except telebot.apihelper.ApiException as e:
                if e.error_code != 400:  # Ignore "Bad Request"
                    print(f"Error deleting message {message_id}: {e}")
        del chat_message_ids[chat_id]


def db_operation(func, *args):
    conn = sqlite3.connect('ballkoenig.db')
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


def create_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kandidaten (
            name TEXT PRIMARY KEY,
            geschlecht TEXT,
            punkte INTEGER DEFAULT 0
        )
    ''')


def insert_kandidaten(cursor, kandidaten):
    for kandidat in kandidaten:
        cursor.execute('''
            INSERT OR IGNORE INTO kandidaten (name, geschlecht) VALUES (?, ?)
        ''', (kandidat['name'], kandidat['geschlecht']))


def update_punkte(cursor, name, punkte):
    cursor.execute('''
        UPDATE kandidaten SET punkte = punkte + ? WHERE name = ?
    ''', (punkte, name))


def get_top_kandidaten(cursor, geschlecht, limit=5):
    cursor.execute('''
        SELECT name, punkte FROM kandidaten WHERE geschlecht = ? ORDER BY punkte DESC LIMIT ?
    ''', (geschlecht, limit))
    return cursor.fetchall()


# JSON-Datei laden and database initialization
try:
    with open('kandidaten.json', 'r', encoding='utf-8') as f:
        kandidaten_data = json.load(f)
        db_operation(create_table)
        db_operation(insert_kandidaten, kandidaten_data)
except FileNotFoundError:
    print("kandidaten.json nicht gefunden. Bitte erstellen Sie die Datei.")
    exit()


@bot.message_handler(commands=['start'])
def start(message):
    clear_chat_messages(message.chat.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item1 = types.KeyboardButton("Spende hinzufügen")
    item2 = types.KeyboardButton("Top 5 anzeigen")
    markup.add(item1, item2)
    msg = bot.send_message(message.chat.id, 'Hauptmenü:', reply_markup=markup)
    chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)


@bot.message_handler(func=lambda message: message.text == "Spende hinzufügen")
def spende_hinzufuegen(message):
    clear_chat_messages(message.chat.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item1 = types.KeyboardButton("2 Euro (1 Punkt)")
    item2 = types.KeyboardButton("5 Euro (3 Punkte)")
    item3 = types.KeyboardButton("Abbrechen")
    markup.add(item1, item2, item3)
    msg = bot.send_message(message.chat.id, 'Wähle den Spendenbetrag:', reply_markup=markup)
    chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
    bot.register_next_step_handler(message, spendenbetrag_auswahl)


def spendenbetrag_auswahl(message):
    clear_chat_messages(message.chat.id)
    if message.text == "Abbrechen":
        start(message)
        return

    betrag_punkte = {"2 Euro (1 Punkt)": (2, 1), "5 Euro (3 Punkte)": (5, 3)}
    betrag, punkte = betrag_punkte.get(message.text, (None, None))

    if betrag is None:
        msg = bot.send_message(message.chat.id, "Ungültige Auswahl. Bitte wählen Sie einen gültigen Spendenbetrag.")
        chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
        sleep(1)
        spende_hinzufuegen(message)
        return

    msg = bot.send_message(message.chat.id, "Wie oft wurde dieser Betrag gespendet? (Bitte Zahl eingeben)", reply_markup=types.ReplyKeyboardRemove())
    chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
    bot.register_next_step_handler(msg, anzahl_spenden, betrag, punkte)


def anzahl_spenden(message, betrag, punkte):
    clear_chat_messages(message.chat.id)
    try:
        anzahl = int(message.text)
        if anzahl <= 0:
            raise ValueError
    except ValueError:
        if message.text == "Abbrechen":
            start(message)
            return
        msg = bot.send_message(message.chat.id, "Ungültige Anzahl. Bitte geben Sie eine positive ganze Zahl ein.")
        chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
        msg = bot.send_message(message.chat.id, "Wie oft wurde dieser Betrag gespendet?")
        chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
        bot.register_next_step_handler(msg, anzahl_spenden, betrag, punkte)
        return

    with open('kandidaten.json', 'r', encoding='utf-8') as f:
        kandidaten = json.load(f)

    msg = bot.send_message(message.chat.id, "Geben Sie den Namen des Kandidaten ein (oder einen Teil davon):", reply_markup=types.ReplyKeyboardRemove())
    chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
    bot.register_next_step_handler(msg, kandidat_auswahl, anzahl, punkte, kandidaten)


def kandidat_auswahl(message, anzahl, punkte, kandidaten):
    clear_chat_messages(message.chat.id)
    if message.text == "Abbrechen":
        start(message)
        return

    entered_name = message.text.lower()
    matching_kandidaten = [kandidat for kandidat in kandidaten if entered_name in kandidat['name'].lower()]

    if not matching_kandidaten:
        msg = bot.send_message(message.chat.id, "Kein Kandidat gefunden. Bitte versuchen Sie es erneut.", reply_markup=types.ReplyKeyboardRemove())
        chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
        bot.register_next_step_handler(msg, kandidat_auswahl, anzahl, punkte, kandidaten)
        return


    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for kandidat in matching_kandidaten:
        markup.add(types.KeyboardButton(kandidat['name']))
    markup.add(types.KeyboardButton("Abbrechen"))

    msg = bot.send_message(message.chat.id, "Wählen Sie den Kandidaten oder geben Sie den Namen des Kandidaten ein (oder einen Teil davon):", reply_markup=markup)
    chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
    bot.register_next_step_handler(msg, kandidat_auswahl_from_list, anzahl, punkte)



def kandidat_auswahl_from_list(message, anzahl, punkte): # Handler for list selection
    clear_chat_messages(message.chat.id)
    if message.text == "Abbrechen":
        start(message)
        return

    name = message.text
    with open('kandidaten.json', 'r', encoding='utf-8') as f:
        kandidaten = json.load(f)

    if not any(kandidat['name'] == name for kandidat in kandidaten):
        kandidat_auswahl(message, anzahl, punkte, kandidaten)
        return

    db_operation(update_punkte, name, anzahl * punkte)
    msg = bot.send_message(message.chat.id, f"Spende für {name} erfolgreich hinzugefügt!", reply_markup=types.ReplyKeyboardRemove())
    chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)
    sleep(1)
    start(message)



@bot.message_handler(func=lambda message: message.text == "Top 5 anzeigen")
def top_5_anzeigen(message):
    clear_chat_messages(message.chat.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Zurück"))

    koenig_liste = "\n".join([f"{name}: {punkte}" for name, punkte in db_operation(get_top_kandidaten, 'M')])
    koenigin_liste = "\n".join([f"{name}: {punkte}" for name, punkte in db_operation(get_top_kandidaten, 'W')])

    msg = bot.send_message(message.chat.id, f"Top 5 Ballkönige:\n{koenig_liste}\n\nTop 5 Ballköniginnen:\n{koenigin_liste}", reply_markup=markup)
    chat_message_ids.setdefault(message.chat.id, []).append(msg.message_id)


@bot.message_handler(func=lambda message: message.text == "Zurück")
def zurueck(message):
    start(message)


if __name__ == "__main__":
    print("Ballkönig Bot läuft...")
    bot.polling(none_stop=True)