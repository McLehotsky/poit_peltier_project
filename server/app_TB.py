import pymysql
from threading import Lock
import random  # Nezabudni pridať import na vrch súboru


def test_data_emitter():
    """Simulátor dát pre grafy (Pumpa, TEC, Teplota)"""
    print("Simulátor dát spustený...")
    while True:
        # Generujeme realistické testovacie dáta
        test_data = {
            "temperature": round(random.uniform(20.0, 25.0), 2),  # Fluktuácia okolo 22 stupňov
            "pump_pwm": random.randint(100, 255),  # Náhodný výkon pumpy
            "tec_pwm": random.randint(50, 150),  # Náhodný výkon Peltieru
            "setpoint": system_state.get('setpoint', 25.0)
        }

        # Odošleme cez Socket.io (namespace a event musia sedieť s tvojím JS)
        socketio.emit('new_data', test_data, namespace='/test')

        socketio.sleep(2)  # Počkáme 2 sekundy pred ďalšou dávkou


pymysql.install_as_MySQLdb()  # Windows fix

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import configparser
import json
import requests
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

#  APLIKÁCIA
app = Flask(__name__)
app.config['SECRET_KEY'] = 'peltier_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

thread = None
thread_lock = Lock()

config = configparser.ConfigParser()
config.read('config.cfg')

#  THINGSBOARD KONFIGURÁCIA
TB_HOST = "eu.thingsboard.cloud"
TB_PORT = 1883
TB_TOKEN = "X9ttptsR0dW5gvE3wYTT"


# --- 2. UPRAVENÉ MQTT CALLBACKS ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Úspešne pripojené k ThingsBoardu")
        # Prihlásime sa na RPC príkazy
        client.subscribe("v1/devices/me/rpc/request/+")
        # NOVÉ: Shared attributes (pump_pwm, tec_pwm, control_mode)
        client.subscribe("v1/devices/me/attributes")
    else:
        print(f"[MQTT] Chyba pripojenia: {rc}")


def on_message(client, userdata, msg):
    global system_state
    try:
        data = json.loads(msg.payload)

        # NOVÉ: SHARED ATTRIBUTES (PWM inputy + Mod tlačidlá)
        if msg.topic == "v1/devices/me/attributes":
            print(f"[ATTR] Shared attribute update: {data}")

            if "target_pump_pwm" in data:
                system_state['target_pump_pwm'] = int(data['target_pump_pwm'])
                print(f"[ATTR] target_pump_pwm → {system_state['target_pump_pwm']}")
                socketio.emit('status_update', {'target_pump': system_state['target_pump_pwm']}, namespace='/test')

            if "target_tec_pwm" in data:
                system_state['target_tec_pwm'] = int(data['target_tec_pwm'])
                print(f"[ATTR] target_tec_pwm → {system_state['target_tec_pwm']}")
                socketio.emit('status_update', {'target_tec': system_state['target_tec_pwm']}, namespace='/test')


            if "control_mode" in data:
                system_state['mode'] = int(data['control_mode'])
                print(f"[ATTR] mode → {system_state['mode']}")
                socketio.emit('status_update', {'mode': system_state['mode']}, namespace='/test')

            return  # nie je to RPC, skončíme tu

        method = data.get("method")
        params = data.get("params")

        print(f"[RPC] Príkaz z TB -> Metóda: {method}, Hodnota: {params}")

        # Mapovanie RPC metód na náš stav
        if method == "setPumpPwm":
            system_state['target_pump_pwm'] = int(params)
            socketio.emit('status_update', {'target_pump': params}, namespace='/test')

        elif method == "setTecPwm":
            system_state['target_tec_pwm'] = int(params)
            socketio.emit('status_update', {'target_tec': params}, namespace='/test')

        elif method == "setMode":
            system_state['mode'] = int(params)
            socketio.emit('status_update', {'mode': params}, namespace='/test')

        elif method == "setRunning":
            system_state['running'] = bool(params)
            if not system_state['running']:
                save_session_to_db_and_json()
            socketio.emit('status_update', {'running': system_state['running']}, namespace='/test')

        # NOVÉ: Connect tlačidlo z TB
        elif method == "setConnected":
            system_state['connected'] = bool(params)
            if not system_state['connected']:
                system_state['running'] = False
                system_state['session_buffer'] = []
            status_text = "PRIPOJENÉ" if system_state['connected'] else "ODPOJENÉ"
            print(f"[RPC] Systém je teraz: {status_text}")
            socketio.emit('status_update', {'connected': system_state['connected']}, namespace='/test')

        # NOVÉ: RPC odpoveď späť do TB
        request_id = msg.topic.split('/')[-1]
        mqtt_client.publish(
            f"v1/devices/me/rpc/response/{request_id}",
            json.dumps({"status": "ok"})
        )

    except Exception as e:
        print(f"[RPC Error] Chyba pri spracovaní správy: {e}")


