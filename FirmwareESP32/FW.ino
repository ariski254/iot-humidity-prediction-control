#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ThreeWire.h>
#include <RtcDS1302.h>
#include <ArduinoJson.h>
#include <WiFiManager.h>
#include <time.h>
#include <ESP32Ping.h>

// definisi pin
#define DHTPIN 4
#define DHTTYPE DHT22
#define MQ135_PIN 34
#define RELAY_PIN 15
#define MOSFET_PWM 16
#define OLED_SDA 21
#define OLED_SCL 22
#define RTC_DAT 19
#define RTC_CLK 18
#define RTC_CE 23

// alamat server backend
const String serverIP = "http://YourServerIP";  // ganti dengan IP server backend Anda

// wifi cadangan
const char* WIFI_SSID = "YourSSID";  // ganti dengan SSID WiFi Anda
const char* WIFI_PASSWORD = "YourPassword";  // ganti dengan password WiFi Anda

// interval waktu dalam milidetik
const unsigned long SENSOR_INTERVAL = 1000;       // baca sensor tiap 1 detik
const unsigned long DISPLAY_INTERVAL = 500;       // update oled tiap 500 ms
const unsigned long SEND_INTERVAL = 5000;         // kirim data ke server tiap 5 detik
const unsigned long CONTROL_INTERVAL = 3000;      // ambil kontrol dari server tiap 3 detik
const unsigned long WIFI_CHECK_INTERVAL = 3000;   // cek koneksi wifi tiap 3 detik
const unsigned long RECONNECT_INTERVAL = 3000;    // coba reconnect tiap 3 detik
const unsigned long SOFT_START_DURATION = 200;    // durasi soft start 200 ms

// objek sensor dan tampilan
DHT dht(DHTPIN, DHTTYPE);
Adafruit_SSD1306 display(128, 64, &Wire, -1);
ThreeWire myWire(RTC_DAT, RTC_CLK, RTC_CE);
RtcDS1302<ThreeWire> Rtc(myWire);
WiFiManager wm;

// variabel global untuk data lingkungan
float currentHumidity = 55.0;
float currentTemp = 25.0;
int currentAQ = 0;
int fanSpeedPercent = 0;
String currentMode = "AUTO";
bool rtcSynced = false;
bool wifiConnected = false;

// timer untuk tugas periodik
unsigned long lastSensorRead = 0;
unsigned long lastDisplayUpdate = 0;
unsigned long lastDataSend = 0;
unsigned long lastControlFetch = 0;
unsigned long lastWifiCheck = 0;
unsigned long lastReconnectAttempt = 0;

bool isSendingData = false;
bool isFetchingControl = false;
bool isReconnecting = false;

// variabel untuk soft-start
bool fanStarting = false;
unsigned long fanStartTime = 0;
int fanTargetSpeed = 0;

// menampilkan pesan booting di OLED
void showBootMessage(String line1, String line2 = "") {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 20);
    display.println(line1);
    if (line2 != "") {
        display.setCursor(0, 40);
        display.println(line2);
    }
    display.display();
}

// mendapatkan timestamp dari RTC atau NTP
String getTimestamp() {
    RtcDateTime now = Rtc.GetDateTime();
    if (now.Year() < 2020 || !rtcSynced) {
        time_t now_ntp = time(nullptr);
        struct tm* timeinfo = localtime(&now_ntp);
        char buf[20];
        strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", timeinfo);
        return String(buf);
    } else {
        char buf[20];
        snprintf(buf, sizeof(buf), "%04u-%02u-%02u %02u:%02u:%02u",
                 now.Year(), now.Month(), now.Day(),
                 now.Hour(), now.Minute(), now.Second());
        return String(buf);
    }
}

// mengontrol relay (ON/OFF)
void setRelay(bool state) {
    digitalWrite(RELAY_PIN, state ? HIGH : LOW);
}

// mengatur PWM untuk kecepatan kipas (0-100%)
void setPWM(int percent) {
    percent = constrain(percent, 0, 100);
    int pwmVal = map(percent, 0, 100, 0, 255);
    ledcWrite(0, pwmVal);
}

