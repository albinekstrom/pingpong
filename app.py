import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import schedule
import time
from datetime import datetime
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Hämta miljövariabler
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

app = App(token=SLACK_BOT_TOKEN)

# Anslut till PostgreSQL-databasen
conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
c = conn.cursor()

# Skapa tabeller om de inte finns
c.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        id SERIAL PRIMARY KEY,
        player1 TEXT NOT NULL,
        player2 TEXT NOT NULL,
        time TEXT NOT NULL
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS results (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        player1 TEXT NOT NULL,
        score1 INTEGER NOT NULL,
        player2 TEXT NOT NULL,
        score2 INTEGER NOT NULL
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS leaderboard (
        player TEXT PRIMARY KEY,
        points INTEGER DEFAULT 0
    )
''')

conn.commit()

# Funktioner för att hantera matcher och resultat
def post_weekly_matches():
    c.execute('SELECT player1, player2, time FROM matches')
    all_matches = c.fetchall()
    message = "📅 **Veckans Matcher:**\n"
    for match in all_matches:
        message += f"{match['player1']} vs {match['player2']} på {match['time']}\n"
    try:
        app.client.chat_postMessage(channel='#pingis-kanal', text=message)
    except Exception as e:
        print(f"Error posting weekly matches: {e}")

def post_daily_results():
    today = datetime.now().date()
    c.execute('SELECT player1, score1, player2, score2 FROM results WHERE date = %s', (today,))
    todays_results = c.fetchall()
    if not todays_results:
        message = "Inga matcher idag."
    else:
        message = "🏓 **Dagens Resultat:**\n"
        for result in todays_results:
            message += f"{result['player1']} {result['score1']} - {result['score2']} {result['player2']}\n"
            # Uppdatera leaderboard
            if result['score1'] > result['score2']:
                c.execute('INSERT INTO leaderboard (player, points) VALUES (%s, 1) ON CONFLICT(player) DO UPDATE SET points = leaderboard.points + 1', (result['player1'],))
            elif result['score2'] > result['score1']:
                c.execute('INSERT INTO leaderboard (player, points) VALUES (%s, 1) ON CONFLICT(player) DO UPDATE SET points = leaderboard.points + 1', (result['player2'],))
    # Hämta leaderboard
    c.execute('SELECT player, points FROM leaderboard ORDER BY points DESC')
    lb = c.fetchall()
    table_message = "**Leaderboard:**\n"
    for player in lb:
        table_message += f"{player['player']}: {player['points']} poäng\n"
    conn.commit()
    # Skicka meddelande
    try:
        app.client.chat_postMessage(channel='#pingis-kanal', text=message + "\n" + table_message)
    except Exception as e:
        print(f"Error posting daily results: {e}")

# Schemaläggning
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

schedule.every().monday.at("09:00").do(post_weekly_matches)
schedule.every().day.at("18:00").do(post_daily_results)

# Slash-kommando för att lägga in match
@app.command("/lägginmatch")
def handle_lagg_in_match(ack, command, respond):
    ack()
    try:
        _, player1, player2, match_time = command['text'].split()
        c.execute('INSERT INTO matches (player1, player2, time) VALUES (%s, %s, %s)', (player1, player2, match_time))
        conn.commit()
        respond(f"Match tillagd: {player1} vs {player2} på {match_time}")
    except ValueError:
        respond("Fel format! Använd: /lägginmatch player1 player2 time")

# Slash-kommando för att rapportera resultat
@app.command("/rapporteraresultat")
def handle_report_result(ack, command, respond):
    ack()
    try:
        _, player1, score1, player2, score2 = command['text'].split()
        c.execute('INSERT INTO results (date, player1, score1, player2, score2) VALUES (%s, %s, %s, %s, %s)',
                  (datetime.now().date(), player1, int(score1), player2, int(score2)))
        # Uppdatera leaderboard
        if int(score1) > int(score2):
            c.execute('INSERT INTO leaderboard (player, points) VALUES (%s, 1) ON CONFLICT(player) DO UPDATE SET points = leaderboard.points + 1', (player1,))
        elif int(score2) > int(score1):
            c.execute('INSERT INTO leaderboard (player, points) VALUES (%s, 1) ON CONFLICT(player) DO UPDATE SET points = leaderboard.points + 1', (player2,))
        conn.commit()
        respond(f"Resultat rapporterat: {player1} {score1} - {score2} {player2}")
    except ValueError:
        respond("Fel format! Använd: /rapporteraresultat player1 score1 player2 score2")

# Starta schemaläggningen i en separat tråd
schedule_thread = threading.Thread(target=run_schedule)
schedule_thread.start()

# Starta appen
if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()

