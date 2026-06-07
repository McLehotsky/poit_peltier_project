#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <PID_v1.h>
#include "secrets.h"

// ================= KONFIGURÁCIA =================
const char* ssid      = SECRET_SSID;
const char* password  = SECRET_PASS;
const char* serverUrl = SERVER_URL;

const int WIFI_TIMEOUT_S   = 15;
const int SERIAL_TIMEOUT_S = 3;
const int SERIAL_DEAD_MS   = 5000;

// ================= PINY =================
const int ONE_WIRE_BUS = 23;
const int peltierPWM   = 32;
const int heaterPWM    = 13;
const int pumpENB      = 19;
const int pumpIN3      = 14;
const int pumpIN4      = 27;

// ================= OBJEKTY =================
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
LiquidCrystal_I2C lcd(0x27, 16, 2);

// ================= KOMUNIKAČNÝ MÓD =================
enum CommMode {
  COMM_WIFI,
  COMM_SERIAL,
  COMM_NONE
};

// ================= RTOS: ZDIEĽANÁ PAMÄŤ =================
struct TelemetryData {
  float currentTemp;
  int peltierPWM;
  int pumpPWM;
  int heaterPWM;
  bool wifiConnected;
  bool serverConnected;
  bool serverRunning;
  int currentMode;
  bool isRunning;
  float currentSetpoint;
  CommMode commMode;
};
TelemetryData sharedData;
SemaphoreHandle_t dataMutex;
SemaphoreHandle_t wifiMutex;

// ================= RTOS: SCHRÁNKA PRÍKAZOV =================
struct ControlCommand {
  bool running;
  int mode;
  double setpoint;
  double target_pump_pwm;
  double target_tec_pwm;
  int heaterPower;   // "error" zo servera = PWM heatera (0-255)
  bool heaterActive; // "isErrorActive" zo servera = či heater beží
};
QueueHandle_t commandQueue;

// ================= PID PREMENNÉ =================
double Setpoint, CurrentTemp;
double Output_Peltier, Output_Pump;

PID peltierPID(&CurrentTemp, &Output_Peltier, &Setpoint, 32.48, 0.039, 0.0, REVERSE);
PID pumpPID(&CurrentTemp, &Output_Pump, &Setpoint, 4.58, 0.013, 0.0, REVERSE);

const double BANGBANG_THRESHOLD = 0.3;


// =================================================================
//         POMOCNÁ FUNKCIA: Pošli telemetriu cez Serial
// =================================================================
void sendSerialTelemetry(const TelemetryData &data)
{
  StaticJsonDocument<256> doc;
  doc["temperature"] = data.currentTemp;
  doc["pump_pwm"]    = data.pumpPWM;
  doc["tec_pwm"]     = data.peltierPWM;
  doc["heater_pwm"]  = data.heaterPWM;
  doc["mode"]        = data.currentMode;
  doc["running"]     = data.isRunning;
  doc["setpoint"]    = data.currentSetpoint;
  doc["comm"]        = "serial";

  String out;
  serializeJson(doc, out);
  Serial.println(out);
}


