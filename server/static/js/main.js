// --- 1. KONFIGURÁCIA A DÁTOVÉ POĽA ---
const MAX_DATA_POINTS = 50; 
const graphData = {
    timestamps: [],
    temperature: [],
    pump_pwm: [],
    tec_pwm: [],
    target_temperature: []
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
    line: { color: '#f7d4ab', width: 2 }
}], { ...smallGraphLayout, title: 'Pumpa (PWM)' });

// Graf 2: PET / Peltier (Top Right vo Figme)
Plotly.newPlot('tec-graph', [{
    x: graphData.timestamps,
    y: graphData.tec_pwm,
    name: 'Peltier',
    mode: 'lines',
    line: { color: '#feadab', width: 2 }
}], { ...smallGraphLayout, title: 'PET (PWM)' });

// Graf 3: Teplota (Veľký spodný graf)
Plotly.newPlot('temp-graph', [
    {
        x: graphData.timestamps,
        y: graphData.temperature,
        name: 'Nameraná teplota',
        mode: 'lines',
        fill: 'tozeroy', // Vyplnený graf pod čiarou pre lepší vzhľad
        line: { color: '#6fa5cc', width: 3 }
    },
    {
        x: graphData.timestamps,
        y: graphData.target_temperature,
        name: 'Žiadaná teplota',
        mode: 'lines',
        line: { color: '#ef4444', width: 2, dash: 'dash' }
    }
], { 
    title: 'Teplota [°C]',
    xaxis: { type: 'date' },
    yaxis: { range: [10, 30] },
    margin: { t: 50, b: 50, l: 50, r: 50 }
});


// --- 3. WEBSOCKET PRIPOJENIE A UPDATE ---

const socket = io("http://localhost:5003/test");
const $terminal = $('#terminal');

function log_to_terminal(message) {
    if (!message) return;
    const line = message.endsWith('\n') ? message : message + '\n';
    $terminal.append(line);
    $terminal.scrollTop($terminal[0].scrollHeight);
}

socket.on('terminal_log', (data) => {
    log_to_terminal(data.msg);
});

socket.on('new_data', (data) => {
    const currentTime = new Date();

    // Vytiahnutie hodnôt
    const temp = data.temperature ?? 0;
    const pump = data.pump_pwm ?? 0;
    const tec = data.tec_pwm ?? 0;
    const setpoint = data.setpoint ?? 0;

    // Pridanie dát do polí
    graphData.timestamps.push(currentTime);
    graphData.temperature.push(temp);
    graphData.pump_pwm.push(pump);
    graphData.tec_pwm.push(tec);
    graphData.target_temperature.push(setpoint);

    // Posun grafu (limit bodov)
    if (graphData.timestamps.length > MAX_DATA_POINTS) {
        graphData.timestamps.shift();
        graphData.temperature.shift();
        graphData.pump_pwm.shift();
        graphData.tec_pwm.shift();
        graphData.target_temperature.shift();
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
        x: [graphData.timestamps, graphData.timestamps],
        y: [graphData.temperature, graphData.target_temperature]
    }, {}, [0, 1]);
});

socket.on('connect', () => console.log('WebSocket pripojený - 3 grafy aktívne.'));

