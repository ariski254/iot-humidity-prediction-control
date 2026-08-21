# ga_lstm_model.py - Model GA-LSTM untuk prediksi kelembapan

import numpy as np
import random
import pickle
import os
import json
import traceback
from datetime import datetime
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras import backend as K
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from deap import base, creator, tools, algorithms
import warnings
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

# konfigurasi GA
POPULATION_SIZE = 15
GENERATIONS = 10
CXPB = 0.75
MUTPB = 0.15

# batas hyperparameter: [n_layers, units, dropout, lr, batch_size, n_steps]
BOUNDS = [(1, 2), (32, 128), (0.0, 0.4), (0.0005, 0.003), (16, 64), (5, 30)]

global_data_scaled = None
ga_history = []

# perbaiki nilai individu agar tetap dalam batas
def repair_individual(ind):
    ind[0] = int(round(max(BOUNDS[0][0], min(BOUNDS[0][1], ind[0]))))
    ind[1] = int(round(max(BOUNDS[1][0], min(BOUNDS[1][1], ind[1]))))
    ind[2] = float(max(BOUNDS[2][0], min(BOUNDS[2][1], ind[2])))
    ind[3] = float(max(BOUNDS[3][0], min(BOUNDS[3][1], ind[3])))
    ind[4] = int(round(max(BOUNDS[4][0], min(BOUNDS[4][1], ind[4]))))
    ind[5] = int(round(max(BOUNDS[5][0], min(BOUNDS[5][1], ind[5]))))
    return ind

