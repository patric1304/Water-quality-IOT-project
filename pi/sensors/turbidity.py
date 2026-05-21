"""
sensors/turbidity.py
--------------------
Reads the turbidity sensor from ADS1115 channel A2.
Converts the raw voltage to turbidity in NTU (Nephelometric Turbidity Units).

How turbidity sensing works:
  The sensor shines an infrared LED through the water. A photodetector measures
  how much light is scattered by suspended particles. More particles = more
  scattering = more scattered light detected = LOWER output voltage.

  This inverse relationship means:
    - Clear water  → high voltage (close to supply voltage)
    - Cloudy water → lower voltage

WHO guideline for drinking water: turbidity < 4 NTU (ideally < 1 NTU).
"""

import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn


def _voltage_to_ntu(voltage: float) -> float:
    """
    Convert sensor voltage to NTU.

    The conversion is based on the empirical curve published for gravity-type
    turbidity sensors (e.g. DFRobot SEN0189). The curve is approximately
    linear in the low-turbidity range and flattens at high turbidity.

    For voltages above ~4.2V (very clear water), NTU is effectively 0.
    For voltages below ~2.5V, the sensor is saturated (very turbid).

    Args:
        voltage: measured voltage from the sensor (volts)

    Returns:
        Turbidity in NTU as a float (≥ 0.0)
    """
    if voltage >= 4.2:
        return 0.0
    if voltage <= 2.5:
        # Sensor saturated — water is very turbid; return a high indicative value
        return 3000.0

    # Quadratic fit to the sensor's voltage-NTU curve (empirical)
    ntu = (
        -1120.4 * voltage ** 2
        + 5742.3 * voltage
        - 4352.9
    )

    return max(0.0, ntu)


class TurbiditySensor:
    """
    Manages the turbidity sensor connected to ADS1115 channel A2.

    Usage:
        sensor = TurbiditySensor()
        ntu_value = sensor.read()
    """

    def __init__(self, samples: int = 10):
        """
        Initialise I2C bus, ADS1115 channel A2.

        Args:
            samples: number of voltage readings to average per measurement.
        """
        self.samples = samples

        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        ads.gain = 1   # ±4.096V range
        self._channel = AnalogIn(ads, ADS.P1)   # Turbidity on channel A1

    def _read_voltage(self) -> float:
        """Read and average multiple voltage samples to reduce noise."""
        readings = []
        for _ in range(self.samples):
            readings.append(self._channel.voltage)
            time.sleep(0.05)
        return sum(readings) / len(readings)

    def read(self) -> float:
        """
        Return the current turbidity reading in NTU.

        Returns:
            Turbidity in NTU as a float (0.0 = perfectly clear), or None on error.
        """
        try:
            voltage = self._read_voltage()
            return _voltage_to_ntu(voltage)
        except Exception as e:
            print(f"[Turbidity sensor] Read error: {e}")
            return None

    def read_raw_voltage(self) -> float:
        """Return the raw voltage without conversion. Useful for debugging."""
        return self._read_voltage()
