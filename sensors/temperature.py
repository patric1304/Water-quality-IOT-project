"""
sensors/temperature.py
----------------------
Reads the DS18B20 waterproof temperature sensor via the 1-Wire protocol.

⚠  DS18B20 NOT CONNECTED — this module is currently disabled.
   The read() method returns None unconditionally.
   Search for "# DS18B20:" in this file to find lines to uncomment
   when the sensor is physically wired.

Wiring (when you add the sensor):
  DS18B20 red wire   → 3.3V (Pi pin 1)
  DS18B20 black wire → GND  (Pi pin 6)
  DS18B20 yellow wire → GPIO4 (Pi pin 7)
  4.7kΩ pull-up resistor between yellow wire and 3.3V

Enable 1-Wire on the Pi (one-time setup):
  sudo raspi-config → Interface Options → 1-Wire → Enable
  OR add  dtoverlay=w1-gpio  to /boot/config.txt and reboot.

Required system package (install once):
  sudo apt-get install python3-w1thermsensor

Required Python package:
  pip3 install w1thermsensor
"""


# DS18B20: from w1thermsensor import W1ThermSensor, NoSensorFoundError


class TemperatureSensor:
    """
    Manages the DS18B20 temperature sensor via 1-Wire.

    When the sensor is not connected, read() returns None so the rest of
    the system can handle the missing value gracefully (e.g. TDS uses
    25 °C as a fallback temperature for compensation).

    Usage (once sensor is connected and uncommented):
        sensor = TemperatureSensor()
        temp = sensor.read()   # returns float in °C, or None
    """

    def __init__(self):
        """
        Initialise the 1-Wire sensor.
        Currently a no-op since DS18B20 is not connected.
        """
        # DS18B20: self._sensor = W1ThermSensor()
        pass

    def read(self) -> float:
        """
        Return the current water temperature in degrees Celsius.

        Returns:
            Temperature as a float (°C), or None if sensor is not connected
            or reading fails.
        """

        # ── DS18B20 disabled ─────────────────────────────────────────────────
        # Uncomment the block below when the DS18B20 is physically connected.
        # Delete or comment the  return None  line at the bottom of this block.
        #
        # DS18B20:
        # try:
        #     return self._sensor.get_temperature()
        # except NoSensorFoundError:
        #     print("[Temperature sensor] DS18B20 not found on 1-Wire bus.")
        #     print("  Check wiring and that 1-Wire is enabled in raspi-config.")
        #     return None
        # except Exception as e:
        #     print(f"[Temperature sensor] Read error: {e}")
        #     return None
        # ── end DS18B20 block ─────────────────────────────────────────────────

        return None   # DS18B20: remove this line when sensor is connected

    def is_connected(self) -> bool:
        """
        Check whether a DS18B20 is detected on the 1-Wire bus.

        Returns:
            True if sensor responds, False otherwise.
        """
        # DS18B20:
        # try:
        #     self._sensor.get_temperature()
        #     return True
        # except Exception:
        #     return False

        return False   # DS18B20: remove this line when sensor is connected
