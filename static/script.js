// Script.js - logika antarmuka web untuk smart home

let humidityChart = null;
let tempAqChart = null;
let currentMode = 'AUTO';
let previousHumidity = null;
let previousTemperature = null;

// fungsi untuk memperbarui jam di header
function updateClock() {
    const now = new Date();
    document.getElementById('header-time').textContent = now.toLocaleTimeString('id-ID', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

// fungsi navigasi antar halaman
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', function(e) {
        e.preventDefault();
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        this.classList.add('active');
        const view = this.dataset.view;
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        document.getElementById('view-' + view).classList.add('active');
        document.getElementById('page-title').textContent = view === 'dashboard' ? 'Dashboard' : 'History';
        if (view === 'history') loadHistory();
    });
});

// fungsi untuk mengganti mode kipas dari tombol
document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        setFanMode(this.dataset.mode);
    });
});

// kirim permintaan perubahan mode ke server
async function setFanMode(mode) {
    try {
        const res = await fetch('/api/fan/toggle/' + mode);
        if (res.ok) {
            currentMode = mode;
            updateModeButtons();
            setTimeout(fetchPredictionAndControl, 100);
        }
    } catch (err) { console.error(err); }
}

// perbarui tampilan tombol mode sesuai status terkini
function updateModeButtons() {
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    const btn = document.querySelector(`.mode-btn[data-mode="${currentMode}"]`);
    if (btn) btn.classList.add('active');
    const badge = document.getElementById('fan-mode-badge');
    if (badge) {
        badge.textContent = currentMode;
        badge.className = 'badge-mode ' + currentMode.toLowerCase();
    }
}

// tentukan status kualitas udara berdasarkan nilai ADC
function getAQStatus(value) {
    if (value < 50) return { label: 'Baik', color: '#48bb78' };
    if (value < 100) return { label: 'Sedang', color: '#ecc94b' };
    if (value < 150) return { label: 'Tidak Sehat', color: '#ed8936' };
    return { label: 'Berbahaya', color: '#fc8181' };
}

// ambil data sensor terbaru (diperbarui setiap 2 detik)
async function fetchRealtime() {
    try {
        const res = await fetch('/api/latest');
        const latest = await res.json();
        if (!latest.humidity && latest.humidity !== 0) return;

        const hum = Number(latest.humidity).toFixed(1);
        const temp = Number(latest.temperature).toFixed(1);
        const aq = latest.air_quality;

        document.getElementById('humidity-value').innerHTML = hum + '<span class="unit">%</span>';
        document.getElementById('temperature-value').innerHTML = temp + '<span class="unit">°C</span>';
        document.getElementById('aq-value').innerHTML = aq;

        const aqStatus = getAQStatus(aq);
        document.getElementById('aq-status').textContent = aqStatus.label;
        document.getElementById('aq-status').style.color = aqStatus.color;

        if (latest.timestamp) {
            const time = new Date(latest.timestamp).toLocaleTimeString('id-ID');
            document.getElementById('humidity-time').textContent = time;
            document.getElementById('temperature-time').textContent = time;
            document.getElementById('aq-time').textContent = time;
            document.getElementById('last-update').textContent = 'Update terakhir: ' + new Date(latest.timestamp).toLocaleString('id-ID');
        }

        // trend kelembapan
        const trendHum = document.getElementById('humidity-trend');
        if (previousHumidity !== null) {
            const diff = (hum - previousHumidity).toFixed(1);
            if (diff > 0) { trendHum.textContent = '↑' + diff + '%'; trendHum.style.color = '#fc8181'; }
            else if (diff < 0) { trendHum.textContent = '↓' + Math.abs(diff) + '%'; trendHum.style.color = '#48bb78'; }
            else { trendHum.textContent = '→ 0%'; trendHum.style.color = '#a0aec0'; }
        } else { trendHum.textContent = '--'; }
        previousHumidity = hum;

        // trend suhu
        const trendTemp = document.getElementById('temperature-trend');
        if (previousTemperature !== null) {
            const diff = (temp - previousTemperature).toFixed(1);
            if (diff > 0) { trendTemp.textContent = '↑' + diff + '°C'; trendTemp.style.color = '#fc8181'; }
            else if (diff < 0) { trendTemp.textContent = '↓' + Math.abs(diff) + '°C'; trendTemp.style.color = '#48bb78'; }
            else { trendTemp.textContent = '→ 0°C'; trendTemp.style.color = '#a0aec0'; }
        } else { trendTemp.textContent = '--'; }
        previousTemperature = temp;

    } catch (err) { console.error('Realtime error:', err); }
}