# buat model LSTM berdasarkan hyperparameter
def create_lstm_model(n_layers, units, dropout_rate, learning_rate, n_steps, n_features=1):
    model = Sequential()
    if n_layers == 1:
        model.add(LSTM(units, input_shape=(n_steps, n_features), name='lstm_1'))
        if dropout_rate > 0:
            model.add(Dropout(dropout_rate, name='dropout_1'))
    else:
        model.add(LSTM(units, return_sequences=True, input_shape=(n_steps, n_features), name='lstm_1'))
        if dropout_rate > 0:
            model.add(Dropout(dropout_rate, name='dropout_1'))
        model.add(LSTM(units // 2, name='lstm_2'))
        if dropout_rate > 0:
            model.add(Dropout(dropout_rate, name='dropout_2'))
    model.add(Dense(1))
    model.compile(optimizer=Adam(learning_rate=learning_rate), loss='mse')
    return model

# bentuk pasangan X,y untuk supervised learning
def prepare_sequences(data, n_steps):
    X, y = [], []
    for i in range(n_steps, len(data)):
        X.append(data[i-n_steps:i])
        y.append(data[i])
    return np.array(X), np.array(y)

# fungsi fitness: evaluasi individu berdasarkan RMSE validasi
def evaluate_individual(individual):
    global global_data_scaled
    try:
        ind = repair_individual(individual[:])
        n_layers = int(ind[0])
        units = int(ind[1])
        dropout_rate = float(ind[2])
        lr = float(ind[3])
        batch_size = int(ind[4])
        n_steps = int(ind[5])

        data = global_data_scaled
        X, y = prepare_sequences(data, n_steps)
        if len(X) < 30:
            return (1000.0,)

        total = len(X)
        train_size = int(0.7 * total)
        val_size = int(0.15 * total)
        if total - train_size - val_size <= 0:
            if train_size > 1:
                train_size -= 1
            elif val_size > 1:
                val_size -= 1
            else:
                return (1000.0,)

        X_train = X[:train_size]
        y_train = y[:train_size]
        X_val = X[train_size:train_size+val_size]
        y_val = y[train_size:train_size+val_size]
        if len(X_train) == 0 or len(X_val) == 0:
            return (1000.0,)

        X_train = X_train.reshape(-1, n_steps, 1)
        X_val = X_val.reshape(-1, n_steps, 1)

        model = create_lstm_model(n_layers, units, dropout_rate, lr, n_steps)
        early_stop = EarlyStopping(monitor='val_loss', patience=3, restore_best_weights=True)
        model.fit(X_train, y_train, epochs=5, batch_size=batch_size,
                  validation_data=(X_val, y_val), callbacks=[early_stop], verbose=0)

        y_pred = model.predict(X_val, verbose=0).flatten()
        y_val = y_val.flatten()
        if len(y_val) == 0:
            del model
            K.clear_session()
            return (1000.0,)

        rmse = np.sqrt(mean_squared_error(y_val, y_pred))
        del model
        K.clear_session()
        return (rmse,)
    except Exception as e:
        print(f"Evaluasi gagal: {individual}, error: {e}")
        traceback.print_exc()
        K.clear_session()
        return (9999.0,)

# setup DEAP toolbox untuk GA
def setup_ga_toolbox():
    if hasattr(creator, "FitnessMin"):
        del creator.FitnessMin
        del creator.Individual
    creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
    creator.create("Individual", list, fitness=creator.FitnessMin)
    toolbox = base.Toolbox()
    toolbox.register("attr_n_layers", random.randint, BOUNDS[0][0], BOUNDS[0][1])
    toolbox.register("attr_units", random.randint, BOUNDS[1][0], BOUNDS[1][1])
    toolbox.register("attr_dropout", random.uniform, BOUNDS[2][0], BOUNDS[2][1])
    toolbox.register("attr_lr", random.uniform, BOUNDS[3][0], BOUNDS[3][1])
    toolbox.register("attr_batch", random.randint, BOUNDS[4][0], BOUNDS[4][1])
    toolbox.register("attr_steps", random.randint, BOUNDS[5][0], BOUNDS[5][1])
    toolbox.register("individual", tools.initCycle, creator.Individual,
                     (toolbox.attr_n_layers, toolbox.attr_units, toolbox.attr_dropout,
                      toolbox.attr_lr, toolbox.attr_batch, toolbox.attr_steps), n=1)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("mate", tools.cxTwoPoint)

    def mut_custom(ind, indpb):
        for i in range(len(ind)):
            if random.random() < indpb:
                if i == 0:
                    ind[i] = random.randint(BOUNDS[i][0], BOUNDS[i][1])
                elif i == 1:
                    ind[i] = random.randint(BOUNDS[i][0], BOUNDS[i][1])
                elif i == 2:
                    ind[i] = random.uniform(BOUNDS[i][0], BOUNDS[i][1])
                elif i == 3:
                    ind[i] = random.uniform(BOUNDS[i][0], BOUNDS[i][1])
                elif i == 4:
                    ind[i] = random.randint(BOUNDS[i][0], BOUNDS[i][1])
                elif i == 5:
                    ind[i] = random.randint(BOUNDS[i][0], BOUNDS[i][1])
        return ind,

    toolbox.register("mutate", mut_custom, indpb=0.15)
    toolbox.register("select", tools.selTournament, tournsize=3)
    toolbox.register("evaluate", evaluate_individual)
    return toolbox

# jalankan algoritma GA
def run_ga(data_scaled):
    global global_data_scaled, ga_history
    global_data_scaled = data_scaled
    ga_history = []
    toolbox = setup_ga_toolbox()
    pop = toolbox.population(n=POPULATION_SIZE)
    hof = tools.HallOfFame(1)
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("min", np.min)
    stats.register("avg", np.mean)
    stats.register("std", np.std)
    try:
        pop, log = algorithms.eaSimple(pop, toolbox, cxpb=CXPB, mutpb=MUTPB,
                                       ngen=GENERATIONS, stats=stats, halloffame=hof, verbose=True)
        ga_history = log
        best = hof[0]
        return {
            'n_layers': int(best[0]),
            'units': int(best[1]),
            'dropout': float(best[2]),
            'learning_rate': float(best[3]),
            'batch_size': int(best[4]),
            'n_steps': int(best[5]),
            'fitness': float(best.fitness.values[0])
        }
    except Exception as e:
        print(f"GA Error: {e}")
        traceback.print_exc()
        return {'n_layers': 1, 'units': 64, 'dropout': 0.2,
                'learning_rate': 0.001, 'batch_size': 32, 'n_steps': 15}

# kelas utama OptimizedLSTM
class OptimizedLSTM:
    def __init__(self, model_path="data/best_lstm.pkl"):
        self.model = None
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        self.n_steps = 15
        self.is_trained = False
        self.best_params = None
        self.model_path = model_path
        self.training_history = []
        self.test_metrics = None
        self.ga_history = None
        self.train_data = self.val_data = self.test_data = None
        self.keras_model_path = "data/best_model.keras"
        os.makedirs("data", exist_ok=True)
        self.load_model()

    def save_model(self):
        if self.model is not None and self.scaler is not None:
            try:
                os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
                self.model.save(self.keras_model_path)
                with open(self.model_path, 'wb') as f:
                    pickle.dump({
                        'scaler': self.scaler,
                        'n_steps': self.n_steps,
                        'best_params': self.best_params,
                        'training_history': self.training_history,
                        'test_metrics': self.test_metrics,
                        'last_trained': datetime.now().isoformat()
                    }, f)
                print("Model saved")
                return True
            except Exception as e:
                print(f"Save error: {e}")
        return False

    def load_model(self):
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    data = pickle.load(f)
                    self.scaler = data.get('scaler')
                    self.n_steps = data.get('n_steps', 15)
                    self.best_params = data.get('best_params')
                    self.training_history = data.get('training_history', [])
                    self.test_metrics = data.get('test_metrics')
                print("Metadata loaded")
            except Exception as e:
                print(f"Load metadata error: {e}")
                return False

            if os.path.exists(self.keras_model_path):
                try:
                    self.model = load_model(self.keras_model_path)
                    self.is_trained = True
                    print("Model loaded from data/best_model.keras")
                    return True
                except Exception as e:
                    print(f"Load model error: {e}")
                    self.model = None
                    self.is_trained = False
                    return False
            else:
                print("data/best_model.keras not found")
                self.model = None
                self.is_trained = False
                return False
        else:
            print("Metadata not found, model not trained")
            return False

    def write_metrics_to_json(self):
        if self.test_metrics is None:
            return
        metrics_path = "data/model_metrics.json"
        os.makedirs(os.path.dirname(metrics_path), exist_ok=True)
        data = {
            'mae': self.test_metrics.get('mae', 0),
            'rmse': self.test_metrics.get('rmse', 0),
            'r2': self.test_metrics.get('r2', 0),
            'data_points': self.test_metrics.get('n_samples', 0),
            'last_trained': datetime.now().isoformat(),
            'best_params': self.best_params
        }
        with open(metrics_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Metrik disimpan ke {metrics_path}")

    def train(self, humidity_series):
        if len(humidity_series) < 100:
            print(f"Data insufficient: {len(humidity_series)} < 100")
            return False

        n = len(humidity_series)
        train_end = int(0.70 * n)
        val_end = int(0.85 * n)
        train_data = humidity_series[:train_end]
        val_data = humidity_series[train_end:val_end]
        test_data = humidity_series[val_end:]
        self.train_data, self.val_data, self.test_data = train_data, val_data, test_data

        print(f"\nSplit data: Train={len(train_data)}, Val={len(val_data)}, Test={len(test_data)}")

        self.scaler.fit(train_data.reshape(-1, 1))
        train_scaled = self.scaler.transform(train_data.reshape(-1, 1)).flatten()
        val_scaled = self.scaler.transform(val_data.reshape(-1, 1)).flatten()
        test_scaled = self.scaler.transform(test_data.reshape(-1, 1)).flatten()

        ga_data_size = min(len(train_scaled), 5000)
        ga_data = train_scaled[-ga_data_size:]
        print(f"Gunakan {len(ga_data)} data terakhir train untuk GA")

        best_params = run_ga(ga_data)
        self.best_params = best_params
        self.n_steps = best_params['n_steps']
        self.ga_history = ga_history

        print(f"\nHasil GA: units={best_params['units']}, layers={best_params['n_layers']}, "
              f"dropout={best_params['dropout']:.3f}, lr={best_params['learning_rate']:.5f}, "
              f"batch={best_params['batch_size']}, window={best_params['n_steps']}")

        X_train, y_train = prepare_sequences(train_scaled, self.n_steps)
        X_val, y_val = prepare_sequences(val_scaled, self.n_steps)
        if len(X_train) < 50 or len(X_val) < 10:
            print("Data tidak cukup untuk training final")
            return False

        X_train = X_train.reshape(-1, self.n_steps, 1)
        X_val = X_val.reshape(-1, self.n_steps, 1)
        print(f"Final training: {len(X_train)} train, {len(X_val)} val")

        self.model = create_lstm_model(
            n_layers=best_params['n_layers'],
            units=best_params['units'],
            dropout_rate=best_params['dropout'],
            learning_rate=best_params['learning_rate'],
            n_steps=self.n_steps
        )
        early_stop = EarlyStopping(monitor='val_loss', patience=15, restore_best_weights=True)
        checkpoint = ModelCheckpoint(self.keras_model_path, save_best_only=True,
                                     monitor='val_loss', mode='min')
        reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5, min_lr=1e-5)

        history = self.model.fit(
            X_train, y_train, epochs=80, batch_size=best_params['batch_size'],
            validation_data=(X_val, y_val), callbacks=[early_stop, checkpoint, reduce_lr], verbose=1
        )
        self.training_history = history.history
        self.is_trained = True

        print("\nEvaluasi test set...")
        test_metrics = self.evaluate_on_scaled(test_scaled)
        if test_metrics:
            self.test_metrics = test_metrics
            self.write_metrics_to_json()
            print(f"  MAE={test_metrics['mae']:.4f}, RMSE={test_metrics['rmse']:.4f}, R2={test_metrics['r2']:.4f}")

        self.save_model()
        print("Training GA-LSTM selesai")
        return True

    def evaluate_on_scaled(self, scaled_series):
        if not self.is_trained or self.model is None:
            return None
        X, y = prepare_sequences(scaled_series, self.n_steps)
        if len(X) == 0:
            return None
        X = X.reshape(-1, self.n_steps, 1)
        y_pred_scaled = self.model.predict(X, verbose=0)
        y_pred = self.scaler.inverse_transform(y_pred_scaled).flatten()
        y_actual = self.scaler.inverse_transform(y.reshape(-1, 1)).flatten()
        mae = mean_absolute_error(y_actual, y_pred)
        mse = mean_squared_error(y_actual, y_pred)
        rmse = np.sqrt(mse)
        mape = np.mean(np.abs((y_actual - y_pred) / y_actual)) * 100
        ss_res = np.sum((y_actual - y_pred) ** 2)
        ss_tot = np.sum((y_actual - np.mean(y_actual)) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        return {
            'mae': round(mae, 4),
            'rmse': round(rmse, 4),
            'mse': round(mse, 4),
            'mape': round(mape, 2),
            'r2': round(r2, 4),
            'n_samples': len(y_actual),
            'predictions': y_pred.tolist(),
            'actual': y_actual.tolist()
        }

    # prediksi multi-step dengan loop sekali saja
    def predict_multi_step(self, humidity_series, steps=[1, 6, 12], interval_seconds=5):
        if not self.is_trained or self.model is None or len(humidity_series) < self.n_steps:
            return self._fallback_predict(humidity_series, steps, interval_seconds)

        def get_label(step):
            total_seconds = step * interval_seconds
            hours = total_seconds / 3600.0
            if hours.is_integer():
                return f"{int(hours)}h"
            else:
                return f"{hours:.1f}h"

        try:
            last_seq = humidity_series[-self.n_steps:]
            scaled_seq = self.scaler.transform(last_seq.reshape(-1, 1)).flatten()
            current_seq = scaled_seq.reshape(1, self.n_steps, 1)

            max_step = max(steps) if steps else 0
            all_predictions_scaled = []

            for _ in range(max_step):
                pred_scaled = self.model.predict(current_seq, verbose=0)[0, 0]
                all_predictions_scaled.append(pred_scaled)
                new_input = np.append(current_seq[0, 1:, 0], pred_scaled)
                current_seq = new_input.reshape(1, self.n_steps, 1)

            if all_predictions_scaled:
                all_predictions_scaled = np.array(all_predictions_scaled).reshape(-1, 1)
                all_predictions_actual = self.scaler.inverse_transform(all_predictions_scaled).flatten()
            else:
                all_predictions_actual = np.array([])

            predictions = {}
            for step in steps:
                if 0 < step <= len(all_predictions_actual):
                    val = float(all_predictions_actual[step - 1])
                    val = np.clip(val, 0, 100)
                    label = get_label(step)
                    predictions[label] = round(val, 2)
                else:
                    last_val = float(humidity_series[-1]) if len(humidity_series) > 0 else 55.0
                    predictions[get_label(step)] = round(np.clip(last_val, 0, 100), 2)
            return predictions

        except Exception as e:
            print(f"Predict error: {e}")
            traceback.print_exc()
            return self._fallback_predict(humidity_series, steps, interval_seconds)

    def _fallback_predict(self, humidity_series, steps, interval_seconds=5):
        if len(humidity_series) > 0:
            last_val = float(humidity_series[-1])
        else:
            last_val = 55.0
        last_val = round(np.clip(last_val, 0, 100), 2)

        predictions = {}
        for step in steps:
            total_sec = step * interval_seconds
            hours = total_sec / 3600.0
            if hours.is_integer():
                label = f"{int(hours)}h"
            else:
                label = f"{hours:.1f}h"
            predictions[label] = last_val
        return predictions

optimized_lstm = OptimizedLSTM()