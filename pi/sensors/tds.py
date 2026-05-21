"""
sensors/tds.py
--------------
Reads the TDS (Total Dissolved Solids) sensor from ADS1115 channel A1.
Converts the raw voltage to a TDS value in mg/L (ppm).

TDS is measured via electrical conductivity — the sensor passes a small
current through the water and measures how easily it flows. More dissolved
solids = higher conductivity = higher TDS reading.

Temperature compensation:
  Conductivity changes with temperature (~2% per °C). Without compensation,
  readings at temperatures other than 25 °C will be slightly inaccurate.
  If the temperature sensor is available, pass the current temperature to
  read(temperature=...). If not, 25 °C is assumed (compensation factor = 1.0).

WHO guideline for drinking water: TDS < 500 mg/L.
"""

import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

# Reference voltage of the ADS1115 at gain=1
VREF = 3.3

# Assumed temperature when no sensor is available
DEFAULT_TEMPERATURE_C = 25.0


def _voltage_to_tds(voltage: float, temperature_c: float) -> float:
    """
    Convert raw sensor voltage to TDS in mg/L with temperature compensation.

    The conversion follows the standard formula used by gravity-type TDS
    sensors (e.g. DFRobot TDS sensor):
      1. Convert voltage to raw conductivity value
      2. Apply temperature compensation
      3. Map to TDS in mg/L using the sensor's empirical coefficient

    Args:
        voltage:       measured voltage from the sensor (volts)
        temperature_c: water temperature in Celsius for compensation

    Returns:
        TDS in mg/L as a float, or 0.0 if voltage is below noise floor
    """
    if voltage < 0.01:
        return 0.0

    # Temperature compensation coefficient
    compensation = 1.0 + 0.02 * (temperature_c - 25.0)

    # Compensated voltage
    compensated_voltage = voltage / compensation

    # Empirical formula for this class of TDS sensor (gravity-type, 3.3V supply)
    # Produces TDS in mg/L (ppm)
    tds = (
        133.42 * compensated_voltage ** 3
        - 255.86 * compensated_voltage ** 2
        + 857.39 * compensated_voltage
    ) * 0.5

    return max(0.0, tds)


class TDSSensor:
    """
    Manages the TDS sensor connected to ADS1115 channel A1.

    Usage:
        sensor = TDSSensor()
        tds_value = sensor.read()                       # assumes 25 °C
        tds_value = sensor.read(temperature=22.5)       # with compensation
    """

    def __init__(self, samples: int = 10):
        """
        Initialise I2C bus, ADS1115 channel A1.

        Args:
            samples: number of voltage readings to average per measurement.
        """
        self.samples = samples

        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        ads.gain = 1   # ±4.096V range
        self._channel = AnalogIn(ads, ADS.P0)   # TDS on channel A0

    def _read_voltage(self) -> float:
        """Read and average multiple voltage samples to reduce noise."""
        readings = []
        for _ in range(self.samples):
            readings.append(self._channel.voltage)
            time.sleep(0.05)
        return sum(readings) / len(readings)

    def read(self, temperature: float = DEFAULT_TEMPERATURE_C) -> float:
        """
        Return the current TDS reading in mg/L.

        Args:
            temperature: current water temperature in Celsius.
                         Pass the value from the temperature sensor if available.
                         Defaults to 25.0 °C (no compensation error at exactly 25).

        Returns:
            TDS in mg/L as a float, or None if reading fails.
        """
        try:
            voltage = self._read_voltage()
            return _voltage_to_tds(voltage, temperature)
        except Exception as e:
            print(f"[TDS sensor] Read error: {e}")
            return None

    def read_raw_voltage(self) -> float:
        """Return the raw voltage without conversion. Useful for debugging."""
        return self._read_voltage()
