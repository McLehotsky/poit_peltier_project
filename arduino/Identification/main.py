import serial
import threading
import time
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# === NASTAVENIE PORTU (Zmeň podľa svojho PC) ===
SERIAL_PORT = 'COM16' 
BAUD_RATE = 115200
SUBOR_NA_ZAPIS = "meranie_dat.txt"

# História dát pre graf (zobrazí posledných 100 meraní)
max_pociatocnych_bodov = 100
casy_data = collections.deque(maxlen=max_pociatocnych_bodov)
teploty_data = collections.deque(maxlen=max_pociatocnych_bodov)

# Globálna premenná pre sériový port
ser = None

def citaj_z_esp32():
    """Vlákno na pozadí: Číta dáta, ukladá do súboru a plní dáta pre graf"""
    global ser
    print("[INFO] Spustené čítanie dát z ESP32...")
    
    with open(SUBOR_NA_ZAPIS, "a", encoding="utf-8") as subor:
        idx = 0
        while True:
            try:
                if ser and ser.in_waiting > 0:
                    riadok = ser.readline().decode('utf-8', errors='ignore').strip()
                    if riadok:
                        aktualny_cas = time.strftime("%Y-%m-%d %H:%M:%S")
                        formatovany_riadok = f"[{aktualny_cas}] {riadok}"
                        
                        # Zápis do súboru
                        subor.write(formatovany_riadok + "\n")
                        subor.flush()
                        
                        # Extrakcia teploty pre graf (hľadáme Teplota_x10:)
                        # Tvoj kód posiela: "Teplota_x10:250.0 Peltier:0..."
                        if "Teplota_x10:" in riadok:
                            try:
                                casti = riadok.split()
                                teplota_raw = casti[0].split(":")[1]
                                # Prepočítame späť na reálnu teplotu (delené 10)
                                realna_teplota = float(teplota_raw) / 10.0
                                
                                # Pridáme do polí pre graf
                                casy_data.append(idx)
                                teploty_data.append(realna_teplota)
                                idx += 1
                            except Exception:
                                pass
            except Exception:
                break

def odosielaj_prikazy():
    """Vlákno na pozadí: Čaká na tvoj vstup v konzole a posiela ho do ESP32"""
    global ser
    while True:
        try:
            prikaz = input("\nZadaj prikaz (napr. W150): ").strip()
            if prikaz and ser:
                ser.write((prikaz + '\n').encode('utf-8'))
                print(f"[ODOSLANÉ] -> {prikaz}")
        except Exception:
            break

def aktualizuj_graf(i, ciara, ax):
    """Funkcia, ktorú matplotlib volá na prekreslenie grafu každých 200ms"""
    if len(teploty_data) > 0:
        ciara.set_data(list(casy_data), list(teploty_data))
        ax.set_xlim(initial_xlim(list(casy_data)))
        ax.set_ylim(min(teploty_data) - 2, max(teploty_data) + 2)
    return ciara,

def initial_xlim(casy):
    if len(casy) < max_pociatocnych_bodov:
        return 0, max_pociatocnych_bodov
    return casy[0], casy[-1]

def main():
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)
        print(f"[INFO] Pripojené na {SERIAL_PORT}")
        
        # Spustenie čítania dát na pozadí
        t_citanie = threading.Thread(target=citaj_z_esp32, daemon=True)
        t_citanie.start()
        
        # Spustenie odosielania príkazov na pozadí
        t_prikazy = threading.Thread(target=odosielaj_prikazy, daemon=True)
        t_prikazy.start()
        
        # Nastavenie okna pre graf
        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title('Živý graf teploty z ESP32')
        ciara, = ax.plot([], [], 'r-', lw=2, label='Teplota (°C)')
        
        ax.set_title("Meranie teploty v reálnom čase")
        ax.set_xlabel("Počet meraní")
        ax.set_ylabel("Teplota [°C]")
        ax.grid(True)
        ax.legend()
        
        # Spustenie animácie grafu (obnova každých 200 ms)
        ani = animation.FuncAnimation(fig, aktualizuj_graf, fargs=(ciara, ax), interval=200, blit=False)
        
        plt.show() # Toto otvorí grafické okno (zablokuje hlavný kód, kým ho nezavrieš)
        
    except serial.SerialException:
        print(f"[CHYBA] Port {SERIAL_PORT} je obsadený alebo neexistuje!")
    except KeyboardInterrupt:
        print("\nUkončené.")

if __name__ == "__main__":
    main()