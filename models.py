# models.py - Definisi tabel database SQLite

from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

os.makedirs("data", exist_ok=True)

Base = declarative_base()

class SensorData(Base):
    __tablename__ = 'sensor_data'
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    humidity = Column(Float)
    temperature = Column(Float)
    air_quality = Column(Integer)

class FanMode(Base):
    __tablename__ = 'fan_mode'
    id = Column(Integer, primary_key=True)
    mode = Column(String, default='AUTO')

class ModelMetadata(Base):
    __tablename__ = 'model_metadata'
    id = Column(Integer, primary_key=True)
    trained_at = Column(DateTime)
    data_points = Column(Integer)
    hyperparams = Column(String)
    mae = Column(Float)
    rmse = Column(Float)
    r2 = Column(Float)

# engine dengan timeout agar database tidak terkunci
engine = create_engine(
    'sqlite:///data/smart_home.db',
    connect_args={'check_same_thread': False, 'timeout': 10}
)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)