// menerapkan kontrol kipas dengan soft-start
void applyFanControl() {
    int desiredSpeed = 0;
    if (currentMode == "ON") {
        desiredSpeed = 100;
    } else if (currentMode == "OFF") {
        desiredSpeed = 0;
    } else {
        desiredSpeed = (fanSpeedPercent > 5) ? fanSpeedPercent : 0;
    }

    if (fanStarting) {
        if (desiredSpeed == 0) {
            fanStarting = false;
            fanTargetSpeed = 0;
            setRelay(false);
            setPWM(0);
            fanSpeedPercent = 0;
            return;
        }
        if (desiredSpeed != fanTargetSpeed) {
            fanTargetSpeed = desiredSpeed;
        }
        if (millis() - fanStartTime >= SOFT_START_DURATION) {
            fanStarting = false;
            if (fanTargetSpeed > 0) {
                setRelay(true);
                setPWM(fanTargetSpeed);
                fanSpeedPercent = fanTargetSpeed;
            } else {
                setRelay(false);
                setPWM(0);
                fanSpeedPercent = 0;
            }
        }
        return;
    }

    if (fanTargetSpeed == 0 && desiredSpeed > 0) {
        fanStarting = true;
        fanStartTime = millis();
        fanTargetSpeed = desiredSpeed;
        setRelay(true);
        setPWM(100);
        fanSpeedPercent = 100;
        return;
    }

    fanTargetSpeed = desiredSpeed;
    if (desiredSpeed > 0) {
        setRelay(true);
        setPWM(desiredSpeed);
        fanSpeedPercent = desiredSpeed;
    } else {
        setRelay(false);
        setPWM(0);
        fanSpeedPercent = 0;
    }
}

// kontrol fallback lokal berbasis histeresis (saat server offline)
void fallbackControl() {
    if (currentMode == "AUTO") {
        if (currentHumidity > 70) fanSpeedPercent = 100;
        else if (currentHumidity > 60) fanSpeedPercent = 70;
        else if (currentHumidity > 55) fanSpeedPercent = 40;
        else if (currentHumidity < 45) fanSpeedPercent = 20;
        else fanSpeedPercent = 0;
        applyFanControl();
    }
}

// membaca sensor DHT22 dan MQ135
void readSensors() {
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    int aq = analogRead(MQ135_PIN);
    if (!isnan(h) && !isnan(t)) {
        currentHumidity = h;
        currentTemp = t;
    }
    currentAQ = aq;
}

// mengirim data sensor ke server
void sendDataToServer() {
    if (!wifiConnected) return;
    if (isSendingData || millis() - lastDataSend < SEND_INTERVAL) return;

    isSendingData = true;
    lastDataSend = millis();

    HTTPClient http;
    http.begin(serverIP + "/data");
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(1500);

    StaticJsonDocument<256> doc;
    doc["humidity"] = round(currentHumidity * 10) / 10.0;
    doc["temperature"] = round(currentTemp * 10) / 10.0;
    doc["air_quality"] = currentAQ;
    String jsonStr;
    serializeJson(doc, jsonStr);

    int code = http.POST(jsonStr);
    if (code != 200) Serial.printf("POST gagal, kode=%d\n", code);
    else Serial.println("POST OK");
    http.end();
    isSendingData = false;
}

// mengambil mode dan kecepatan kipas dari server
// ESP32 hanya kirim current_humidity, server yang hitung prediksi
void fetchControlFromServer() {
    if (!wifiConnected) {
        if (currentMode == "AUTO") {
            Serial.println("WiFi putus, fallback lokal.");
            fallbackControl();
        }
        return;
    }

    if (isFetchingControl || millis() - lastControlFetch < CONTROL_INTERVAL) return;

    isFetchingControl = true;
    lastControlFetch = millis();

    // ambil mode fan dari server
    HTTPClient httpMode;
    httpMode.begin(serverIP + "/api/fan/status");
    httpMode.setTimeout(1000);
    int codeMode = httpMode.GET();
    if (codeMode == 200) {
        DynamicJsonDocument docMode(128);
        deserializeJson(docMode, httpMode.getString());
        String newMode = docMode["mode"].as<String>();
        if (newMode != currentMode) {
            currentMode = newMode;
            Serial.print("Mode: ");
            Serial.println(currentMode);
        }
    }
    httpMode.end();

    // jika mode AUTO, minta kontrol ke server (server hitung prediksi + FLC)
    if (currentMode == "AUTO") {
        HTTPClient httpCtrl;
        String url = serverIP + "/api/control?current_humidity=" + String(currentHumidity, 1);
        httpCtrl.begin(url);
        httpCtrl.setTimeout(1500);

        int codeCtrl = httpCtrl.GET();
        if (codeCtrl == 200) {
            DynamicJsonDocument docCtrl(128);
            deserializeJson(docCtrl, httpCtrl.getString());
            fanSpeedPercent = docCtrl["fan_speed"] | 0;
            Serial.printf("Kontrol OK: speed=%d%%\n", fanSpeedPercent);
        } else {
            Serial.println("Gagal kontrol, fallback.");
            fallbackControl();
        }
        httpCtrl.end();
    }

    applyFanControl();
    isFetchingControl = false;
}

