import pymysql
from threading import Lock
import random # Nezabudni pridať import na vrch súboru

def test_data_emitter():
    """Simulátor dát pre grafy (Pumpa, TEC, Teplota)"""
    print("Simulátor dát spustený...")
    while True:
        # Generujeme realistické testovacie dáta
        test_data = {
            "temperature": round(random.uniform(20.0, 25.0), 2), # Fluktuácia okolo 22 stupňov
            "pump_pwm": random.randint(100, 255),               # Náhodný výkon pumpy
            "tec_pwm": random.randint(50, 150)                  # Náhodný výkon Peltieru
        }
        
        # Odošleme cez Socket.io (namespace a event musia sedieť s tvojím JS)
        socketio.emit('new_data', test_data, namespace='/test')
        
        socketio.sleep(2) # Počkáme 2 sekundy pred ďalšou dávkou

pymysql.install_as_MySQLdb()  # Windows fix

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import configparser
import json
import requests
from datetime import datetime, timezone


#  APLIKÁCIA
app = Flask(__name__)
app.config['SECRET_KEY'] = 'peltier_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

thread = None
thread_lock = Lock()

config = configparser.ConfigParser()
config.read('config.cfg')

#  THINGSBOARD KONFIGURÁCIA
#TB_HOST = "thingsboard.cloud"
TB_URL = "http://thingsboard.cloud/api/v1/{token}/telemetry"
TB_TOKEN = "780kjbsiuz5nrp4nohvg"  # ← zmeňit toto za Access Token zariadenia


def send_to_thingsboard(data: dict):
    """Pošle telemetriu na ThingsBoard cloud"""
    try:
        url = TB_URL.format(token=TB_TOKEN)
        # Pridaný explicitný Header pre JSON dáta
        headers = {'Content-Type': 'application/json'}
        resp = requests.post(url, json=data, headers=headers, timeout=3)
        print(f"[ThingsBoard] status: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"[ThingsBoard] chyba: {e}")


#  DATABÁZA  (ukladanie histórie)

def get_db():
    return pymysql.connect(
        host=config.get('mysqlDB', 'host', fallback='localhost'),
        user=config.get('mysqlDB', 'user', fallback='root'),
        password=config.get('mysqlDB', 'passwd', fallback=''),
        database=config.get('mysqlDB', 'db', fallback='ml_poit'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


def save_to_db(data: dict):
    """Uloží meranie do SQL databázy"""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO measurements
                    (temperature, pump_pwm, tec_pwm, setpoint, timestamp)
                VALUES
                    (%s, %s, %s, %s, %s)
            """, (
                data.get('temperature'),
                data.get('pump_pwm'),
                data.get('tec_pwm'),
                data.get('setpoint'),
                datetime.now(timezone.utc)
            ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] chyba: {e}")


#  JSON SÚBOR  (záloha dát)

JSON_FILE = "data_log.json"

def save_to_json(data: dict):
    """Pridá záznam do JSON súboru"""
    try:
        try:
            with open(JSON_FILE, 'r') as f:
                log = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        log.append({**data, "timestamp": datetime.now(timezone.utc).isoformat()})

        with open(JSON_FILE, 'w') as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"[JSON] chyba: {e}")


#  STAV SYSTÉMU  (aktuálne hodnoty + mód regulácie)

system_state = {
    "connected": False,
    "temperature": None,
    "pump_pwm": 0,
    "tec_pwm": 0,
    "target_pump_pwm": 0,
    "target_tec_pwm": 0,
    "setpoint": 25.0,
    "mode": 1,
    "running": False
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

    # ThingsBoard vyžaduje pre správne zobrazenie grafu teplôt aj kľúč 'setpoint'.
    # Ak ho ESP32 neposiela, musíme ho doplniť z lokálneho system_state.
    tb_data = {
        "temperature": system_state['temperature'],
        "pump_pwm": system_state['pump_pwm'],
        "tec_pwm": system_state['tec_pwm'],
        "setpoint": system_state['setpoint']
    }

    # Pošli kompletné telemetrické dáta na ThingsBoard
    # send_to_thingsboard(tb_data)

    # Broadcast cez WebSocket všetkým pripojeným klientom
    if system_state['running']:
        socketio.emit('new_data', data, namespace='/test')
        # Ulož do databázy
        # save_to_db({**data, "setpoint": system_state['setpoint']})
    
        # Ulož do JSON súboru
        # save_to_json(data)

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
    print("[API] systém SPUSTENÝ")
    return jsonify({"status": "ok", "running": True})


@app.route('/api/stop', methods=['POST'])
def stop_system():
    """Zastav reguláciu"""
    system_state['running'] = False
    print("[API] systém ZASTAVENÝ")
    return jsonify({"status": "ok", "running": False})


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
    
    status_text = "PRIPOJENÉ" if system_state['connected'] else "ODPOJENÉ"
    print(f"[GATEWAY] Systém je teraz: {status_text}")
    
    return jsonify({"status": "ok", "connected": system_state['connected']})



#  WEBSOCKET  –  udalosti
@socketio.on('connect', namespace='/test')
def test_connect():
    # global thread
    # with thread_lock:
    #     if thread is None:
    #         # Namiesto background_thread (ktorý čaká na Arduino) 
    #         # teraz na test spustíme náš emitter:
    #         thread = socketio.start_background_task(target=test_data_emitter)
    print('Web klient pripojený k simulátoru')


@socketio.on('disconnect', namespace='/test')
def on_disconnect():
    print('[WS] klient odpojený')


if __name__ == '__main__':
    #socketio.run(app, host='0.0.0.0', port=5001, debug=True)
    socketio.run(app, host='0.0.0.0', port=5001, debug=True, allow_unsafe_werkzeug=True)