// ambil prediksi dan kontrol dari server (dijalankan setiap 10 detik)
async function fetchPredictionAndControl() {
    try {
        // ambil mode terbaru
        const statusRes = await fetch('/api/fan/status');
        if (statusRes.ok) {
            const status = await statusRes.json();
            if (status.mode) {
                currentMode = status.mode;
                updateModeButtons();
            }
        }

        // ambil prediksi
        const predRes = await fetch('/api/predict');
        const pred = await predRes.json();
        if (pred.predictions) {
            document.getElementById('pred1h').innerHTML = Number(pred.predictions['1h']).toFixed(1) + '<span class="unit">%</span>';
            document.getElementById('pred6h').innerHTML = Number(pred.predictions['6h']).toFixed(1) + '<span class="unit">%</span>';
            document.getElementById('pred12h').innerHTML = Number(pred.predictions['12h']).toFixed(1) + '<span class="unit">%</span>';
        }

        // ambil kecepatan kipas dari server (server akan menghitung prediksi 1 jam secara internal)
        const latestRes = await fetch('/api/latest');
        const latest = await latestRes.json();
        const currentHum = latest.humidity || 55;

        let fanSpeed = 0;
        if (currentMode === 'ON') {
            fanSpeed = 100;
        } else if (currentMode === 'OFF') {
            fanSpeed = 0;
        } else {
            // cukup kirim current_humidity, server akan cari prediksi sendiri
            const ctrlRes = await fetch(`/api/control?current_humidity=${currentHum}`);
            if (ctrlRes.ok) {
                const ctrl = await ctrlRes.json();
                fanSpeed = ctrl.fan_speed;
            }
        }

        document.getElementById('fan-speed').innerHTML = fanSpeed + '<span class="unit">%</span>';
        document.getElementById('fan-speed-label').textContent = fanSpeed + '%';
        document.getElementById('fan-fill').style.width = fanSpeed + '%';

        // ambil data history untuk grafik
        const histRes = await fetch('/api/history?limit=30');
        if (histRes.ok) {
            const hist = await histRes.json();
            updateCharts(hist);
        }
    } catch (err) { console.error('Prediction/Control error:', err); }
}

// perbarui grafik humidity dan temperature/AQ
function updateCharts(hist) {
    const timeLabels = hist.timestamps.map(ts => new Date(ts).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }));

    // grafik kelembapan
    const humData = hist.humidity;
    const minHum = Math.min(...humData);
    const maxHum = Math.max(...humData);
    const yMin = Math.max(30, minHum - 5);
    const yMax = Math.min(100, maxHum + 5);
    const ctx1 = document.getElementById('humidityChart').getContext('2d');
    if (humidityChart) {
        humidityChart.data.labels = timeLabels;
        humidityChart.data.datasets[0].data = humData;
        humidityChart.update();
    } else {
        humidityChart = new Chart(ctx1, {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [{
                    label: 'Kelembapan',
                    data: humData,
                    borderColor: '#2b6cb0',
                    backgroundColor: (ctx) => {
                        const chart = ctx.chart;
                        const {ctx: c, chartArea} = chart;
                        if (!chartArea) return 'rgba(43,108,176,0.2)';
                        const gradient = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
                        gradient.addColorStop(0, 'rgba(43,108,176,0.4)');
                        gradient.addColorStop(1, 'rgba(43,108,176,0.02)');
                        return gradient;
                    },
                    fill: true,
                    tension: 0.3,
                    pointRadius: 2,
                    pointBackgroundColor: '#2b6cb0',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 1,
                    spanGaps: false,
                    borderWidth: 2.5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { min: yMin, max: yMax, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#a0aec0' } },
                    x: { grid: { display: false }, ticks: { color: '#a0aec0', maxTicksLimit: 10 } }
                },
                interaction: { intersect: false, mode: 'index' }
            }
        });
    }

    // grafik suhu dan kualitas udara
    const tempData = hist.temperature;
    const aqData = hist.air_quality;
    const ctx2 = document.getElementById('tempAqChart').getContext('2d');
    if (tempAqChart) {
        tempAqChart.data.labels = timeLabels;
        tempAqChart.data.datasets[0].data = tempData;
        tempAqChart.data.datasets[1].data = aqData;
        tempAqChart.update();
    } else {
        tempAqChart = new Chart(ctx2, {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'Suhu', data: tempData, borderColor: '#e53e3e', backgroundColor: 'rgba(229,62,62,0.08)', fill: true, tension: 0.3, pointRadius: 2, yAxisID: 'y' },
                    { label: 'Kualitas Udara', data: aqData, borderColor: '#dd6b20', backgroundColor: 'rgba(221,107,32,0.08)', fill: true, tension: 0.3, pointRadius: 2, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top', labels: { boxWidth: 12, font: { size: 10, color: '#a0aec0' } } }
                },
                scales: {
                    y: { type: 'linear', position: 'left', grid: { color: 'rgba(255,255,255,0.05)' }, title: { display: true, text: '°C', color: '#a0aec0' } },
                    y1: { type: 'linear', position: 'right', grid: { display: false }, title: { display: true, text: 'AQI', color: '#a0aec0' } },
                    x: { grid: { display: false } }
                }
            }
        });
    }
}

// ambil dan tampilkan 50 data history terbaru
async function loadHistory() {
    try {
        const res = await fetch('/api/history?limit=50');
        const data = await res.json();
        const tbody = document.getElementById('history-body');
        if (data.timestamps && data.timestamps.length > 0) {
            let html = '';
            for (let i = data.timestamps.length - 1; i >= 0; i--) {
                const d = new Date(data.timestamps[i]);
                html += `<tr>
                    <td>${i+1}</td>
                    <td>${d.toLocaleString('id-ID')}</td>
                    <td>${Number(data.humidity[i]).toFixed(1)}%</td>
                    <td>${Number(data.temperature[i]).toFixed(1)}°C</td>
                    <td>${data.air_quality[i]}</td>
                </tr>`;
            }
            tbody.innerHTML = html;
        } else {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#4a5568;">Belum ada data</td></tr>';
        }
    } catch (err) { console.error('History error:', err); }
}

// inisialisasi saat halaman dimuat
async function init() {
    await fetchRealtime();
    await fetchPredictionAndControl();
    try {
        const res = await fetch('/api/fan/status');
        const data = await res.json();
        if (data.mode) {
            currentMode = data.mode;
            updateModeButtons();
        }
    } catch(e) {}
    setInterval(fetchRealtime, 2000);
    setInterval(fetchPredictionAndControl, 10000);
}
init();