// =================================================================
//                      JADRO 1: HARDVÉROVÝ PROCES
// =================================================================
void HardwareTask(void *pvParameters)
{
  sensors.begin();
  sensors.setWaitForConversion(false);

  lcd.init();
  lcd.backlight();

  pinMode(peltierPWM, OUTPUT);
  pinMode(heaterPWM,  OUTPUT);
  pinMode(pumpENB,    OUTPUT);
  pinMode(pumpIN3,    OUTPUT);
  pinMode(pumpIN4,    OUTPUT);
  digitalWrite(pumpIN3, HIGH);
  digitalWrite(pumpIN4, LOW);

  peltierPID.SetMode(AUTOMATIC);
  pumpPID.SetMode(AUTOMATIC);
  peltierPID.SetSampleTime(200);
  pumpPID.SetSampleTime(200);

  ControlCommand currentState = {false, 1, 25.0, 150.0, 100.0, 0, false};
  bool is_wifi_ok          = false;
  bool is_server_connected = false;
  CommMode currentCommMode = COMM_NONE;
  char lcdBuf[17];
  bool lastWasBangBang = true;

  sensors.requestTemperatures();

  while (true) {
    // 1. PRÍKAZY Z FRONTY
    ControlCommand incomingCmd;
    while (xQueueReceive(commandQueue, &incomingCmd, 0) == pdPASS) {
      currentState = incomingCmd;
      Setpoint     = currentState.setpoint;
    }

    // 2. TEPLOTA
    if (sensors.isConversionComplete()) {
      float newTemp = sensors.getTempCByIndex(0);
      if (newTemp != DEVICE_DISCONNECTED_C) {
        CurrentTemp = newTemp;
      }
      sensors.requestTemperatures();
    }

    // 3. STAV SIETE
    if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
      is_wifi_ok          = sharedData.wifiConnected;
      is_server_connected = sharedData.serverConnected;
      currentCommMode     = sharedData.commMode;
      xSemaphoreGive(dataMutex);
    }

    // 4. AKTIVITA SYSTÉMU
    bool system_active = false;
    if (!is_server_connected && currentCommMode == COMM_NONE) {
      // žiadne spojenie
    } else if (!currentState.running) {
      // čakáme na running
    } else if (CurrentTemp > 50.0) {
      // bezpečnostný teplotný limit
    } else if (is_server_connected || currentCommMode == COMM_SERIAL) {
      system_active = true;
    }

    // =============================================================
    // 5. RIADENIE
    //
    // Mód 1: Peltier bang-bang+PID,  Pumpa manuálna
    // Mód 2: Peltier manuálny,       Pumpa PID
    // Mód 3: Peltier bang-bang+PID,  Pumpa PID
    // Mód 4: Peltier manuálny,       Pumpa manuálna
    //
    // HEATER:
    //   isErrorActive = true  → heater beží na PWM = error (0-255)
    //   isErrorActive = false → heater vypnutý (PWM = 0)
    //   Heater beží nezávisle od módov, peltier a pumpa bežia normálne
    // =============================================================

    int final_heater_pwm = 0;

    if (system_active) {

      // --- HEATER (nezávislý od módu) ---
      if (currentState.heaterActive) {
        // error = PWM hodnota heatera priamo zo servera
        final_heater_pwm = constrain(currentState.heaterPower, 0, 255);
        Serial.printf("[HW] Heater ON: PWM=%d\n", final_heater_pwm);
      } else {
        final_heater_pwm = 0;
      }

      // --- PELTIER ---
      if (currentState.mode == 1 || currentState.mode == 3) {
        double pidError = Setpoint - CurrentTemp;

        if (pidError > BANGBANG_THRESHOLD) {
          Output_Peltier = 0;
          peltierPID.SetMode(MANUAL);
          lastWasBangBang = true;

        } else if (pidError < -BANGBANG_THRESHOLD) {
          Output_Peltier = 255;
          peltierPID.SetMode(MANUAL);
          lastWasBangBang = true;

        } else {
          if (lastWasBangBang) {
            Output_Peltier  = (pidError > 0) ? 180 : 50;
            peltierPID.SetMode(AUTOMATIC);
            lastWasBangBang = false;
          }
          peltierPID.SetMode(AUTOMATIC);
          peltierPID.SetOutputLimits(0, 255);
          peltierPID.Compute();
        }

      } else if (currentState.mode == 2 || currentState.mode == 4) {
        Output_Peltier  = currentState.target_tec_pwm;
        peltierPID.SetMode(MANUAL);
        lastWasBangBang = true;
      }

      // --- PUMPA ---
      pumpPID.SetOutputLimits(100, 255);

      if (currentState.mode == 1 || currentState.mode == 4) {
        Output_Pump = currentState.target_pump_pwm;
        pumpPID.SetMode(MANUAL);
      } else if (currentState.mode == 2 || currentState.mode == 3) {
        pumpPID.SetMode(AUTOMATIC);
        pumpPID.Compute();
      }

    } else {
      Output_Peltier   = 0;
      Output_Pump      = 0;
      final_heater_pwm = 0;
      peltierPID.SetMode(MANUAL);
      pumpPID.SetMode(MANUAL);
      lastWasBangBang  = true;
    }

    int final_pump_pwm = (int)Output_Pump;

    // 6. HARDVÉR
    analogWrite(peltierPWM, (int)Output_Peltier);
    analogWrite(pumpENB,    final_pump_pwm);
    analogWrite(heaterPWM,  final_heater_pwm);

    // 7. ZDIEĽANIE DÁT
    if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
      sharedData.currentTemp     = CurrentTemp;
      sharedData.peltierPWM      = (int)Output_Peltier;
      sharedData.pumpPWM         = final_pump_pwm;
      sharedData.heaterPWM       = final_heater_pwm;
      sharedData.currentMode     = currentState.mode;
      sharedData.isRunning       = system_active;
      sharedData.currentSetpoint = currentState.setpoint;
      xSemaphoreGive(dataMutex);
    }

    // 8. LCD
    lcd.setCursor(0, 0);
    if (currentCommMode == COMM_SERIAL) {
      snprintf(lcdBuf, sizeof(lcdBuf), "M%d USB  S:%.1f  ", currentState.mode, currentState.setpoint);
      lcd.print(lcdBuf);
    } else if (!is_wifi_ok) {
      lcd.print("Bez WiFi!       ");
    } else if (!is_server_connected) {
      lcd.print("Hladam server...");
    } else if (!currentState.running) {
      snprintf(lcdBuf, sizeof(lcdBuf), "M%d STANDBY S:%.1f", currentState.mode, currentState.setpoint);
      lcd.print(lcdBuf);
    } else {
      snprintf(lcdBuf, sizeof(lcdBuf), "M%d RUN    S:%.1f", currentState.mode, currentState.setpoint);
      lcd.print(lcdBuf);
    }

    // Druhý riadok: teplota + PWM, pri aktívnom heateri ukáž H
    lcd.setCursor(0, 1);
    if (currentState.heaterActive) {
      snprintf(lcdBuf, sizeof(lcdBuf), "T:%.1f P%d H%d   ",
               CurrentTemp, (int)Output_Peltier, final_heater_pwm);
    } else {
      snprintf(lcdBuf, sizeof(lcdBuf), "T:%.1f P%d W%d   ",
               CurrentTemp, (int)Output_Peltier, final_pump_pwm);
    }
    lcd.print(lcdBuf);

    vTaskDelay(200 / portTICK_PERIOD_MS);
  }
}