$(document).ready(function() {

    // Tlačidlo CONNECT (Logická brána pre ESP32)
    $('#connect-btn').click(function() {
        let isConnected = $(this).hasClass('btn-green'); 
        let newState = !isConnected;

        $.ajax({
            url: '/api/connect',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ connect: newState }),
            success: function(resp) {
                const time = new Date().toLocaleTimeString();
                if (resp.connected) {
                    $('#connect-btn').text('Connected').removeClass('btn-yellow').addClass('btn-green');
                } else {
                    $('#connect-btn').text('Connect').removeClass('btn-green').addClass('btn-yellow');
                }
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
            },
            error: function(xhr) {
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.msg : "Chyba";
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
            }
        });
    });

    // --- OVLÁDANIE MÓDU (Mení sa pri výbere z roletky) ---
    $('#mode-select').change(function() {
        let selectedMode = parseInt($(this).val()); // Prevedieme na číslo (1, 2 alebo 3)
        let modeName = $(this).find("option:selected").text(); // Získa presný text

        // LOGIKA ZOBRAZOVANIA POLÍČOK:
        if (selectedMode === 1) {
            $('#wrapper-pumpa').show();     // Zobrazí pumpu
            $('#wrapper-peltier').hide();   // Schová peltier
        } else if (selectedMode === 2) {
            $('#wrapper-pumpa').hide();     // Schová pumpu
            $('#wrapper-peltier').show();   // Zobrazí peltier
        } else if (selectedMode === 3) {
            // Mód 3 (Kaskádová regulácia) - schová obe
            $('#wrapper-pumpa').hide();
            $('#wrapper-peltier').hide();
        } else {
            $('#wrapper-pumpa').show();
            $('#wrapper-peltier').show();
        }

        // ODESLANIE NA SERVER:
        $.ajax({
            url: '/api/mode',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ mode: selectedMode }),
            success: function(resp) {
                const time = new Date().toLocaleTimeString();
            },
            error: function(xhr) {
                const time = new Date().toLocaleTimeString();
            }
        });
    }).trigger('change'); // <-- Tento '.trigger('change')' hneď pri načítaní stránky zosynchronizuje vizuál s vybratou hodnotou

    $('#chyba-cislo').change(function() {

        let errorVal = parseInt($(this).val());
        let isErrorActive =  $('#chyba-checkbox').is(':checked');
        const time = new Date().toLocaleTimeString();

        if (isNaN(errorVal)) {
            return;
        }

        $.ajax({
            url: '/api/error',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ error: errorVal, isErrorActive: isErrorActive }),
            success: function(response) {
                const time = new Date().toLocaleTimeString();
            },
            error: function(xhr) {
                const time = new Date().toLocaleTimeString();
            }
        });

    }).trigger('change');

    $('#chyba-checkbox').change(function() {
        let errorVal = parseInt($('#chyba-cislo').val());
        let isErrorActive =  $(this).is(':checked');
        const time = new Date().toLocaleTimeString();

        if (isNaN(errorVal)) {
            return;
        }

        $.ajax({
            url: '/api/error',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ error: errorVal, isErrorActive: isErrorActive }),
            success: function(response) {
                const time = new Date().toLocaleTimeString();
            },
            error: function(xhr) {
                const time = new Date().toLocaleTimeString();
            }
        });
    }).trigger('change');

    const inputPumpa = document.getElementById('ovladanie-pumpa');
    const inputPeltier = document.getElementById('ovladanie-peltier');
    const inputTeplota = document.getElementById('ovladanie-teplota');

    // Pomocná funkcia na odoslanie POST požiadavky
    async function posliPwmKonstantu(url, hodnota, label) {
        // Prevody na číslo a základná validácia prázdnej hodnoty
        const ciselnaHodnota = parseInt(hodnota, 10);
        const time = new Date().toLocaleTimeString();

        if (isNaN(ciselnaHodnota)) {
            console.warn(`Zadaná hodnota pre ${url} nie je platné číslo.`);
            return;
        }

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ pwm: ciselnaHodnota })
            });

            if (!response.ok) {
                throw new Error(`Chyba pri komunikácii so serverom: ${response.status}`);
            }

            const data = await response.json();
            console.log(`Úspešne aktualizované cez API (${url}):`, data);
        } catch (error) {
            console.error(`Nastala chyba pri odosielaní na ${url}:`, error);
        }
    }

    async function posliSetpoint(url, hodnota, label) {
        const ciselnaHodnota = parseFloat(hodnota);
        const time = new Date().toLocaleTimeString();

        if (isNaN(ciselnaHodnota)) {
            return;
        }

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ setpoint: ciselnaHodnota }) // Očakáva "setpoint"
            });

            if (!response.ok) throw new Error(`Chyba pri komunikácii so serverom: ${response.status}`);

            const data = await response.json();
        } catch (error) {
        }
    }
    
        // Naviazanie udalosti 'blur' pre pumpu
    if (inputPumpa) {
        inputPumpa.addEventListener('blur', (event) => {
            const hodnota = event.target.value;
            posliPwmKonstantu('/api/pwm_pump', hodnota, 'Pumpa');
        });
        
        // Voliteľné: Odoslanie po stlačení klávesu Enter
        inputPumpa.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') {
                inputPumpa.blur(); // Vyvolá udalosť blur a stratí fokus
            }
        });
    }

    // Naviazanie udalosti 'blur' pre Peltierov článok
    if (inputPeltier) {
        inputPeltier.addEventListener('blur', (event) => {
            const hodnota = event.target.value;
            posliPwmKonstantu('/api/pwm_tec', hodnota, 'Peltier');
        });
    
        // Voliteľné: Odoslanie po stlačení klávesu Enter
        inputPeltier.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') {
                inputPeltier.blur(); // Vyvolá udalosť blur a stratí fokus
            }
        });
    }

    // Naviazanie udalostí pre SETPOINT TEPLOTY
    if (inputTeplota) {
        inputTeplota.addEventListener('blur', (event) => {
            const hodnota = event.target.value;
            posliSetpoint('/api/setpoint', hodnota, 'Setpoint teploty');
        });
        inputTeplota.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') inputTeplota.blur();
        });
    }    
    
});


// --- REUSABLE FUNKCIA PRE BOOTSTRAP MODAL ---
function showModal(title, message, isError = true) {
    // Nastavenie textov
    $('#bootstrapModalLabel').text(title);
    $('#bootstrapModalBody').html(message); // .html() umožní v správe použiť aj napr. <br> alebo <strong>

    const $header = $('#modalHeader');
    const $btn = $('#modalBtn');

    if (isError) {
        // Červený vzhľad pre chyby
        $header.removeClass('bg-info bg-success text-white').addClass('bg-danger text-white');
        $btn.removeClass('btn-info btn-success').addClass('btn-danger');
    } else {
        // Modrý vzhľad pre informácie/úspech
        $header.removeClass('bg-danger text-white').addClass('bg-info text-white');
        $btn.removeClass('btn-danger').addClass('btn-info');
    }

    // Zobrazenie modálneho okna pomocou Bootstrapu
    // Ak Bootstrap 5 deteguje jQuery, funguje tento jednoduchý zápis:
    $('#bootstrapModal').modal('show');
    
    // Ak by náhodou jQuery zápis nefungoval (v závislosti od verzie BS5), 
    // použi tento čistý JS zápis:
    // let modalElement = document.getElementById('bootstrapModal');
    // let modalInstance = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
    // modalInstance.show();
}