# app.py - Server FastAPI untuk smart home dengan auto-training dan scheduler

from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc
from datetime import datetime
import numpy as np
import os
import json
import logging
import threading
import traceback
from typing import Optional
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# konfigurasi logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from models import SessionLocal, SensorData, FanMode
from fuzzy_controller import fuzzy_controller
from ga_lstm_model import optimized_lstm

# inisialisasi aplikasi FastAPI
app = FastAPI(title="Smart Home AI - Realtime Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# buat folder untuk static dan template
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# interval pengiriman data dari ESP32 (detik) - harus sama dengan ESP32
INTERVAL_SEC = 5

# inisialisasi mode fan di database
db = SessionLocal()
if db.query(FanMode).count() == 0:
    db.add(FanMode(mode='AUTO'))
    db.commit()
db.close()

last_error = 0.0
is_training = False

class SensorPayload(BaseModel):
    humidity: float
    temperature: float = 0.0
    air_quality: int = 0
    timestamp: Optional[str] = None

# fungsi untuk menjalankan pelatihan ulang model
def run_auto_training():
    global is_training
    if is_training:
        logger.info("Training sudah berjalan, lewati.")
        return
    if optimized_lstm.is_trained:
        logger.info("Model sudah terlatih, lewati.")
        return

    try:
        is_training = True
        db = SessionLocal()
        count = db.query(SensorData).count()
        if count < 100:
            logger.info(f"Data {count} < 100, training dilewati.")
            db.close()
            return
        records = db.query(SensorData).order_by(SensorData.timestamp).all()
        db.close()

        if len(records) < 100:
            logger.info("Data tidak cukup untuk training")
            return

        logger.info(f"Memulai training dengan {len(records)} data...")
        humidity_series = np.array([r.humidity for r in records])
        success = optimized_lstm.train(humidity_series)
        if success:
            logger.info("Auto-training berhasil")
        else:
            logger.error("Auto-training gagal")
    except Exception as e:
        logger.error(f"Error training: {e}")
        traceback.print_exc()
    finally:
        is_training = False

# cek kondisi dan panggil training jika diperlukan
def check_and_train():
    if optimized_lstm.is_trained or is_training:
        return
    db = SessionLocal()
    count = db.query(SensorData).count()
    db.close()
    if count >= 100 and count % 50 == 0:
        thread = threading.Thread(target=run_auto_training)
        thread.start()

# fungsi untuk memicu training secara manual
async def trigger_training():
    if is_training:
        return {"status": "Training already running"}
    if optimized_lstm.is_trained:
        return {"status": "Model already trained"}
    thread = threading.Thread(target=run_auto_training)
    thread.start()
    return {"status": "Training started in background"}

@app.post("/api/train")
async def trigger_training_post():
    return await trigger_training()

@app.get("/api/train")
async def trigger_training_get():
    return await trigger_training()

# scheduler periodik setiap 6 jam
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=run_auto_training,
        trigger=IntervalTrigger(hours=6),
        id='auto_training_job',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler berjalan: auto-training setiap 6 jam")

# helper untuk mengambil dan menyimpan mode fan
def get_fan_mode():
    db = SessionLocal()
    mode_obj = db.query(FanMode).first()
    mode = mode_obj.mode if mode_obj else 'AUTO'
    db.close()
    return mode

def set_fan_mode(mode: str):
    if mode not in ['AUTO', 'ON', 'OFF']:
        return False
    db = SessionLocal()
    mode_obj = db.query(FanMode).first()
    if mode_obj:
        mode_obj.mode = mode
    else:
        db.add(FanMode(mode=mode))
    db.commit()
    db.close()
    logger.info(f"Fan mode berubah menjadi {mode}")
    return True

# endpoint untuk menerima data dari ESP32
@app.post("/data")
async def receive_data(payload: SensorPayload):
    try:
        hum = payload.humidity
        if hum is None or not (0 <= hum <= 100):
            return {"status": "ignored"}
        db = SessionLocal()
        new_data = SensorData(
            timestamp=datetime.utcnow(),
            humidity=float(hum),
            temperature=float(payload.temperature),
            air_quality=int(payload.air_quality)
        )
        db.add(new_data)
        db.commit()
        logger.info(f"Data tersimpan: H={hum}%, T={payload.temperature}C")
        db.close()
        check_and_train()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"status": "error"}

# endpoint uji coba
@app.get("/api/test")
async def test():
    return {"status": "ok", "time": datetime.now().isoformat()}

# endpoint data terbaru
@app.get("/api/latest")
async def get_latest():
    db = SessionLocal()
    latest = db.query(SensorData).order_by(desc(SensorData.timestamp)).first()
    db.close()
    if latest:
        return {
            "humidity": round(latest.humidity, 1),
            "temperature": round(latest.temperature, 1),
            "air_quality": latest.air_quality,
            "timestamp": latest.timestamp.isoformat()
        }
    return {"humidity": 0, "temperature": 0, "air_quality": 0}

