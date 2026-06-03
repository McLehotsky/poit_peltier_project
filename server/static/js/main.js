// --- 1. KONFIGURÁCIA A DÁTOVÉ POĽA ---
const MAX_DATA_POINTS = 50; 
const graphData = {
    timestamps: [],
    temperature: [],
    pump_pwm: [],
    tec_pwm: []
};

// Spoločné nastavenia pre malé grafy (Pumpa a PET)
const smallGraphLayout = {
    margin: { t: 30, b: 40, l: 40, r: 20 },
    xaxis: { type: 'date', showgrid: false },
    yaxis: { range: [0, 260], fixedrange: true }
};

// --- 2. INICIALIZÁCIA TROCH GRAFOV ---

// Graf 1: Pumpa (Top Left vo Figme)
Plotly.newPlot('pump-graph', [{
    x: graphData.timestamps,
    y: graphData.pump_pwm,
    name: 'Pumpa',
    mode: 'lines',
    line: { color: '#ff7f0e', width: 2 }
}], { ...smallGraphLayout, title: 'Pumpa (PWM)' });

// Graf 2: PET / Peltier (Top Right vo Figme)
Plotly.newPlot('tec-graph', [{
    x: graphData.timestamps,
    y: graphData.tec_pwm,
    name: 'Peltier',
    mode: 'lines',
    line: { color: '#9467bd', width: 2 }
}], { ...smallGraphLayout, title: 'PET (PWM)' });

// Graf 3: Teplota (Veľký spodný graf)
Plotly.newPlot('temp-graph', [{
    x: graphData.timestamps,
    y: graphData.temperature,
    name: 'Teplota',
    mode: 'lines',
    fill: 'tozeroy', // Vyplnený graf pod čiarou pre lepší vzhľad
    line: { color: '#1f77b4', width: 3 }
}], { 
    title: 'Teplota [°C]',
    xaxis: { type: 'date' },
    yaxis: { range: [10, 30] },
    margin: { t: 50, b: 50, l: 50, r: 50 }
});


// --- 3. WEBSOCKET PRIPOJENIE A UPDATE ---

const socket = io("http://localhost:5001/test");

socket.on('new_data', (data) => {
    const currentTime = new Date();

    // Vytiahnutie hodnôt
    const temp = data.temperature ?? 0;
    const pump = data.pump_pwm ?? 0;
    const tec = data.tec_pwm ?? 0;

    // Pridanie dát do polí
    graphData.timestamps.push(currentTime);
    graphData.temperature.push(temp);
    graphData.pump_pwm.push(pump);
    graphData.tec_pwm.push(tec);

    // Posun grafu (limit bodov)
    if (graphData.timestamps.length > MAX_DATA_POINTS) {
        graphData.timestamps.shift();
        graphData.temperature.shift();
        graphData.pump_pwm.shift();
        graphData.tec_pwm.shift();
    }

    // Aktualizácia Pumpy
    Plotly.update('pump-graph', {
        x: [graphData.timestamps],
        y: [graphData.pump_pwm]
    }, {}, [0]);

    // Aktualizácia PET
    Plotly.update('tec-graph', {
        x: [graphData.timestamps],
        y: [graphData.tec_pwm]
    }, {}, [0]);

    // Aktualizácia Teploty
    Plotly.update('temp-graph', {
        x: [graphData.timestamps],
        y: [graphData.temperature]
    }, {}, [0]);
});

socket.on('connect', () => console.log('WebSocket pripojený - 3 grafy aktívne.'));

$(document).ready(function() {

    // Tlačidlo CONNECT (Logická brána pre ESP32)
    $('#connect-btn').click(function() {
        let isConnected = $(this).hasClass('btn-success'); 
        let newState = !isConnected;

        $.ajax({
            url: '/api/connect',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ connect: newState }),
            success: function(resp) {
                const time = new Date().toLocaleTimeString();
                if (resp.connected) {
                    $('#connect-btn').text('Connected').removeClass('btn-warning').addClass('btn-success');
                    $('#terminal').append(`[${time}] System: CONNECTED (Brána otvorená)\n`);
                } else {
                    $('#connect-btn').text('Connect').removeClass('btn-success').addClass('btn-warning');
                    $('#terminal').append(`[${time}] System: DISCONNECTED (Brána zatvorená)\n`);
                }
                $('#terminal').scrollTop($('#terminal')[0].scrollHeight);
            }
        });
    });

    // Tlačidlo START
    $('#start-btn').click(function() {
        $.ajax({
            url: '/api/start',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({}),
            success: function(response) {
                const time = new Date().toLocaleTimeString();
                $('#terminal').append(`[${time}] System: START - Regulácia a grafy spustené.\n`);
                $('#terminal').scrollTop($('#terminal')[0].scrollHeight);
            },
            error: function(xhr) {
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.msg : "Chyba";
                $('#terminal').append(`[${new Date().toLocaleTimeString()}] Error: ${errorMsg}\n`);
            }
        });
    });

    // Tlačidlo STOP
    $('#stop-btn').click(function() {
        $.ajax({
            url: '/api/stop',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({}),
            success: function(response) {
                const time = new Date().toLocaleTimeString();
                $('#terminal').append(`[${time}] System: STOP - Regulácia pozastavená.\n`);
                $('#terminal').scrollTop($('#terminal')[0].scrollHeight);
            }
        });
    });

});