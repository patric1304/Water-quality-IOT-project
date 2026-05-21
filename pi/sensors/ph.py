"""
sensors/ph.py
-------------
Reads the pH sensor from ADS1115 channel A0 and converts the raw voltage
to a pH value using the two-point calibration coefficients stored in config.py.

Calibration must be run (calibrate_ph.py) before this module produces
meaningful values. If calibration constants are missing from config.py,
the module raises a clear error rather than silently returning garbage.
"""

import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn


def _load_calibration():
    """
    Load pH calibration constants from config.py.
    Raises RuntimeError with a helpful message if they are missing.
    """
    try:
        import config
        v7 = config.PH_VOLTAGE_AT_7
        v4 = config.PH_VOLTAGE_AT_4
    except AttributeError:
        raise RuntimeError(
            "pH calibration constants not found in config.py.\n"
            "Run calibrate_ph.py first to perform a two-point calibration."
        )
    except ModuleNotFoundError:
        raise RuntimeError(
            "config.py not found. Copy config.example.py to config.py "
            "and run calibrate_ph.py to fill in the calibration values."
        )
    return v7, v4


def _voltage_to_ph(voltage: float, v7: float, v4: float) -> float:
    """
    Convert a sensor voltage to pH using two-point linear interpolation.

    The formula maps voltage linearly between the two calibration points:
      - v7 is the voltage that corresponds to pH 7.0
      - v4 is the voltage that corresponds to pH 4.0

    For most pH sensors, voltage increases as pH decreases (acidic),
    so v4 > v7. The formula handles both directions correctly.

    Args:
        voltage: measured voltage from the sensor (volts)
        v7:      calibration voltage at pH 7.0
        v4:      calibration voltage at pH 4.0

    Returns:
        pH value as a float, clamped to the 0–14 range
    """
    if abs(v7 - v4) < 1e-6:
        raise ValueError("Calibration points are too close together — recalibrate.")

    m = (7.0 - 4.0) / (v7 - v4)
    b = 7.0 - m * v7
    ph = m * voltage + b

    # Clamp to physically meaningful range
    return max(0.0, min(14.0, ph))


class PHSensor:
    """
    Manages the pH sensor connected to ADS1115 channel A0.

    Usage:
        sensor = PHSensor()
        ph_value = sensor.read()
    """

    def __init__(self, samples: int = 10):
        """
        Initialise I2C bus, ADS1115, and load calibration constants.

        Args:
            samples: number of voltage readings to average per measurement.
                     More samples = smoother result, slightly slower read.
                     10 samples at default delay ≈ 0.5 seconds per reading.
        """
        self.samples = samples
        self._v7, self._v4 = _load_calibration()

        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        ads.gain = 1   # ±4.096V — do not change; calibration assumes this gain
        self._channel = AnalogIn(ads, ADS.P0)

    def _read_voltage(self) -> float:
        """
        Read the sensor voltage multiple times and return the average.
        Averaging reduces noise from the analog signal and ADC.
        """
        readings = []
        for _ in range(self.samples):
            readings.append(self._channel.voltage)
            time.sleep(0.05)
        return sum(readings) / len(readings)

    def read(self) -> float:
        """
        Return the current pH reading.

        Returns:
            pH as a float (0.0 – 14.0), or None if reading fails.
        """
        try:
            voltage = self._read_voltage()
            return _voltage_to_ph(voltage, self._v7, self._v4)
        except Exception as e:
            print(f"[pH sensor] Read error: {e}")
            return None

    def read_raw_voltage(self) -> float:
        """
        Return the raw voltage without converting to pH.
        Useful during calibration or debugging.
        """
        return self._read_voltage()