# --- 3. MQTT KLIENT (ponechaj tak ako máš) ---
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.username_pw_set(TB_TOKEN)
mqtt_client.connect(TB_HOST, TB_PORT, 60)
mqtt_client.loop_start()


def send_to_thingsboard(data: dict):
    """Publikovanie telemetrie (vylepšené)"""
    try:
        # Telemetria (grafy)
        mqtt_client.publish("v1/devices/me/telemetry", json.dumps(data))

        # NOVÉ: Terminal widget (shared attribute)
        running_text = "RUN" if system_state['running'] else "STOP"
        terminal = (
            f"T={data.get('temperature', 0):.1f}°C | "
            f"Err={data.get('error', 0):.2f} | "
            f"{running_text} | "
            f"Mode={system_state['mode']}"
        )
        mqtt_client.publish(
            "v1/devices/me/attributes",
            json.dumps({"terminal": terminal})
        )
    except Exception as e:
        print(f"[MQTT] Chyba odosielania: {e}")


#  JSON SÚBOR  (záloha dát)

JSON_FILE = "data_log.json"


def get_db():
    return pymysql.connect(
        host=config.get('mysqlDB', 'host', fallback='localhost'),
        user=config.get('mysqlDB', 'user', fallback='root'),
        password=config.get('mysqlDB', 'passwd', fallback=''),
        database=config.get('mysqlDB', 'db', fallback='ml_poit'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


def save_session_to_db_and_json():
    """Uloží celú sekvenciu z buffra do DB aj do JSON súboru naraz"""
    if not system_state['session_buffer']:
        print("[SAVE] Buffer je prázdny, nič neukladám.")
        return

    try:
        # 1. Príprava dát (JSON string)
        json_data = json.dumps(system_state['session_buffer'])

        # 2. Zápis do SQL Databázy
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO graph (hodnoty) VALUES (%s)", (json_data,))
        conn.commit()
        conn.close()
        print("[DB] Celá session úspešne uložená do databázy.")

        # 3. Zápis do JSON súboru (každá session na nový riadok)
        with open(JSON_FILE, "a") as f:
            f.write(json_data + "\n")
        print("[FILE] Celá session úspešne pridaná do súboru.")

        # 4. VYČISTENIE BUFFRA pre ďalšie meranie
        system_state['session_buffer'] = []

    except Exception as e:
        print(f"[SAVE ERROR] Chyba pri ukladaní: {e}")


system_state = {
    "connected": False,
    "temperature": None,
    "pump_pwm": 0,
    "tec_pwm": 0,
    "target_pump_pwm": 0,
    "target_tec_pwm": 0,
    "setpoint": 25.0,
    "mode": 1,
    "running": False,
    "session_buffer": []
}


#  ROUTES  –  frontend
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/archive')
def archive():
    return render_template('archive.html')


#  API  –  príjem dát z ESP32
# Endpoint pre Arduino (príjem dát cez WiFi)

@app.route('/api/update', methods=['POST'])
def update_data():
    if not system_state['connected']:
        return jsonify({
            "status": "standby",
            "connected": False,
            "running": False,
            "msg": "Waiting for web connection"
        })

    data = request.json
    if not data: return jsonify({"status": "error"}), 400

    # Aktualizuj lokálny stav
    system_state.update({
        "temperature": data.get('temperature'),
        "pump_pwm": data.get('pump_pwm', system_state['pump_pwm']),
        "tec_pwm": data.get('tec_pwm', system_state['tec_pwm']),
    })

    tb_data = {
        "temperature": system_state['temperature'],
        "pump_pwm": system_state['pump_pwm'],
        "tec_pwm": system_state['tec_pwm'],
        "setpoint": system_state['setpoint'],
        "running": system_state['running'],
        "mode": system_state['mode'],
        # NOVÉ:  pre Error widget na TB
        "error": round(system_state['setpoint'] - (system_state['temperature'] or 0), 2)
    }

    send_to_thingsboard(tb_data)

    # Broadcast cez WebSocket všetkým pripojeným klientom
    if system_state['running']:
        data_point = {
            "x": len(system_state['session_buffer']) + 1,
            "t": datetime.now(timezone.utc).isoformat(),
            "temp": system_state['temperature'],
            "p_pwm": system_state['pump_pwm'],
            "t_pwm": system_state['tec_pwm'],
            "setpoint": system_state['setpoint'],
            "mode": system_state['mode']
        }

        # Pridáme do buffra (dočasná pamäť v RAM)
        system_state['session_buffer'].append(data_point)

        socketio.emit('new_data', {
            **data,
            "setpoint": system_state['setpoint']
        }, namespace='/test')

    # Vráť ESP32 aktuálny setpoint a mód
    return jsonify({
        "status": "ok",
        "connected": system_state['connected'],
        "running": system_state['running'],
        "mode": system_state['mode'],
        "target_pump": system_state['target_pump_pwm'],
        "target_tec": system_state['target_tec_pwm'],
        "setpoint": system_state['setpoint']
    })


#  API  –  ovládanie z dashboardu / frontendu
@app.route('/api/setpoint', methods=['POST'])
def set_setpoint():
    """Nastav cieľovú teplotu"""
    data = request.json
    system_state['setpoint'] = float(data.get('setpoint', 25.0))
    print(f"[API] setpoint → {system_state['setpoint']} °C")
    return jsonify({"status": "ok", "setpoint": system_state['setpoint']})


@app.route('/api/mode', methods=['POST'])
def set_mode():
    """Prepni mód regulácie (1 / 2 / 3)"""
    data = request.json
    mode = int(data.get('mode', 1))
    if mode not in (1, 2, 3):
        return jsonify({"status": "error", "msg": "neplatný mód"}), 400
    system_state['mode'] = mode
    print(f"[API] mód → {mode}")
    return jsonify({"status": "ok", "mode": mode})


@app.route('/api/start', methods=['POST'])
def start_system():
    """Spusti reguláciu"""
    system_state['running'] = True
    system_state['session_buffer'] = []
    print("[API] systém SPUSTENÝ")
    return jsonify({"status": "ok", "running": True})


@app.route('/api/stop', methods=['POST'])
def stop_system():
    """Zastav reguláciu"""
    system_state['running'] = False

    save_session_to_db_and_json()

    print("[API] systém ZASTAVENÝ")
    return jsonify({"status": "ok", "running": False})


#  API – nastavenie PWM z dashboardu (manuálne vstupy)
@app.route('/api/pwm_pump', methods=['POST'])
def set_pwm_pump():
    """Nastaví konštantu pre pumpu (využívané hlavne v Móde 1)"""
    data = request.json
    val = int(data.get('pwm', 150))
    system_state['target_pump_pwm'] = max(0, min(255, val))
    print(f"[API] Target Pump PWM → {system_state['target_pump_pwm']}")
    return jsonify({"status": "ok", "target_pump": system_state['target_pump_pwm']})


@app.route('/api/pwm_tec', methods=['POST'])
def set_pwm_tec():
    """Nastaví konštantu pre Peltier (využívané hlavne v Móde 2)"""
    data = request.json
    val = int(data.get('pwm', 150))
    system_state['target_tec_pwm'] = max(0, min(255, val))
    print(f"[API] Target TEC PWM → {system_state['target_tec_pwm']}")
    return jsonify({"status": "ok", "target_tec": system_state['target_tec_pwm']})


@app.route('/api/status', methods=['GET'])
def get_status():
    """Vráť aktuálny stav systému"""
    return jsonify(system_state)


# NOVÝ ENDPOINT PRE TLAČIDLO CONNECT
@app.route('/api/connect', methods=['POST'])
def connect_trigger():
    data = request.json
    # Prepneme stav podľa toho, čo prišlo z frontendu
    system_state['connected'] = data.get('connect', False)
    if not system_state['connected']:
        system_state['running'] = False
        system_state['session_buffer'] = []

    status_text = "PRIPOJENÉ" if system_state['connected'] else "ODPOJENÉ"
    print(f"[GATEWAY] Systém je teraz: {status_text}")

    return jsonify({"status": "ok", "connected": system_state['connected']})


@app.route('/api/read_log/<int:row_id>')
def read_log(row_id):
    try:
        with open(JSON_FILE, "r") as f:
            lines = f.readlines()
            # Riadok 3 je index lines[2]
            return lines[row_id - 1]
    except:
        return "Záznam nenájdený", 404


@app.route('/api/read_db/<int:row_id>')
def read_db(row_id):
    """Načíta konkrétny záznam z databázy podľa ID"""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT hodnoty FROM graph WHERE id=%s", (row_id,))
            rv = cur.fetchone()
        conn.close()
        return rv['hodnoty'] if rv else ("Nenájdené", 404)
    except Exception as e:
        return str(e), 500


#  WEBSOCKET  –  udalosti
@socketio.on('connect', namespace='/test')
def test_connect():
    # global thread
    # with thread_lock:
    #     if thread is None:
    #         # Namiesto background_thread (ktorý čaká na Arduino)
    #         # teraz na test spustíme náš emitter:
    #         thread = socketio.start_background_task(target=test_data_emitter)
    print('[WS] klient pripojený')


@socketio.on('disconnect', namespace='/test')
def on_disconnect():
    print('[WS] klient odpojený')


if __name__ == '__main__':
    # socketio.run(app, host='0.0.0.0', port=5001, debug=True)
    socketio.run(app, host='0.0.0.0', port=5003, debug=False, allow_unsafe_werkzeug=True)
