import eventlet
eventlet.monkey_patch()


import pymysql
from threading import Lock
import random



def test_data_emitter():
    """Simulátor dát pre grafy (Pumpa, TEC, Teplota)"""
    log_to_terminal("Simulátor dát spustený...")
    while True:
        test_data = {
            "temperature": round(random.uniform(20.0, 25.0), 2),
            "pump_pwm": random.randint(100, 255),
            "tec_pwm": random.randint(50, 150),
            "setpoint": system_state.get('setpoint', 25.0)
        }
        socketio.emit('new_data', test_data, namespace='/test')
        socketio.sleep(2)

def log_to_terminal(message):
    """Vypíše správu do VSCode konzoly a pošle ju cez Socket.io na web."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    
    # 1. Výpis do konzoly VSCode
    print(full_msg)
    
    # 2. Odoslanie na web cez WebSocket (všetkým pripojeným klientom)
    # Používame socketio.emit bez ohľadu na to, či ide o API call alebo MQTT
    socketio.emit('terminal_log', {'msg': full_msg}, namespace='/test')


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
# TB_TOKEN = "ncgt93ixsrkl8ngwt1cs"
# TB_TOKEN = "X9ttptsR0dW5gvE3wYTT"
TB_TOKEN = "" # toto použiť ak nepracujeme s thingsboard



# ─── POMOCNÁ FUNKCIA pre shared attributes ───────────────────────────────────
def _apply_attributes(data: dict):
    """Spracuje shared attributes z ThingsBoard (update aj response)"""
    if "target_pump_pwm" in data:
        system_state['target_pump_pwm'] = int(data['target_pump_pwm'])
        log_to_terminal(f"[ATTR] target_pump_pwm → {system_state['target_pump_pwm']}")
        socketio.emit('status_update', {'target_pump': system_state['target_pump_pwm']}, namespace='/test')

    if "target_tec_pwm" in data:
        system_state['target_tec_pwm'] = int(data['target_tec_pwm'])
        log_to_terminal(f"[ATTR] target_tec_pwm → {system_state['target_tec_pwm']}")
        socketio.emit('status_update', {'target_tec': system_state['target_tec_pwm']}, namespace='/test')

    if "control_mode" in data:
        system_state['mode'] = int(data['control_mode'])
        log_to_terminal(f"[ATTR] mode → {system_state['mode']}")
        socketio.emit('status_update', {'mode': system_state['mode']}, namespace='/test')

    if "archiv_source" in data:
        system_state['archiv_source'] = int(data['archiv_source'])
        log_to_terminal(f"[ATTR] archiv_source → {system_state['archiv_source']}")
        socketio.emit('status_update', {'archiv_source': system_state['archiv_source']}, namespace='/test')

    if "archiv_index" in data:
        system_state['archiv_index'] = int(data['archiv_index'])
        log_to_terminal(f"[ATTR] archiv_index → {system_state['archiv_index']}")
        socketio.emit('status_update', {'archiv_index': system_state['archiv_index']}, namespace='/test')


# ─── MQTT CALLBACKS ───────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log_to_terminal("[MQTT] Úspešne pripojené k ThingsBoardu")
        client.subscribe("v1/devices/me/rpc/request/+")
        client.subscribe("v1/devices/me/attributes")
        # FIX: prihlás sa aj na response topic a vyžiadaj aktuálne hodnoty
        client.subscribe("v1/devices/me/attributes/response/+")
        client.publish(
            "v1/devices/me/attributes/request/1",
            json.dumps({"sharedKeys": "control_mode,target_pump_pwm,target_tec_pwm,archiv_source,archiv_index"})
        )
    else:
        log_to_terminal(f"[MQTT] Chyba pripojenia: {rc}")


def on_message(client, userdata, msg):
    global system_state
    try:
        data = json.loads(msg.payload)

        # FIX: shared attribute - priamy update z TB (napr. po kliknutí Mod 1/2/3)
        if msg.topic == "v1/devices/me/attributes":
            log_to_terminal(f"[ATTR] Shared attribute update: {data}")
            _apply_attributes(data)
            return

        # FIX: response na vyžiadané atribúty (po pripojení)
        if msg.topic.startswith("v1/devices/me/attributes/response/"):
            log_to_terminal(f"[ATTR] Attribute response: {data}")
            shared = data.get("shared", {})
            _apply_attributes(shared)
            return

        method = data.get("method")
        params = data.get("params")

        log_to_terminal(f"[RPC] Príkaz z TB -> Metóda: {method}, Hodnota: {params}")

        if method == "setPumpPwm":
            system_state['target_pump_pwm'] = int(params)
            socketio.emit('status_update', {'target_pump': system_state['target_pump_pwm']}, namespace='/test')

        elif method == "setTecPwm":
            system_state['target_tec_pwm'] = int(params)
            socketio.emit('status_update', {'target_tec': system_state['target_tec_pwm']}, namespace='/test')

        elif method == "setMode":
            # FIX: int() funguje aj pre string "1" aj pre int 1
            system_state['mode'] = int(params)
            log_to_terminal(f"[RPC] mode → {system_state['mode']}")
            socketio.emit('status_update', {'mode': system_state['mode']}, namespace='/test')

        elif method == "setRunning":
            system_state['running'] = bool(params)
            if not system_state['running']:
                save_session_to_db_and_json()
            socketio.emit('status_update', {'running': system_state['running']}, namespace='/test')

        elif method == "setConnected":
            system_state['connected'] = bool(params)
            if not system_state['connected']:
                system_state['running'] = False
                system_state['session_buffer'] = []
            status_text = "PRIPOJENÉ" if system_state['connected'] else "ODPOJENÉ"
            log_to_terminal(f"[RPC] Systém je teraz: {status_text}")
            socketio.emit('status_update', {'connected': system_state['connected']}, namespace='/test')

        # RPC odpoveď späť do TB
        request_id = msg.topic.split('/')[-1]
        mqtt_client.publish(
            f"v1/devices/me/rpc/response/{request_id}",
            json.dumps({"status": "ok"})
        )

    except Exception as e:
        log_to_terminal(f"[RPC Error] Chyba pri spracovaní správy: {e}")


# ─── MQTT KLIENT ──────────────────────────────────────────────────────────────
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.username_pw_set(TB_TOKEN)
mqtt_client.connect(TB_HOST, TB_PORT, 60)
mqtt_client.loop_start()


def send_to_thingsboard(data: dict):
    """Publikovanie telemetrie"""
    try:
        mqtt_client.publish("v1/devices/me/telemetry", json.dumps(data))

        # FIX: použi system_state['temperature'] nie data.get('temperature')
        running_text = "RUN" if system_state['running'] else "STOP"
        terminal = (
            f"T={system_state['temperature'] or 0:.1f}°C | "
            f"Err={data.get('error', 0):.2f} | "
            f"{running_text} | "
            f"Mode={system_state['mode']}"
        )
        mqtt_client.publish(
            "v1/devices/me/attributes",
            json.dumps({"terminal": terminal})
        )
    except Exception as e:
        log_to_terminal(f"[MQTT] Chyba odosielania: {e}")


#  JSON SÚBOR (záloha dát)
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
        log_to_terminal("[SAVE] Buffer je prázdny, nič neukladám.")
        return

    try:
        json_data = json.dumps(system_state['session_buffer'])

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO graph (hodnoty) VALUES (%s)", (json_data,))
        conn.commit()
        conn.close()
        log_to_terminal("[DB] Celá session úspešne uložená do databázy.")

        with open(JSON_FILE, "a") as f:
            f.write(json_data + "\n")
        log_to_terminal("[FILE] Celá session úspešne pridaná do súboru.")

        system_state['session_buffer'] = []

    except Exception as e:
        log_to_terminal(f"[SAVE ERROR] Chyba pri ukladaní: {e}")


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
    "error": 0,
    "isErrorActive": False,
    "session_buffer": [],
    "archiv_source": 0,   # 0=databáza, 1=súbor
    "archiv_index": 0     # index záznamu
}

esp_connect_check_count = 0


#  ROUTES – frontend
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/archive')
def archive():
    return render_template('archive.html')


#  API – príjem dát z ESP32
@app.route('/api/update', methods=['POST'])
def update_data():
    global esp_connect_check_count

    if not system_state['connected']:
        if esp_connect_check_count < 3:
            log_to_terminal(f"[API] Prijaté údaje z ESP32, ale systém nie je pripojený ({esp_connect_check_count + 1}/3).")
            esp_connect_check_count += 1
        return jsonify({
            "status": "standby",
            "connected": False,
            "running": False,
            "msg": "Waiting for web connection"
        })

    data = request.json
    if not data: return jsonify({"status": "error"}), 400

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
        "error": system_state['error'],
        "isErrorActive": system_state['isErrorActive']
    }

    send_to_thingsboard(tb_data)

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
        system_state['session_buffer'].append(data_point)
        socketio.emit('new_data', {
            **data,
            "setpoint": system_state['setpoint']
        }, namespace='/test')

    return jsonify({
        "status": "ok",
        "connected": system_state['connected'],
        "running": system_state['running'],
        "mode": system_state['mode'],
        "target_pump": system_state['target_pump_pwm'],
        "target_tec": system_state['target_tec_pwm'],
        "setpoint": system_state['setpoint'],
        "error": system_state['error'],
        "isErrorActive": system_state['isErrorActive']
    })


#  API – ovládanie z dashboardu / frontendu
@app.route('/api/setpoint', methods=['POST'])
def set_setpoint():
    data = request.json
    system_state['setpoint'] = float(data.get('setpoint', 25.0))
    log_to_terminal(f"[API] setpoint → {system_state['setpoint']} °C")
    return jsonify({"status": "ok", "setpoint": system_state['setpoint']})


@app.route('/api/mode', methods=['POST'])
def set_mode():
    data = request.json
    mode = int(data.get('mode', 1))
    if mode not in (1, 2, 3, 4):
        return jsonify({"status": "error", "msg": "neplatný mód"}), 400
    system_state['mode'] = mode
    log_to_terminal(f"[API] mód → {mode}")
    return jsonify({"status": "ok", "mode": mode})


@app.route('/api/start', methods=['POST'])
def start_system():
    system_state['running'] = True
    system_state['session_buffer'] = []
    log_to_terminal("[API] systém SPUSTENÝ")
    return jsonify({"status": "ok", "running": True})


@app.route('/api/stop', methods=['POST'])
def stop_system():
    system_state['running'] = False
    save_session_to_db_and_json()
    log_to_terminal("[API] systém ZASTAVENÝ")
    return jsonify({"status": "ok", "running": False})


@app.route('/api/pwm_pump', methods=['POST'])
def set_pwm_pump():
    data = request.json
    val = int(data.get('pwm', 150))
    system_state['target_pump_pwm'] = max(0, min(255, val))
    log_to_terminal(f"[API] Target Pump PWM → {system_state['target_pump_pwm']}")
    return jsonify({"status": "ok", "target_pump": system_state['target_pump_pwm']})


@app.route('/api/pwm_tec', methods=['POST'])
def set_pwm_tec():
    data = request.json
    val = int(data.get('pwm', 150))
    system_state['target_tec_pwm'] = max(0, min(255, val))
    log_to_terminal(f"[API] Target TEC PWM → {system_state['target_tec_pwm']}")
    return jsonify({"status": "ok", "target_tec": system_state['target_tec_pwm']})

@app.route('/api/error', methods=['POST'])
def set_error():
    data = request.json or {}
    error_value = data.get('error')

    if error_value is None:
        return jsonify({"status": "error", "msg": "Missing or invalid error value."}), 400

    try:
        error_value = float(error_value)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "msg": "Error value must be a number."}), 400

    system_state['error'] = error_value
    system_state['isErrorActive'] = bool(data.get('isErrorActive', False))
    log_to_terminal(f"[API] Error → {system_state['error']} PWM, status of error: {'ACTIVE' if system_state['isErrorActive'] else 'INACTIVE'}")
    return jsonify({"status": "ok", "error": system_state['error'], "isErrorActive": system_state['isErrorActive']})


@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(system_state)


@app.route('/api/connect', methods=['POST'])
def connect_trigger():
    data = request.json
    system_state['connected'] = data.get('connect', False)
    if not system_state['connected']:
        system_state['running'] = False
        system_state['session_buffer'] = []
    status_text = "PRIPOJENÉ" if system_state['connected'] else "ODPOJENÉ"
    log_to_terminal(f"[GATEWAY] Systém je teraz: {status_text}")
    return jsonify({"status": "ok", "connected": system_state['connected']})


@app.route('/api/read_log/<int:row_id>')
def read_log(row_id):
    try:
        with open(JSON_FILE, "r") as f:
            lines = f.readlines()
            return lines[row_id - 1]
    except:
        return "Záznam nenájdený", 404


@app.route('/api/read_db/<int:row_id>')
def read_db(row_id):
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT hodnoty FROM graph WHERE id=%s", (row_id,))
            rv = cur.fetchone()
        conn.close()
        return rv['hodnoty'] if rv else ("Nenájdené", 404)
    except Exception as e:
        return str(e), 500

@app.route('/api/archive', methods=['GET'])
def get_archive_data():
    """Vráti záznam podľa aktuálneho archiv_source a archiv_index"""
    source = system_state['archiv_source']
    index = system_state['archiv_index']
    if source == 0:
        return read_db(index)
    else:
        return read_log(index)

#  WEBSOCKET – udalosti
@socketio.on('connect', namespace='/test')
def test_connect():
    log_to_terminal('[WS] klient pripojený')


@socketio.on('disconnect', namespace='/test')
def on_disconnect():
    log_to_terminal('[WS] klient odpojený')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5003, debug=False)
