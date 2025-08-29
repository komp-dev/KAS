# KAS server - server to sync and store all the attempts
# Copyright (C) 2025  komp
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty o
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import datetime as dt
import json
import pathlib
import shutil
import sqlite3
import sys
import websockets


kas_db = None
apple_client = None
obs_client = None

KAS = {
    "state": "idle",
    "attempt": None,
    "progress": None,
    "stats": None,
}

def create_database():
    db = sqlite3.connect("kas.db")

    cur = db.cursor()
    cur.execute((
        "CREATE TABLE history(\n"
        "    id                  INTEGER     PRIMARY KEY,\n"
        "    version             INTEGER     DEFAULT 1,\n"
        "    last_updated        DATETIME    DEFAULT CURRENT_TIMESTAMP NOT NULL\n"
        ")"
    ))

    cur.execute((
        "CREATE TABLE attempts(\n"
        "    id                  INTEGER     PRIMARY KEY,\n"
        "    started             DATETIME    NOT NULL UNIQUE,\n"
        "    ended               DATETIME    NOT NULL,\n"
        "    score               INTEGER     NOT NULL,\n"
        "    finished            BOOLEAN     NOT NULL,\n"
        "    perfect             BOOLEAN     NOT NULL,\n"
        "    duration            REAL        NOT NULL\n"
        ")"
    ))

    cur.execute("INSERT INTO history(version) VALUES (1)")
    db.commit()

    return db

def open_database():
    global kas_db

    db_path = pathlib.Path("kas.db")
    if db_path.is_dir():
        print("Invalid database!")
        return False

    if not db_path.exists():
        kas_db = create_database()
    else:
        kas_db = sqlite3.connect("kas.db")

    return True

def close_database():
    global kas_db
    if kas_db is not None:
        kas_db.close()

def read_history_metadata():
    cur = kas_db.cursor()
    res = cur.execute("SELECT * FROM history WHERE id = 1 LIMIT 1")
    meta = res.fetchone()
    _, version, last_updated = meta
    return {
        "version": version,
        "last_updated": last_updated
    }

def write_history_metadata(meta):
    cur = kas_db.cursor()
    res = cur.execute(
        "UPDATE history SET last_updated = '{}' WHERE id = 1".format(meta["last_updated"]))
    kas_db.commit()

def update_history_last_modified(date: dt.datetime):
    d = date.isoformat()
    cur = kas_db.cursor()
    res = cur.execute(
        "UPDATE history SET last_updated = '{}' WHERE id = 1".format(d))
    kas_db.commit()

def merge_history(history):
    # Javascript Date.now() holds time in milliseconds.
    # While datetime.fromtimestamp() expect time in seconds.
    time_py = int(history["lastUpdated"] / 1000)
    hist_last_updated = dt.datetime.fromtimestamp(time_py, None)

    meta = read_history_metadata()
    db_last_updated = dt.datetime.fromisoformat(meta["last_updated"])

    # if db_last_updated >= hist_last_updated:
    #    return

    cur = kas_db.cursor()
    for a in history["attempts"]:
        cur.execute((
            "INSERT OR IGNORE INTO attempts("
            "started, ended, score, finished, perfect, duration"
            ") VALUES({}, {}, {}, {}, {}, {})".format(
                a["started"], a["ended"], a["score"], a["finished"], a["perfect"], a["duration"]
            )
        ))

    kas_db.commit()

    update_history_last_modified(dt.datetime.now())

def get_history_attempts(num_of_attempts_to_get):
    cur = kas_db.cursor()
    res = cur.execute(
        "SELECT * FROM attempts ORDER BY id DESC LIMIT {}".format(num_of_attempts_to_get))
    db_attempts = res.fetchall()
    attempts = []
    for db_att in db_attempts:
        id, started, ended, score, finished, perfect, duration = db_att
        attempts.append(
            {
                "id": id,
                "started": started,
                "ended": ended,
                "score": score,
                "finished": finished,
                "perfect": perfect,
                "duration": duration,
            }
        )

    return list(reversed(attempts))

def add_new_attempt_to_history(attempt):
    cur = kas_db.cursor()
    cur.execute((
        "INSERT OR IGNORE INTO attempts("
        "started, ended, score, finished, perfect, duration"
        ") VALUES({}, {}, {}, {}, {}, {})".format(
            attempt["started"],
            attempt["ended"],
            attempt["score"],
            attempt["finished"],
            attempt["perfect"],
            attempt["duration"]
        )
    ))

    kas_db.commit()

def get_number_of_attempts():
    cur = kas_db.cursor()
    res = cur.execute("SELECT id FROM attempts ORDER BY id DESC LIMIT 1")
    attempts_number, *rest_ = res.fetchone() or (0,)
    return attempts_number

def get_best_score():
    cur = kas_db.cursor()
    res = cur.execute("SELECT MAX(score) FROM attempts")
    max_score, *rest = res.fetchone() or (0,)
    return max_score

def get_avg_score():
    cur = kas_db.cursor()
    res = cur.execute("SELECT AVG(score) FROM attempts")
    avg_score, *rest = res.fetchone() or (0,)
    return avg_score

def get_total_playtime():
    cur = kas_db.cursor()
    res = cur.execute("SELECT SUM(duration) FROM attempts")
    total_playtime, *rest = res.fetchone() or (0.0,)
    return total_playtime

