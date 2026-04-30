class PIDController:
    def __init__(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        # Tu budú premenné pre integrálnu a derivačnú zložku

    def compute(self, current_temp, setpoint):
        # Tu bude výpočet PWM hodnoty
        return 0