import pymysql
pymysql.install_as_MySQLdb() # Windows fix

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import configparser
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'peltier_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

config = configparser.ConfigParser()
config.read('config.cfg')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/graph')
def graph():
    return render_template('graph.html')

# Endpoint pre Arduino (príjem dát cez WiFi)
@app.route('/api/update', methods=['POST'])
def update_data():
    data = request.json
    # Tu spracuješ dáta z Arduina
    print(f"Dáta z Arduina: {data}")
    return jsonify({"status": "ok", "setpoint": 25.0})

@socketio.on('connect', namespace='/test')
def on_connect():
    print('Web klient pripojený')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)