$('#show-btn').click(function() {
    // 1. Načítame hodnoty z formulára
    let source = $('#mode-select').val(); // Bude "databaza" alebo "subor"
    let rowId = parseInt($('#index-zaznamu').val());

    // 2. Skontrolujeme, či používateľ zadal platné číslo
    if (!rowId || rowId <= 0) {
        showModal("Neplatný vstup", "Prosím, zadajte platný index záznamu (číslo väčšie ako 0).", true);
        return;
    }

    // 3. Rozhodneme, ktoré API zavoláme podľa vybraného zdroja
    let apiUrl = source === "databaza" ? `/api/read_db/${rowId}` : `/api/read_log/${rowId}`;

    // 4. Samotné volanie na Python backend
    $.ajax({
        url: apiUrl,
        type: 'GET',
        success: function(response) {
            console.log(`[ÚSPECH] Dáta zo zdroja: ${source}, Index: ${rowId}`);
            
            // --- ZAČIATOK SPRACOVANIA A KRESLENIA GRAFOV ---
            
            let dataArray;
            try {
                // Keďže čítame zo súboru, dáta prídu ako jeden dlhý text (String).
                // Musíme ich premeniť na skutočný JavaScriptový zoznam (Array) pomocou JSON.parse
                dataArray = typeof response === 'string' ? JSON.parse(response) : response;
            } catch (e) {
                console.error("Chyba pri parsovaní JSON:", e);
                showModal("Chyba pri spracovaní dát", "Skontrolujte formát v zdroji.", true);
                return;
            }

            if (!Array.isArray(dataArray) || dataArray.length === 0) {
                showModal("Chyba pri načítaní", "Záznam je prázdny alebo má nesprávny formát.", true);
                return;
            }

            // Pripravíme si prázdne polia pre osi X a Y
            let timestamps = [];
            let temps = [];
            let pumpPwms = [];
            let tecPwms = [];

            // Prejdeme každý bod z histórie a rozdelíme ho (názvy musia sedieť s tvojou konzolou)
            dataArray.forEach(point => {
                timestamps.push(point.t);
                temps.push(point.temp);
                pumpPwms.push(point.p_pwm);
                tecPwms.push(point.t_pwm);
            });

            $('#graphs-wrapper').fadeIn(300); 

            // Nastavenie pre malé grafy (aby vyzerali rovnako)
            const smallGraphLayout = {
                autosize: true, // Povolí automatické prispôsobenie
                margin: { t: 10, b: 40, l: 40, r: 20 }, // Zmenšený horný okraj (t: 10)
                xaxis: { type: 'date', showgrid: false },
                yaxis: { range: [0, 260], fixedrange: true }
            };

            // Vykreslíme GRAF 1: Pumpa
            Plotly.newPlot('pump-graph', [{
                x: timestamps,
                y: pumpPwms,
                name: 'Pumpa',
                mode: 'lines',
                line: { color: '#f7d4ab', width: 2 }
            }], smallGraphLayout, { responsive: true }); // <-- Pridané { responsive: true }

            // Vykreslíme GRAF 2: Peltier
            Plotly.newPlot('tec-graph', [{
                x: timestamps,
                y: tecPwms,
                name: 'Peltier',
                mode: 'lines',
                line: { color: '#feadab', width: 2 }
            }], smallGraphLayout, { responsive: true }); // <-- Pridané { responsive: true }

            // Vykreslíme GRAF 3: Teplota
            Plotly.newPlot('temp-graph', [{
                x: timestamps,
                y: temps,
                name: 'Teplota',
                mode: 'lines',
                fill: 'tozeroy', 
                line: { color: '#6fa5cc', width: 3 }
            }], { 
                autosize: true, // Povolí automatické prispôsobenie
                xaxis: { type: 'date' },
                yaxis: { range: [10, 30] },
                margin: { t: 10, b: 40, l: 40, r: 20 }
            }, { responsive: true }); // <-- Pridané { responsive: true }

            // --- KONIEC KRESLENIA GRAFOV ---
        },
        error: function(xhr) {
            console.error("[CHYBA] Nepodarilo sa načítať dáta:", xhr.responseText);
            showModal("Neplatný index", `Záznam s indexom ${rowId} v zdroji "${source}" nebol nájdený.`, true);
        }
    });
});

document.addEventListener('DOMContentLoaded', () => {
    const inputPumpa = document.getElementById('ovladanie-pumpa');
    const inputPeltier = document.getElementById('ovladanie-peltier');

    // Pomocná funkcia na odoslanie POST požiadavky
    async function posliPwmKonstantu(url, hodnota) {
        // Prevody na číslo a základná validácia prázdnej hodnoty
        const ciselnaHodnota = parseInt(hodnota, 10);
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

    // Naviazanie udalosti 'blur' pre pumpu
    if (inputPumpa) {
        inputPumpa.addEventListener('blur', (event) => {
            const hodnota = event.target.value;
            posliPwmKonstantu('/api/pwm_pump', hodnota);
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
            posliPwmKonstantu('/api/pwm_tec', hodnota);
        });

        // Voliteľné: Odoslanie po stlačení klávesu Enter
        inputPeltier.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') {
                inputPeltier.blur(); // Vyvolá udalosť blur a stratí fokus
            }
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

// MANUÁLNA POISTKA PRE ZATVORENIE MODALU (Pre Bootstrap 4 aj 5)
$(document).on('click', '[data-dismiss="modal"], [data-bs-dismiss="modal"], .btn-close, .close, #modalBtn', function() {
    try {
        let modalElement = document.getElementById('bootstrapModal');
        let modalInstance = bootstrap.Modal.getInstance(modalElement);
        if (modalInstance) {
            modalInstance.hide();
        } else {
            $('#bootstrapModal').modal('hide');
        }
    } catch (e) {
        try {
            $('#bootstrapModal').modal('hide');
        } catch (err) {
            // Posledná záchrana: ak Bootstrap JS úplne zlyhá, skryjeme to natívne
            $('#bootstrapModal').hide();
            $('.modal-backdrop').remove(); // Odstráni tmavé pozadie
            $('body').removeClass('modal-open').css('overflow', ''); // Obnoví scrollovanie na stránke
        }
    }
});