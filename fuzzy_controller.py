# fuzzy_controller.py - Logika fuzzy untuk kontrol kipas

import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl

class FuzzyFanController:
    def __init__(self, target_humidity=55):
        self.target = target_humidity

        # variabel input
        self.error = ctrl.Antecedent(np.arange(-30, 31, 1), 'error')
        self.delta = ctrl.Antecedent(np.arange(-10, 11, 1), 'delta')
        self.pred_h = ctrl.Antecedent(np.arange(0, 101, 1), 'pred_h')
        # variabel output
        self.speed = ctrl.Consequent(np.arange(0, 101, 1), 'speed')

        # fungsi keanggotaan error
        self.error['NB'] = fuzz.trimf(self.error.universe, [-30, -20, -10])
        self.error['NS'] = fuzz.trimf(self.error.universe, [-15, -7, 0])
        self.error['Z'] = fuzz.trimf(self.error.universe, [-5, 0, 5])
        self.error['PS'] = fuzz.trimf(self.error.universe, [0, 7, 15])
        self.error['PB'] = fuzz.trimf(self.error.universe, [10, 20, 30])

        # fungsi keanggotaan delta
        self.delta['N'] = fuzz.trimf(self.delta.universe, [-10, -5, 0])
        self.delta['Z'] = fuzz.trimf(self.delta.universe, [-2, 0, 2])
        self.delta['P'] = fuzz.trimf(self.delta.universe, [0, 5, 10])

        # fungsi keanggotaan prediksi
        self.pred_h['Low'] = fuzz.trimf(self.pred_h.universe, [0, 30, 50])
        self.pred_h['Normal'] = fuzz.trimf(self.pred_h.universe, [40, 55, 70])
        self.pred_h['High'] = fuzz.trimf(self.pred_h.universe, [60, 80, 100])

        # fungsi keanggotaan speed
        self.speed['Stop'] = fuzz.trimf(self.speed.universe, [0, 0, 20])
        self.speed['Slow'] = fuzz.trimf(self.speed.universe, [15, 35, 55])
        self.speed['Medium'] = fuzz.trimf(self.speed.universe, [45, 65, 85])
        self.speed['Fast'] = fuzz.trimf(self.speed.universe, [75, 95, 100])

        # aturan fuzzy
        rule1 = ctrl.Rule(self.error['NB'] | self.pred_h['High'], self.speed['Fast'])
        rule2 = ctrl.Rule(self.error['NS'] & self.pred_h['Normal'], self.speed['Medium'])
        rule3 = ctrl.Rule(self.error['Z'] & self.delta['Z'], self.speed['Stop'])
        rule4 = ctrl.Rule(self.error['Z'] & self.pred_h['High'], self.speed['Medium'])
        rule5 = ctrl.Rule(self.error['PS'] | self.error['PB'], self.speed['Stop'])
        rule6 = ctrl.Rule(self.delta['P'] & self.error['NS'], self.speed['Slow'])
        rule7 = ctrl.Rule(self.pred_h['High'] & (self.error['Z'] | self.error['NS']), self.speed['Fast'])

        self.control_system = ctrl.ControlSystem([rule1, rule2, rule3, rule4, rule5, rule6, rule7])
        self.simulator = ctrl.ControlSystemSimulation(self.control_system)

    def compute_speed(self, current_humidity, previous_error, predicted_humidity_1h):
        error = self.target - current_humidity
        delta_error = error - previous_error

        # batasi nilai agar sesuai domain
        error = np.clip(error, -30, 30)
        delta_error = np.clip(delta_error, -10, 10)
        pred_h = np.clip(predicted_humidity_1h, 0, 100)

        self.simulator.input['error'] = error
        self.simulator.input['delta'] = delta_error
        self.simulator.input['pred_h'] = pred_h

        try:
            self.simulator.compute()
            speed = self.simulator.output['speed']
            return int(np.clip(speed, 0, 100))
        except:
            return 50

fuzzy_controller = FuzzyFanController(target_humidity=55)