// =================================================================
//                      JADRO 0: SIEŤOVÝ PROCES
// =================================================================
void NetworkTask(void *pvParameters)
{
  vTaskDelay(1000 / portTICK_PERIOD_MS);


  // OPRAVA: Explicitný reset WiFi stacku pred každým pripojením
  // Bez toho ESP32 po nahraní kódu niekedy zostane v starom stave
  WiFi.disconnect(true, true); // odpoj + vymaž credentials z RTC pamäte
  WiFi.mode(WIFI_OFF);         // úplne vypni WiFi hardware
  vTaskDelay(500 / portTICK_PERIOD_MS);
  WiFi.mode(WIFI_STA);         // zapni znova ako station
  vTaskDelay(200 / portTICK_PERIOD_MS);

  Serial.println("\n[NET] Spajam sa s WiFi...");
  WiFi.begin(ssid, password);

  int wifiRetries = WIFI_TIMEOUT_S * 2;
  while (WiFi.status() != WL_CONNECTED && wifiRetries > 0) {
    vTaskDelay(500 / portTICK_PERIOD_MS);
    Serial.print(".");
    wifiRetries--;
  }

  CommMode activeMode = COMM_NONE;

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[NET] WiFi OK! IP: %s\n", WiFi.localIP().toString().c_str());
    activeMode = COMM_WIFI;
  } else {
    Serial.println("\n[NET] WiFi zlyhalo. Skusam Serial fallback...");
    WiFi.disconnect();

    Serial.println("[SERIAL] Cakam na HELLO...");
    Serial.println("[SERIAL] Posli: {\"cmd\":\"HELLO\"}");

    unsigned long serialWaitStart = millis();
    bool helloReceived = false;

    while ((millis() - serialWaitStart) < (SERIAL_TIMEOUT_S * 1000UL)) {
      if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();
        StaticJsonDocument<100> doc;
        if (!deserializeJson(doc, line)) {
          const char* cmd = doc["cmd"] | "";
          if (strcmp(cmd, "HELLO") == 0) {
            helloReceived = true;
            Serial.println("[SERIAL] HELLO prijate!");
            Serial.println("{\"status\":\"READY\",\"comm\":\"serial\"}");
            break;
          }
        }
      }
      vTaskDelay(50 / portTICK_PERIOD_MS);
    }

    activeMode = helloReceived ? COMM_SERIAL : COMM_NONE;
    if (!helloReceived) {
      Serial.println("[SERIAL] Timeout - standalone mod.");
    }
  }

  if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
    sharedData.commMode        = activeMode;
    sharedData.wifiConnected   = (activeMode == COMM_WIFI);
    sharedData.serverConnected = false;
    xSemaphoreGive(dataMutex);
  }

  TelemetryData localData;
  bool last_srv_ok = false;
  unsigned long lastSerialRx = millis();

  int failCount           = 0;
  const int BASE_DELAY_MS = 1000;
  const int MAX_DELAY_MS  = 10000;
  const int HTTP_TIMEOUT  = 2000;

  while (true) {

    if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
      localData = sharedData;
      xSemaphoreGive(dataMutex);
    }

    // ==============================================================
    // WIFI MÓD
    // ==============================================================
    if (activeMode == COMM_WIFI) {
      bool wifi_ok = (WiFi.status() == WL_CONNECTED);
      last_srv_ok  = false;

      if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
        sharedData.wifiConnected = wifi_ok;
        xSemaphoreGive(dataMutex);
      }

      if (wifi_ok) {
        if (xSemaphoreTake(wifiMutex, pdMS_TO_TICKS(3000))) {

          WiFiClient client;
          HTTPClient http;
          http.begin(client, serverUrl);
          http.addHeader("Content-Type", "application/json");
          http.setTimeout(HTTP_TIMEOUT);
          http.setReuse(false);

          StaticJsonDocument<256> docOut;
          docOut["request"]     = "status";
          docOut["temperature"] = localData.currentTemp;
          docOut["pump_pwm"]    = localData.pumpPWM;
          docOut["tec_pwm"]     = localData.peltierPWM;
          docOut["heater_pwm"]  = localData.heaterPWM;

          String body;
          serializeJson(docOut, body);

          Serial.printf("[NET] POST | Body: %s\n", body.c_str());
          int httpCode = http.POST(body);
          Serial.printf("[NET] HTTP kod: %d\n", httpCode);

          if (httpCode == 200) {
            String payload = http.getString();
            Serial.printf("[NET] Odpoved: %s\n", payload.c_str());

            StaticJsonDocument<300> docIn;
            DeserializationError err = deserializeJson(docIn, payload);

            if (!err) {
              last_srv_ok = true;
              Serial.printf("[NET] Heater debug -> error:%d isErrorActive:%s\n", 
              (int)docIn["error"], 
              (bool)docIn["isErrorActive"] ? "TRUE" : "FALSE");
              failCount   = 0;

              ControlCommand newCmd;
              newCmd.running         = docIn["running"]        | false;
              newCmd.mode            = docIn["mode"]            | 1;
              newCmd.setpoint        = docIn["setpoint"]        | 25.0;
              newCmd.target_pump_pwm = docIn["target_pump"]     | 0;
              newCmd.target_tec_pwm  = docIn["target_tec"]      | 0;
              newCmd.heaterPower     = docIn["error"]           | 0;
              newCmd.heaterActive    = docIn["isErrorActive"]   | false;

              Serial.printf("[NET] Cmd -> Run:%s M:%d Set:%.1f Pump:%.0f TEC:%.0f Heater:%d HtrOn:%s\n",
                            newCmd.running      ? "T" : "F",
                            newCmd.mode,
                            newCmd.setpoint,
                            newCmd.target_pump_pwm,
                            newCmd.target_tec_pwm,
                            newCmd.heaterPower,
                            newCmd.heaterActive ? "T" : "F");

              Serial.printf("[NET] QUEUE -> heaterPower:%d heaterActive:%s\n",
              newCmd.heaterPower,
              newCmd.heaterActive ? "T" : "F");
              xQueueSend(commandQueue, &newCmd, 0);
            } else {
              failCount++;
            }
          } else {
            Serial.printf("[NET] CHYBA: %d (%s)\n", httpCode, http.errorToString(httpCode).c_str());
            failCount++;
          }

          http.end();
          client.stop();
          xSemaphoreGive(wifiMutex);
        }
      } else {
        failCount++;
      }

      if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
        sharedData.serverConnected = last_srv_ok;
        xSemaphoreGive(dataMutex);
      }

      int delayMs = BASE_DELAY_MS;
      if (failCount > 0) {
        delayMs = min(BASE_DELAY_MS * (1 << min(failCount, 4)), MAX_DELAY_MS);
        Serial.printf("[NET] Backoff: %d zlyhaní, %dms\n", failCount, delayMs);
      }
      vTaskDelay(delayMs / portTICK_PERIOD_MS);
    }

    // ==============================================================
    // SERIAL MÓD
    // ==============================================================
    else if (activeMode == COMM_SERIAL) {

      sendSerialTelemetry(localData);

      while (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();
        if (line.length() == 0) continue;

        StaticJsonDocument<200> docIn;
        if (!deserializeJson(docIn, line)) {
          lastSerialRx = millis();

          if (docIn.containsKey("running")) {
            ControlCommand newCmd;
            newCmd.running         = docIn["running"]        | false;
            newCmd.mode            = docIn["mode"]            | 1;
            newCmd.setpoint        = docIn["setpoint"]        | 25.0;
            newCmd.target_pump_pwm = docIn["target_pump"]     | 0;
            newCmd.target_tec_pwm  = docIn["target_tec"]      | 0;
            newCmd.heaterPower     = docIn["error"]           | 0;
            newCmd.heaterActive    = docIn["isErrorActive"]   | false;
            xQueueSend(commandQueue, &newCmd, 0);
          }

          const char* cmd = docIn["cmd"] | "";
          if (strcmp(cmd, "PING") == 0) {
            Serial.println("{\"cmd\":\"PONG\"}");
          }
        }
      }

      bool serialAlive = (millis() - lastSerialRx) < SERIAL_DEAD_MS;

      if (!serialAlive) {
        Serial.println("[SERIAL] PC neodpoveda - standalone mod.");
        activeMode = COMM_NONE;
        if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
          sharedData.commMode        = COMM_NONE;
          sharedData.serverConnected = false;
          xSemaphoreGive(dataMutex);
        }
      } else {
        if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
          sharedData.commMode        = COMM_SERIAL;
          sharedData.serverConnected = true;
          xSemaphoreGive(dataMutex);
        }
      }

      vTaskDelay(1000 / portTICK_PERIOD_MS);
    }

    // ==============================================================
    // NONE MÓD
    // ==============================================================
    else {
      if (xSemaphoreTake(dataMutex, portMAX_DELAY)) {
        sharedData.serverConnected = false;
        sharedData.commMode        = COMM_NONE;
        xSemaphoreGive(dataMutex);
      }
      vTaskDelay(2000 / portTICK_PERIOD_MS);
    }
  }
}


// =================================================================
//                      HLAVNÝ SETUP
// =================================================================
void setup()
{
  Serial.begin(115200);
  delay(500);

  dataMutex    = xSemaphoreCreateMutex();
  wifiMutex    = xSemaphoreCreateMutex();
  commandQueue = xQueueCreate(10, sizeof(ControlCommand));

  xTaskCreatePinnedToCore(NetworkTask,  "NetTask", 10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(HardwareTask, "HwTask",  10000, NULL, 2, NULL, 1);
}

void loop()
{
  vTaskDelete(NULL);
}
