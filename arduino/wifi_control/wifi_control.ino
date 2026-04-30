#include <WiFi.h>
#include <HTTPClient.h>

const char* ssid = "Tvoja_WiFi";
const char* password = "Tvoje_Heslo";
const char* serverUrl = "http://192.168.1.XX:5001/api/update"; // IP tvojho PC

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); }
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    String jsonData = "{\"temp\": 24.5, \"humidity\": 50}";
    int httpResponseCode = http.POST(jsonData);
    
    http.end();
  }
  delay(2000);
}