def dump_remote_history(history):
    dumps_dir = pathlib.Path("./dumps/")
    dumps_dir.mkdir(exist_ok=True)

    t = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dump_path = dumps_dir / "{}.json".format(t)

    with open(dump_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(history))

async def obs_client_send(msg, obj):
    if obs_client is not None:
        payload = {"msg": msg, "data": obj}
        await obs_client.send(json.dumps(payload))

async def obs_client_on_open():
    if obs_client is not None:
        await obs_client_update_history()
        await update_stats()

async def obs_client_update_history():
    if obs_client is not None:
        attempts = get_history_attempts(20)
        await obs_client_send("history", attempts)

async def obs_client_start_attempt():
    if obs_client is not None:
        await obs_client_send("attemptStart", KAS["id"])

async def obs_client_end_attempt():
    if obs_client is not None:
        await obs_client_send("attemptEnd", KAS["attempt"])

async def obs_client_update_progress():
    if obs_client is not None:
        await obs_client_send("progress", KAS["progress"])

async def obs_client_update_stats():
    if obs_client is not None:
        await obs_client_send("stats", KAS["stats"])

async def apple_client_send(msg, obj):
    if apple_client is not None:
        payload = {"msg": msg, "data": obj}
        await apple_client.send(json.dumps(payload))

async def apple_client_on_open():
    if apple_client is not None:
        pass

async def sync_history(data):
    print("Synchronizing local history with remote...")
    # dump_remote_history(data)
    merge_history(data)
    await obs_client_update_history()

async def start_new_attempt():
    global KAS

    print("Starting new attempt...")

    KAS["state"] = "playing"
    KAS["id"] = get_number_of_attempts() + 1
    KAS["attempt"] = None
    KAS["progress"] = None

    await obs_client_start_attempt()

async def finish_attempt(attempt):
    global KAS

    print("Finished attempt.")

    add_new_attempt_to_history(attempt)

    KAS["attempt"] = attempt
    await obs_client_end_attempt()

    KAS["state"] = "idle"
    KAS["id"] = 0
    KAS["attempt"] = None
    KAS["progress"] = None

async def update_progress(progress):
    global KAS

    KAS["progress"] = progress
    KAS["progress"]["id"] = KAS["id"]
    await obs_client_update_progress()

async def update_stats():
    global KAS

    avg_score = get_avg_score()
    best_score = get_best_score()
    num_of_attempts = get_number_of_attempts()

    elapsed = 0
    extraScore = 0
    if KAS["progress"] is not None:
        elapsed = 120 - KAS["progress"]["timeRemaining"]
        extraScore = KAS["progress"]["score"]
        avg_score = ((avg_score * num_of_attempts) + extraScore) / (num_of_attempts + 1)

        if KAS["progress"]["score"] > best_score:
            best_score = KAS["progress"]["score"]

    stats = {}
    stats["bestScore"] = best_score
    stats["avgScore"] = avg_score
    stats["totalPlaytime"] = int(get_total_playtime() + int(elapsed))
    stats["numberOfAttempts"] = num_of_attempts

    KAS["stats"] = stats
    await obs_client_update_stats()

async def process_apple_client_message(msg, data):
    if msg == "history":
        await sync_history(data)
    elif msg == "attemptStart":
        await start_new_attempt()
        await update_stats()
    elif msg == "attemptEnd":
        await finish_attempt(data)
        await update_stats()
    elif msg == "progress":
        if KAS["state"] != "playing":
            await start_new_attempt()

        await update_progress(data)
        await update_stats()

async def process_obs_client_message(msg, data):
    pass

async def identify_client(client_info, websocket):
    global apple_client
    global obs_client

    if client_info["name"] == "apple":
        if apple_client is not None:
            print("Apple client is already connected!")
        else:
            print("Apple client connected.")
            apple_client = websocket
            await apple_client_on_open()
    elif client_info["name"] == "obs":
        if obs_client is not None:
            print("Obs client is already connected!")
        else:
            print("Obs client connected.")
            obs_client = websocket
            await obs_client_on_open()

def unpack_payload(message):
    try:
        payload = json.loads(message)
    except:
        # print("Failed to deserialize json!")
        raise ValueError("invalid message")

    return (payload["msg"], payload["data"])

async def process_message(message, websocket):
    try:
        msg, data = unpack_payload(message)
    except ValueError:
        print("Failed to process message!")
        return

    # print("msg: {}, data: {}".format(msg, data))

    if msg == "clientInfo":
        await identify_client(data, websocket)
    else:
        if websocket == apple_client:
            await process_apple_client_message(msg, data)
        elif websocket == obs_client:
            await process_obs_client_message(msg, data)

async def handler(websocket):
    global apple_client
    global obs_client

    # print("Client connected.")
    try:
        async for message in websocket:
            await process_message(message, websocket)
    finally:
        if websocket == apple_client:
            print("Apple client disconnected.")
            apple_client = None
        elif websocket == obs_client:
            print("Obs client disconnected.")
            obs_client = None
        else:
            pass
            # print("Client disconnected.")

async def server_input():
    try:
        while True:
            msg = await asyncio.to_thread(input, "")
            if msg == "q":
                print("Shutting down...")
                break
    except Exception as e:
        pass

async def start_server():
    server = await websockets.serve(handler, "localhost", 8765)
    print("Server is running on ws://localhost:8765")
    print("Waiting for client connections...")
    print("Enter 'q' to quit")

async def main():
    await asyncio.gather(server_input(), start_server())

if __name__ == "__main__":
    if not open_database():
        sys.exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

    close_database()