// memperbarui tampilan OLED
void updateDisplay() {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);

    display.setTextSize(1);
    RtcDateTime now = Rtc.GetDateTime();
    display.setCursor(0, 0);
    if (now.Year() >= 2020 && rtcSynced) {
        display.printf("%02u:%02u:%02u", now.Hour(), now.Minute(), now.Second());
    } else {
        display.print("--:--:--");
    }
    display.setCursor(90, 0);
    display.print(currentMode);

    display.setTextSize(2);
    display.setCursor(0, 16);
    display.printf("%.1f", currentTemp);
    display.setTextSize(1);
    display.print((char)247);
    display.print("C");

    display.setTextSize(2);
    display.setCursor(68, 16);
    display.printf("%.1f", currentHumidity);
    display.setTextSize(1);
    display.print("%");

    display.setTextSize(1);
    display.setCursor(0, 40);
    display.print("AQ: ");
    display.print(currentAQ);

    display.setCursor(0, 50);
    display.print("Fan: ");
    display.print(fanSpeedPercent);
    display.print("%");

    display.setCursor(85, 50);
    if (wifiConnected) display.print("WiFi");
    else display.print("NoWiFi");

    display.display();
}

// sinkronisasi RTC dengan NTP
void syncRTC() {
    configTime(7 * 3600, 0, "pool.ntp.org", "time.google.com", "id.pool.ntp.org");
    struct tm timeinfo;
    for (int i = 0; i < 5; i++) {
        if (getLocalTime(&timeinfo, 2000)) {
            RtcDateTime now(timeinfo.tm_year + 1900, timeinfo.tm_mon + 1, timeinfo.tm_mday,
                            timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
            Rtc.SetDateTime(now);
            rtcSynced = true;
            Serial.println("RTC sync OK");
            return;
        }
        delay(500);
    }
    rtcSynced = false;
    Serial.println("RTC sync gagal");
}

// setup PWM untuk kipas
void setupPWM() {
    ledcSetup(0, 500, 8);
    ledcAttachPin(MOSFET_PWM, 0);
    ledcWrite(0, 0);
}

// mencoba reconnect ke WiFi (dengan fallback WiFiManager)
void attemptReconnect() {
    Serial.println("Reconnect...");

    WiFi.setAutoReconnect(false);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    int attempts = 0;
    bool gotIP = false;
    while (attempts < 15) {
        delay(500);
        attempts++;
        Serial.print(".");
        if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0,0,0,0)) {
            gotIP = true;
            break;
        }
    }

    if (gotIP) {
        wifiConnected = true;
        isReconnecting = false;
        Serial.println("\nReconnect berhasil!");
        Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
        return;
    }

    // jika gagal, aktifkan WiFiManager dengan timeout 10 detik
    Serial.println("\nCoba WiFiManager...");
    wm.setConfigPortalTimeout(10);
    wm.setConnectTimeout(8);
    if (wm.autoConnect("ESP32-SmartHome")) {
        wifiConnected = true;
        isReconnecting = false;
        Serial.println("WiFiManager berhasil!");
        Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
    } else {
        wifiConnected = false;
        isReconnecting = true;
        Serial.println("Reconnect gagal.");
    }
}

