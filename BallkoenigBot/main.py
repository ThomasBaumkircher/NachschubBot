import telebot
import json
import os
from telebot import types
import sqlite3

BOT_TOKEN = os.getenv("BOT_KEY")
bot = telebot.TeleBot(BOT_TOKEN)

# Datenbankverbindung herstellen und Tabelle erstellen, falls nicht vorhanden
conn = sqlite3.connect('ballkoenig.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS kandidaten (
        name TEXT PRIMARY KEY,
        geschlecht TEXT,
        punkte INTEGER DEFAULT 0
    )
''')
conn.commit()

# JSON-Datei laden und Kandidaten in die Datenbank einfügen, falls noch nicht vorhanden
try:
    with open('kandidaten.json', 'r', encoding='utf-8') as f:
        kandidaten = json.load(f)
        for kandidat in kandidaten:
            cursor.execute('''
                INSERT OR IGNORE INTO kandidaten (name, geschlecht) VALUES (?, ?)
            ''', (kandidat['name'], kandidat['geschlecht']))
        conn.commit()
except FileNotFoundError:
    print("kandidaten.json nicht gefunden. Bitte erstellen Sie die Datei.")
    exit()


def update_punkte(name, punkte):
    cursor.execute('''
        UPDATE kandidaten SET punkte = punkte + ? WHERE name = ?
    ''', (punkte, name))
    conn.commit()


def get_top_kandidaten(geschlecht, limit=5):
    cursor.execute('''
        SELECT name, punkte FROM kandidaten WHERE geschlecht = ? ORDER BY punkte DESC LIMIT ?
    ''', (geschlecht, limit))
    return cursor.fetchall()


@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item1 = types.KeyboardButton("Spende hinzufügen")
    item2 = types.KeyboardButton("Top 5 anzeigen")
    markup.add(item1, item2)
    bot.send_message(message.chat.id, 'Hauptmenü:', reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Spende hinzufügen")
def spende_hinzufuegen(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item1 = types.KeyboardButton("2 Euro (1 Punkt)")
    item2 = types.KeyboardButton("5 Euro (3 Punkte)")
    item3 = types.KeyboardButton("Abbrechen")
    markup.add(item1, item2, item3)
    bot.send_message(message.chat.id, 'Wähle den Spendenbetrag:', reply_markup=markup)
    bot.register_next_step_handler(message, spendenbetrag_auswahl)

def spendenbetrag_auswahl(message):
    if message.text == "Abbrechen":
        start(message)
        return

    betrag_punkte = {"2 Euro (1 Punkt)": (2, 1), "5 Euro (3 Punkte)": (5, 3)}
    betrag, punkte = betrag_punkte.get(message.text, (None, None))

    if betrag is None:
        bot.send_message(message.chat.id, "Ungültige Auswahl. Bitte wählen Sie einen gültigen Spendenbetrag.")
        spende_hinzufuegen(message)
        return

    msg = bot.send_message(message.chat.id, "Wie oft wurde dieser Betrag gespendet?")
    bot.register_next_step_handler(msg, anzahl_spenden, betrag, punkte)


def anzahl_spenden(message, betrag, punkte):
    try:
        anzahl = int(message.text)
        if anzahl <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "Ungültige Anzahl. Bitte geben Sie eine positive ganze Zahl ein.")
        msg = bot.send_message(message.chat.id, "Wie oft wurde dieser Betrag gespendet?")
        bot.register_next_step_handler(msg, anzahl_spenden, betrag, punkte)
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for kandidat in kandidaten:
        markup.add(types.KeyboardButton(kandidat['name']))
    markup.add(types.KeyboardButton("Abbrechen"))

    msg = bot.send_message(message.chat.id, "Für welchen Kandidaten ist die Spende?", reply_markup=markup)
    bot.register_next_step_handler(msg, kandidat_auswahl, anzahl, punkte)


def kandidat_auswahl(message, anzahl, punkte):
    if message.text == "Abbrechen":
        start(message)
        return

    name = message.text
    if not any(kandidat['name'] == name for kandidat in kandidaten):
        bot.send_message(message.chat.id, "Ungültiger Kandidat. Bitte wählen Sie einen Kandidaten aus der Liste.")
        spende_hinzufuegen(message)
        return

    update_punkte(name, anzahl * punkte)
    bot.send_message(message.chat.id, f"Spende für {name} erfolgreich hinzugefügt!", reply_markup=types.ReplyKeyboardRemove())
    start(message)


@bot.message_handler(func=lambda message: message.text == "Top 5 anzeigen")
def top_5_anzeigen(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Zurück"))

    koenig_liste = "\n".join([f"{name}: {punkte}" for name, punkte in get_top_kandidaten('M')])
    koenigin_liste = "\n".join([f"{name}: {punkte}" for name, punkte in get_top_kandidaten('W')])

    bot.send_message(message.chat.id, f"Top 5 Ballkönige:\n{koenig_liste}\n\nTop 5 Ballköniginnen:\n{koenigin_liste}", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Zurück")
def zurueck(message):
    start(message)


bot.polling()