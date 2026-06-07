#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "../secrets.h"

// ================= KONFIGURÁCIA WIFI A SERVERA =================
const char* ssid = SECRET_SSID;
const char* password = SECRET_PASS;
const char* serverUrl = SERVER_URL; 

// ================= PINY =================
const int ONE_WIRE_BUS = 23;  
const int peltierPWM   = 32;  
const int heaterPWM    = 13;  

const int pumpENB = 19;       
const int pumpIN3 = 14;       
const int pumpIN4 = 27;       

// ================= OBJEKTY =================
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
LiquidCrystal_I2C lcd(0x27, 16, 2); 

// ================= PREMENNÉ =================
int peltier_pwm = 0;
int pump_pwm = 0;
int heater_pwm = 0;
float current_temp = 0.0;

unsigned long lastHardwareLoop = 0;
unsigned long lastDotAnimation = 0;
unsigned long lastSerialAlive = 0; 
int dotCount = 0;

// Dáta zo servera
int serverMode = 0;
bool serverRunning = false;
float serverSetpoint = 0.0;
String serverStatus = "";

void setup() {
  Serial.begin(115200);
  delay(1000); 
  
  Serial.println("\n--- [START] ESP32 Program sa spustil ---");
  
  sensors.begin();
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Bootovanie...");
  
  pinMode(peltierPWM, OUTPUT);
  pinMode(heaterPWM, OUTPUT);
  pinMode(pumpENB, OUTPUT);
  pinMode(pumpIN3, OUTPUT);
  pinMode(pumpIN4, OUTPUT);

  digitalWrite(pumpIN3, HIGH);
  digitalWrite(pumpIN4, LOW);
  
  analogWrite(peltierPWM, 0);
  analogWrite(heaterPWM, 0);
  analogWrite(pumpENB, 0);

  Serial.print("Pripájam sa na WiFi: ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);
}

void loop() {
  unsigned long currentMillis = millis();

  // 1. ČÍTANIE PRÍKAZOV ZO SERIAL MONITORA
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    
    if (input.length() > 0) {
      Serial.print("\n[SERIAL INPUT] Prijatý príkaz: ");
      Serial.println(input);
      
      if (input.startsWith("P")) peltier_pwm = input.substring(1).toInt();
      else if (input.startsWith("W")) pump_pwm = input.substring(1).toInt();
      else if (input.startsWith("H")) {
        heater_pwm = input.substring(1).toInt();
        if (heater_pwm > 40) heater_pwm = 40; 
      }
    }
  }

  // STAV 1: AK NIE SME PRIPOJENÍ K WIFI (Animácia bodiek)
  if (WiFi.status() != WL_CONNECTED) {
    analogWrite(peltierPWM, 0);
    analogWrite(pumpENB, 0);
    analogWrite(heaterPWM, 0);

    if (currentMillis - lastDotAnimation >= 500) {
      lastDotAnimation = currentMillis;
      dotCount = (dotCount + 1) % 4;
      
      lcd.setCursor(0, 0);
      lcd.print("Pripajanie WiFi");
      for (int i = 0; i < 3; i++) {
        if (i < dotCount) lcd.print(".");
        else lcd.print(" ");
      }
      lcd.setCursor(0, 1);
      lcd.print("Cakam na router ");
    }
    return; 
  }

  // STAV 2: SME PRIPOJENÍ K WIFI (Komunikácia každých 1000ms)
  if (currentMillis - lastHardwareLoop >= 1000) {
    lastHardwareLoop = currentMillis;

    sensors.requestTemperatures();
    current_temp = sensors.getTempCByIndex(0);

    analogWrite(peltierPWM, peltier_pwm);
    analogWrite(pumpENB, pump_pwm);
    analogWrite(heaterPWM, heater_pwm);

    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    // Príprava JSON-u pre server
    StaticJsonDocument<200> docOut;
    docOut["request"] = "status";            
    docOut["temperature"] = current_temp;     
    docOut["pump_pwm"] = pump_pwm;           
    docOut["tec_pwm"] = peltier_pwm;         

    String requestBody;
    serializeJson(docOut, requestBody);      

    int httpCode = http.POST(requestBody);

    if (httpCode == 200) {
      String payload = http.getString();
      
      // PARSOVANIE ODPOVEDE
      StaticJsonDocument<200> docIn;
      DeserializationError error = deserializeJson(docIn, payload);

      if (!error) {
        bool canProcess = docIn["connected"]; 

        // Načítanie hodnôt z JSON-u do premenných
        serverMode = docIn["mode"];
        serverRunning = docIn["running"];
        serverSetpoint = docIn["setpoint"];
        const char* statusChar = docIn["status"];
        serverStatus = String(statusChar);

        // --- VÝPIS DO SERIAL MONITORA (Štruktúra, ktorú si chcel vidieť) ---
        Serial.println("\n================ PRIJATÝ JSON ================");
        Serial.print("  connected: "); Serial.println(canProcess ? "true" : "false");
        Serial.print("  mode:      "); Serial.println(serverMode);
        Serial.print("  running:   "); Serial.println(serverRunning ? "true" : "false");
        Serial.print("  setpoint:  "); Serial.println(serverSetpoint);
        Serial.print("  status:    "); Serial.println(serverStatus);
        Serial.println("==============================================");

        if (canProcess) {
          // Zobrazenie hodnôt zo servera na LCD displeji
          lcd.setCursor(0, 0);
          lcd.print("M:"); lcd.print(serverMode);
          lcd.print(serverRunning ? " RUN" : " STP");
          lcd.print(" S:"); lcd.print(serverSetpoint, 1);
          lcd.print("   "); // Vyčistenie konca riadku

          lcd.setCursor(0, 1);
          lcd.print("T:"); lcd.print(current_temp, 1);
          lcd.print("C   Web:OK  ");
        } else {
          // Ak connected = false
          analogWrite(peltierPWM, 0);
          analogWrite(pumpENB, 0);
          analogWrite(heaterPWM, 0);
          
          lcd.setCursor(0, 0);
          lcd.print("WiFi: Pripojene ");
          lcd.setCursor(0, 1);
          lcd.print("T:"); lcd.print(current_temp, 1);
          lcd.print("C  Web:DISC");
        }
      } else {
        Serial.print("[JSON] Chyba parsovania: ");
        Serial.println(error.c_str());
      }
    } else {
      // Server spadol alebo neodpovedá
      analogWrite(peltierPWM, 0);
      analogWrite(pumpENB, 0);
      analogWrite(heaterPWM, 0);
      
      Serial.print("[HTTP] Chyba spojenia, HTTP kód: ");
      Serial.println(httpCode);

      lcd.setCursor(0, 0);
      lcd.print("WiFi: Pripojene ");
      lcd.setCursor(0, 1);
      lcd.print("T:"); lcd.print(current_temp, 1);
      lcd.print("C  Web:ERR ");
    }
    
    http.end();
  }
}
