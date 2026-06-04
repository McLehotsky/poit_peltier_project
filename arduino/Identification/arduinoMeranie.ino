#include <Wire.h>
#include <LiquidCrystal_I2C.h> // Pridaná knižnica pre I2C LCD
#include <OneWire.h>
#include <DallasTemperature.h>

// ================= PINY =================
const int ONE_WIRE_BUS = 23;  // DS18B20 senzor
const int peltierPWM   = 32;  // MOSFET Peltier (Zmenené z 34 na bezpečný pin 32)
const int heaterPWM    = 13;  // MOSFET Ohrev

// Piny pre L298N (Pumpa)
const int pumpENB = 19;       // PWM rýchlosť pumpy
const int pumpIN3 = 14;       // Smer 1
const int pumpIN4 = 27;       // Smer 2

// ================= OBJEKTY =================
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// Nastavenie displeja (Adresa 0x27, 16 stĺpcov, 2 riadky)
// Ak by displej nesvietil, skús adresu 0x3F
LiquidCrystal_I2C lcd(0x27, 16, 2); 

// Premenné pre udržiavanie hodnôt výkonu
int peltier_pwm = 0;
int pump_pwm = 0;
int heater_pwm = 0;

void setup() {
  Serial.begin(115200);
  sensors.begin();

  // Inicializácia LCD displeja
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("HW Test bezi..."); // Text v prvom riadku

  // Nastavenie pinov ako výstupy
  pinMode(peltierPWM, OUTPUT);
  pinMode(heaterPWM, OUTPUT);
  pinMode(pumpENB, OUTPUT);
  pinMode(pumpIN3, OUTPUT);
  pinMode(pumpIN4, OUTPUT);

  // Nastavenie smeru toku vody (H-mostík)
  digitalWrite(pumpIN3, HIGH);
  digitalWrite(pumpIN4, LOW);
  
  // Na začiatku všetko vypneme pre istotu
  analogWrite(peltierPWM, 0);
  analogWrite(heaterPWM, 0);
  analogWrite(pumpENB, 0);
}

void loop() {
  // 1. ČÍTANIE PRÍKAZOV Z POČÍTAČA (Serial Plotter / Monitor)
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim(); // Odstráni medzery a skryté znaky
    
    if (input.startsWith("P")) {
      peltier_pwm = input.substring(1).toInt();
    } 
    else if (input.startsWith("W")) {
      pump_pwm = input.substring(1).toInt();
    } 
    else if (input.startsWith("H")) {
      heater_pwm = input.substring(1).toInt();
    }
  }

  // BEZPEČNOSTNÝ LIMIT PRE OHREV (na 12V nesmie ísť vysoko!)
  if (heater_pwm > 40) {
    heater_pwm = 40;
  }

  // 2. APLIKOVANIE VÝKONU NA HARDVÉR
  analogWrite(peltierPWM, peltier_pwm);
  analogWrite(pumpENB, pump_pwm);
  analogWrite(heaterPWM, heater_pwm);

  // 3. MERANIE TEPLOTY
  sensors.requestTemperatures();
  float temp = sensors.getTempCByIndex(0);

  // 4. VÝPIS NA LCD DISPLEJ
  lcd.setCursor(0, 1); // Nastavenie na začiatok druhého riadku
  lcd.print("Teplota: ");
  lcd.print(temp, 1);  // Vypíše teplotu s 1 desatinným miestom (napr. 25.4)
  lcd.print(" C  ");   // Medzery na konci zmažú staré znaky, ak by teplota klesla z 10 na 9

  // 5. VÝPIS PRE SERIAL PLOTTER (Sériový ploter)
  Serial.print("Teplota_x10:");
  Serial.print(temp * 10.0);
  
  Serial.print(" Peltier:");
  Serial.print(peltier_pwm);
  
  Serial.print(" Pumpa:");
  Serial.print(pump_pwm);
  
  Serial.print(" Ohrev:");
  Serial.println(heater_pwm); // Posledný výpis musí byť println!

  // Rýchlosť "filmu" (graf sa posunie 5-krát za sekundu)
  delay(200); 
}