# endpoint prediksi multi-step
@app.get("/api/predict")
async def get_predictions():
    db = SessionLocal()
    records = db.query(SensorData).order_by(desc(SensorData.timestamp)).limit(200).all()
    db.close()
    if len(records) < 10:
        return {
            "predictions": {"1h": 55.0, "6h": 55.0, "12h": 55.0},
            "model_trained": optimized_lstm.is_trained
        }
    records = records[::-1]
    humidity_series = np.array([r.humidity for r in records])
    current_h = humidity_series[-1]

    steps_hours = [1, 6, 12]
    steps_in_samples = [h * 3600 // INTERVAL_SEC for h in steps_hours]

    predictions = optimized_lstm.predict_multi_step(
        humidity_series,
        steps=steps_in_samples,
        interval_seconds=INTERVAL_SEC
    )

    formatted_predictions = {
        "1h": predictions.get("1h", round(current_h, 1)),
        "6h": predictions.get("6h", round(current_h, 1)),
        "12h": predictions.get("12h", round(current_h, 1))
    }
    return {
        "predictions": formatted_predictions,
        "current_humidity": round(current_h, 1),
        "model_trained": optimized_lstm.is_trained
    }

# endpoint kontrol untuk ESP32 (dengan feedforward prediksi 1 jam)
@app.get("/api/control")
async def get_fan_speed(current_humidity: float = 55.0):
    global last_error
    mode = get_fan_mode()
    logger.info(f"Control request: humidity={current_humidity}, mode={mode}")

    if mode == "ON":
        speed = 100
    elif mode == "OFF":
        speed = 0
    else:
        # ambil prediksi 1 jam dari database sebagai feedforward
        predicted_1h = current_humidity
        try:
            db = SessionLocal()
            records = db.query(SensorData).order_by(desc(SensorData.timestamp)).limit(200).all()
            db.close()

            if len(records) >= 20:
                records = records[::-1]
                humidity_series = np.array([r.humidity for r in records])
                steps_1h = 1 * 3600 // INTERVAL_SEC
                pred_result = optimized_lstm.predict_multi_step(
                    humidity_series,
                    steps=[steps_1h],
                    interval_seconds=INTERVAL_SEC
                )
                predicted_1h = pred_result.get("1h", current_humidity)
                logger.info(f"Prediksi 1h dari server: {predicted_1h}")
        except Exception as e:
            logger.error(f"Gagal ambil prediksi untuk FLC: {e}")
            predicted_1h = current_humidity

        prev_error = last_error
        speed = fuzzy_controller.compute_speed(current_humidity, prev_error, predicted_1h)
        last_error = fuzzy_controller.target - current_humidity
        logger.info(f"FLC output speed: {speed}%")

    return {"fan_speed": speed, "mode": mode}

# endpoint status fan
@app.get("/api/fan/status")
async def fan_status():
    return {"mode": get_fan_mode()}

# endpoint toggle mode fan
@app.get("/api/fan/toggle/{mode}")
async def toggle_fan(mode: str):
    if mode in ["AUTO", "ON", "OFF"]:
        set_fan_mode(mode)
        return {"status": "success", "mode": mode}
    return {"status": "error"}

# endpoint riwayat data sensor
@app.get("/api/history")
async def get_history(limit: int = 50):
    db = SessionLocal()
    data = db.query(SensorData).order_by(desc(SensorData.timestamp)).limit(limit).all()
    data = data[::-1]
    result = {
        "timestamps": [d.timestamp.isoformat() for d in data],
        "humidity": [round(d.humidity, 1) for d in data],
        "temperature": [round(d.temperature, 1) for d in data],
        "air_quality": [d.air_quality for d in data]
    }
    db.close()
    return result

# endpoint status model
@app.get("/api/model-status")
async def model_status():
    return {
        "is_trained": optimized_lstm.is_trained,
        "best_params": optimized_lstm.best_params,
        "n_steps": optimized_lstm.n_steps
    }

# endpoint metrik model
@app.get("/api/model-metrics")
async def get_model_metrics():
    metrics_path = "data/model_metrics.json"
    if not os.path.exists(metrics_path):
        raise HTTPException(status_code=404, detail="Model metrics not found")
    try:
        with open(metrics_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error(f"Error reading metrics: {e}")
        raise HTTPException(status_code=500, detail="Error reading metrics file")

# halaman dashboard
@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# event saat server mulai
@app.on_event("startup")
def startup_event():
    start_scheduler()
    if not optimized_lstm.is_trained:
        db = SessionLocal()
        count = db.query(SensorData).count()
        db.close()
        if count >= 100:
            thread = threading.Thread(target=run_auto_training)
            thread.start()
    logger.info("Server startup selesai")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)