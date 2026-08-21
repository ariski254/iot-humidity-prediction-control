<div align="center">
  <h1>🏡 IoT Smart Home</h1>
  <p><strong>Prediksi Kelembapan & Kontrol Kipas Otomatis dengan Hybrid GA-LSTM dan Fuzzy Logic</strong></p>

  ![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
  ![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
  ![ESP32](https://img.shields.io/badge/ESP32-Arduino-00979D?style=for-the-badge&logo=arduino)
  ![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
</div>

<br>

Sistem Smart Home berbasis IoT untuk monitoring lingkungan, prediksi kelembapan multi-step (1, 6, dan 12 jam) menggunakan metode **Hybrid GA-LSTM**, serta kontrol kipas otomatis menggunakan **Fuzzy Logic Controller (FLC)**. 

Sistem ini dikembangkan secara khusus untuk membantu mengatasi kondisi kelembapan tinggi pada lingkungan dengan iklim tropis.

---

## 📖 Penjelasan Sistem

Sistem ini terdiri dari tiga komponen utama:

1. **Perangkat Keras (ESP32)** 📟  
   Membaca suhu dan kelembapan menggunakan **DHT22**, serta kualitas udara menggunakan **MQ135** secara *real-time*.
2. **Backend Server (FastAPI)** ⚙️  
   Menerima data sensor, menjalankan model prediksi Hybrid GA-LSTM, dan menghitung kecepatan kipas menggunakan Fuzzy Logic Controller.
3. **Dashboard Web** 📊  
   Menampilkan data sensor, grafik historis, hasil prediksi, serta kontrol mode kipas (ON/OFF/AUTO).

> **💡 Mengapa GA-LSTM?**  
> Model ini melakukan optimasi hyperparameter secara otomatis menggunakan *Genetic Algorithm* (GA). Prediksi kelembapan 1 jam ke depan digunakan sebagai masukan *feedforward* bagi FLC sehingga kipas bekerja secara **proaktif**, bukan reaktif terhadap kondisi saat ini.

---

## 📊 Sumber Dataset

Dataset diperoleh dari pengambilan data secara langsung di ruangan dengan ventilasi terbatas selama **75 hari** menggunakan sensor DHT22 yang terhubung dengan ESP32.

| Parameter | Keterangan / Nilai |
| :--- | :--- |
| **Total Sampel** | 36.647 data point |
| **Interval Pengiriman** | 5 detik |
| **Kelembapan (Min - Max)** | 53.8% - 86.1% |
| **Rata-rata Kelembapan** | 68.3% |
| **Fitur Dataset** | Kelembapan, Suhu, Kualitas Udara |
| **Proporsi Pembagian Data** | Training (70%), Validasi (15%), Pengujian (15%) |

---

## 🌟 Fitur Utama

- 📡 **Monitoring Real-Time**: Menampilkan suhu, kelembapan, dan kualitas udara melalui OLED dan Web Dashboard.
- 🔮 **Prediksi Multi-Step**: Memprediksi kelembapan 1, 6, dan 12 jam ke depan.
- 🧬 **Hybrid GA-LSTM**: Optimasi hyperparameter model LSTM secara otomatis dengan *Genetic Algorithm*.
- 🎛️ **Fuzzy Logic Controller (FLC)**: Mengatur kecepatan kipas secara dinamis (0–100%) berdasarkan kondisi ruangan dan prediksi.
- 🔄 **Auto-Training**: Model dapat dilatih ulang berkala untuk adaptasi lingkungan.
- 🛡️ **Fallback Control**: ESP32 mengambil alih kontrol secara lokal (mekanisme histeresis) jika server terputus.

### 🌬️ Mode Operasi Kipas
- 🟢 **ON** — Kipas berjalan pada 100%.
- 🔴 **OFF** — Kipas dimatikan.
- 🤖 **AUTO** — Kecepatan kipas dikontrol otomatis oleh FLC (1-99%).

---

## 📁 Struktur Folder

```text
SmartHome/
├── FirmwareESP32/
│   └── FW.ino                  # Program ESP32 (C/C++)
├── main.py                     # Entry point FastAPI
├── models.py                   # Model database SQLAlchemy
├── ga_lstm_model.py            # Implementasi Hybrid GA-LSTM
├── fuzzy_controller.py         # Implementasi Fuzzy Logic Controller
├── requirements.txt            # Dependencies Python
├── data/                       # Direktori penyimpanan Model & Metrik
├── templates/
│   └── index.html              # Dashboard Web UI
└── README.md                   # Dokumentasi proyek
```

---

## 🛠️ Instalasi dan Menjalankan Sistem

### 1. Backend FastAPI

Install *dependencies*:

```bash
pip install -r requirements.txt
```

Jalankan server:
```bash
python main.py
```
> **Catatan:** Server berjalan di `http://localhost:8000` atau `http://0.0.0.0:8000`. Pastikan komputer server dan ESP32 berada di jaringan Wi-Fi yang sama.

### 2. Firmware ESP32

1. Buka Arduino IDE dan buka file `FirmwareESP32/FW.ino`.
2. Sesuaikan konfigurasi jaringan pada kode:
   ```cpp
   const char* WIFI_SSID = "WiFi_Anda";
   const char* WIFI_PASSWORD = "Password_Anda";
   const String serverIP = "http://192.168.x.x:8000"; // Sesuaikan IP Server
   ```
3. Install *Library* berikut via Library Manager Arduino:
   - `DHT sensor library` (Adafruit)
   - `Adafruit SSD1306` & `Adafruit GFX`
   - `ArduinoJson`
   - `WiFiManager`
   - `ESP32Ping`
   - `RtcDS1302`
4. Pilih board **ESP32 Dev Module** lalu klik **Upload**.

### 3. Akses Dashboard

Buka browser dan navigasikan ke IP Server Anda:
```text
http://192.168.x.x:8000
```
Dashboard akan menampilkan pemantauan sensor *real-time*, grafik riwayat, hasil prediksi, dan panel kontrol kipas.

---

## 🤖 Metode yang Digunakan

### 1. Hybrid GA-LSTM
- **LSTM (Long Short-Term Memory)** digunakan untuk mempelajari pola temporal data sensor dalam memprediksi kelembapan (Target: *t+1, t+6, t+12 jam*).
- **Genetic Algorithm (GA)** mengoptimasi hyperparameter LSTM agar secara otomatis menyesuaikan dengan karakteristik dataset.

### 2. Fuzzy Logic Controller (FLC)
Menentukan kecepatan kipas dengan merespons kondisi *real-time* digabung dengan prediksi 1 jam ke depan untuk mencegah kenaikan kelembapan yang berlebihan.

---

## 🚨 Fallback Mode (Sistem Pengaman)
Apabila ESP32 **kehilangan koneksi** dengan backend server, sistem tidak akan berhenti. ESP32 secara otomatis berpindah ke kontrol lokal berbasis histeresis. Kipas tetap beroperasi menggunakan data pembacaan sensor terakhir untuk menjamin perangkat tetap berfungsi.

---

## 📌 Catatan & Troubleshooting
- Pastikan IP komputer server *reachable* dari ESP32 (cek IP menggunakan `ipconfig` di Windows atau `ifconfig` di Linux).
- Pastikan *port 8000* tidak diblokir oleh Firewall.
- Folder `data/` akan dibuat otomatis saat aplikasi dijalankan untuk menyimpan model dan log metrik hasil training.

---