// memeriksa koneksi WiFi dengan ping ke gateway
void checkWifi() {
    if (isReconnecting) return;

    if (WiFi.status() != WL_CONNECTED || WiFi.localIP() == IPAddress(0,0,0,0)) {
        if (wifiConnected) {
            wifiConnected = false;
            Serial.println("WiFi putus (status/IP invalid)");
        }
        isReconnecting = true;
        lastReconnectAttempt = millis();
        return;
    }

    IPAddress gateway = WiFi.gatewayIP();
    bool pingResult = Ping.ping(gateway, 2);

    if (pingResult) {
        if (!wifiConnected) {
            wifiConnected = true;
            Serial.println("WiFi OK (ping)");
        }
    } else {
        if (wifiConnected) {
            wifiConnected = false;
            Serial.println("WiFi putus (ping)");
            if (currentMode == "AUTO") fallbackControl();
            isReconnecting = true;
            lastReconnectAttempt = millis();
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("SMART HOME");

    pinMode(RELAY_PIN, OUTPUT);
    pinMode(MOSFET_PWM, OUTPUT);
    digitalWrite(RELAY_PIN, LOW);
    setupPWM();
    dht.begin();
    Rtc.Begin();

    // inisialisasi OLED
    Wire.begin(OLED_SDA, OLED_SCL);
    Wire.setClock(100000);
    bool oledFound = false;
    for (int addr = 0x3C; addr <= 0x3D; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            if (display.begin(SSD1306_SWITCHCAPVCC, addr)) {
                oledFound = true;
                break;
            }
        }
    }
    if (!oledFound) {
        Serial.println("OLED tidak ditemukan");
        display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
    }
    display.setRotation(2);

    showBootMessage("Booting...", "Memulai");
    delay(500);

    // koneksi WiFi pertama kali
    showBootMessage("Menghubungkan WiFi", "Tunggu...");
    WiFi.mode(WIFI_STA);
    WiFi.persistent(true);
    WiFi.setAutoReconnect(false);
    WiFi.setSleep(false);

    Serial.printf("Menghubung ke %s\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    int tryCount = 0;
    bool gotIP = false;
    while (tryCount < 20 && !gotIP) {
        delay(500);
        tryCount++;
        Serial.print(".");
        if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0,0,0,0)) {
            gotIP = true;
            break;
        }
        static int dot = 0;
        String dots = "";
        for (int i = 0; i <= dot % 3; i++) dots += ".";
        showBootMessage("Menghubungkan WiFi", dots);
        dot++;
    }

    if (gotIP) {
        wifiConnected = true;
        Serial.println("\nWiFi OK");
        showBootMessage("WiFi OK", "IP: " + WiFi.localIP().toString());
        delay(800);
    } else {
        Serial.println("\nGagal, pakai WiFiManager...");
        showBootMessage("WiFi gagal", "AP mode");
        delay(500);
        wm.setConfigPortalTimeout(30);
        wm.setConnectTimeout(20);
        if (wm.autoConnect("ESP32-SmartHome")) {
            wifiConnected = true;
            Serial.println("WiFiManager OK");
            showBootMessage("WiFi OK", "IP: " + WiFi.localIP().toString());
            delay(800);
        } else {
            wifiConnected = false;
            Serial.println("WiFi GAGAL");
            showBootMessage("WiFi GAGAL", "Offline");
            delay(800);
        }
    }

    // sinkronisasi RTC
    showBootMessage("Sinkron RTC", "Mengambil waktu...");
    syncRTC();
    if (rtcSynced) showBootMessage("RTC OK", "Waktu sync");
    else showBootMessage("RTC Gagal", "Waktu lokal");
    delay(600);

    // baca sensor pertama kali
    readSensors();
    showBootMessage("System Ready", "Monitoring");
    delay(600);
    Serial.println("SISTEM SIAP");
}

void loop() {
    unsigned long now = millis();

    // cek koneksi WiFi secara periodik
    if (!isReconnecting && (now - lastWifiCheck >= WIFI_CHECK_INTERVAL)) {
        lastWifiCheck = now;
        checkWifi();
    }

    // jika perlu reconnect, lakukan
    if (isReconnecting && (now - lastReconnectAttempt >= RECONNECT_INTERVAL)) {
        lastReconnectAttempt = now;
        attemptReconnect();
    }

    // baca sensor
    if (now - lastSensorRead >= SENSOR_INTERVAL) {
        lastSensorRead = now;
        readSensors();
    }

    // update OLED
    if (now - lastDisplayUpdate >= DISPLAY_INTERVAL) {
        lastDisplayUpdate = now;
        updateDisplay();
    }

    // kirim data ke server
    sendDataToServer();

    // ambil kontrol dari server (tanpa prediksi dari ESP32)
    fetchControlFromServer();

    delay(5);
}