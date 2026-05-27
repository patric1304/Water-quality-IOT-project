#!/usr/bin/env python3
"""
Test script: TDS (SEN0244) + Turbidity (SEN0189) via ADS1115 + DS18B20 temperature
Run with: python3 test_sensors.py
"""

import time
import glob
import os

# -- ADS1115 via I2C ----------------------------------------------------------
# Requires: pip3 install adafruit-circuitpython-ads1x15
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

# -- DS18B20 via 1-Wire -------------------------------------------------------
# Requires: 1-Wire enabled in raspi-config  (Interface Options → 1-Wire)
# No extra Python library needed — reads from /sys/bus/w1


# -----------------------------------------------------------------------------
# DS18B20 helpers
# -----------------------------------------------------------------------------

def find_ds18b20():
    """Return the path to the first DS18B20 device file, or None."""
    base = "/sys/bus/w1/devices/"
    matches = glob.glob(base + "28-*/w1_slave")
    if not matches:
        return None
    return matches[0]


def read_temperature(device_file):
    """
    Read raw lines from the 1-Wire device file.
    Returns temperature in °C as float, or None on error.
    """
    try:
        with open(device_file, "r") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"  [temp] Could not read device file: {e}")
        return None

    # Line 1 ends with YES if CRC is OK
    if lines[0].strip()[-3:] != "YES":
        print("  [temp] CRC check failed — bad reading")
        return None

    # Line 2 contains "t=<value in thousandths of °C>"
    pos = lines[1].find("t=")
    if pos == -1:
        print("  [temp] Unexpected file format")
        return None

    temp_c = float(lines[1][pos + 2:]) / 1000.0
    return temp_c


# -----------------------------------------------------------------------------
# TDS helpers
# -----------------------------------------------------------------------------

# Calibration constants (adjust after calibration with known solution)
# SEN0244 uses a simple linear formula:  TDS (ppm) = voltage × K
# K ≈ 133.42 * V³ - 255.86 * V² + 857.39 * V  (from DFRobot datasheet)
# Temperature compensation coefficient
TEMP_COEFF = 0.02      # 2% per °C, standard for most solutions
REFERENCE_TEMP = 25.0  # °C


def voltage_to_tds(voltage_v, temperature_c=25.0):
    """
    Convert ADS1115 voltage to TDS value in ppm.
    Uses DFRobot SEN0244 formula with optional temperature compensation.

    Temperature compensation: normalise the reading to 25 °C so that
    results are comparable regardless of water temperature.
    """
    # Temperature compensation factor
    comp_factor = 1.0 + TEMP_COEFF * (temperature_c - REFERENCE_TEMP)
    comp_voltage = voltage_v / comp_factor

    # DFRobot cubic formula (voltage in V, result in ppm)
    tds_ppm = (133.42 * comp_voltage**3
               - 255.86 * comp_voltage**2
               + 857.39 * comp_voltage) * 0.5

    return max(tds_ppm, 0.0)   # clamp negatives (noise at very low voltage)


# -----------------------------------------------------------------------------
# Turbidity helpers
# -----------------------------------------------------------------------------

# SEN0189 output is 0-4.5V (5V powered), divided by 2 via 10kΩ/10kΩ divider
# So ADS1115 sees 0-2.25V. We multiply back by 2 to get the real sensor voltage.
# Turbidity (NTU) formula from DFRobot datasheet (based on real sensor voltage):
#   voltage > 4.2V → 0 NTU (clear water)
#   voltage < 2.5V → 3000 NTU (very turbid)
#   otherwise      → -1120.4 * V² + 5742.3 * V - 4352.9

VOLTAGE_DIVIDER_FACTOR = 2.0   # we used two equal resistors (10k/10k)


def voltage_to_turbidity(adc_voltage):
    """
    Convert ADS1115 voltage (after divider) to turbidity in NTU.
    Uses linear calibration based on two measured points:
      3.75V -> 5 NTU   (clear tap water)
      3.28V -> 500 NTU (brownish muddy water)
    Adjust these values after calibration with known NTU solutions.
    """
    real_voltage = adc_voltage * VOLTAGE_DIVIDER_FACTOR

    # Calibration points
    v_clear, ntu_clear = 3.75, 5.0
    v_muddy, ntu_muddy = 3.28, 500.0

    # Linear interpolation
    slope = (ntu_muddy - ntu_clear) / (v_muddy - v_clear)
    ntu = ntu_clear + slope * (real_voltage - v_clear)

    return max(round(ntu, 1), 0.0)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("  Water sensor test — TDS + Turbidity + Temp")
    print("=" * 50)

    # -- Set up ADS1115 -------------------------------
    print("\n[1] Initialising ADS1115 over I2C ...")
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS1115(i2c)              # default address 0x48 (ADDR pin → GND)
        ads.gain = 1                    # ±4.096 V range — safe for 0-3.3 V signal
        tds_channel        = AnalogIn(ads, 0)  # A0
        turbidity_channel  = AnalogIn(ads, 1)  # A1
        print("  ADS1115 found  OK")
    except Exception as e:
        print(f"  ADS1115 init failed: {e}")
        print("  Check: I2C enabled? (raspi-config → Interface Options → I2C)")
        print("  Check: SDA→GPIO2, SCL→GPIO3, VDD→3.3V, GND→GND, ADDR→GND")
        return

    # -- Find DS18B20 ---------------------------------
    print("\n[2] Looking for DS18B20 on 1-Wire bus ...")
    device_file = find_ds18b20()
    if device_file:
        print(f"  Sensor found: {device_file}  OK")
    else:
        print("  No DS18B20 found.")
        print("  Check: 1-Wire enabled? (raspi-config → Interface Options → 1-Wire)")
        print("  Check: DATA→GPIO4, VCC→3.3V, GND→GND, 10kΩ between DATA and 3.3V")
        device_file = None

    # -- Continuous reading loop -----------------------
    print("\nReading every 2 seconds. Press Ctrl+C to stop.\n")
    print(f"{'Time':>8}  {'Temp (°C)':>10}  {'TDS (ppm)':>10}  {'Turbidity (NTU)':>16}")
    print("-" * 60)

    try:
        while True:
            timestamp = time.strftime("%H:%M:%S")

            # Temperature
            if device_file:
                temp_c = read_temperature(device_file)
                temp_str = f"{temp_c:8.2f} °C" if temp_c is not None else "  ERROR   "
            else:
                temp_c = 25.0
                temp_str = "  N/A    "

            # TDS
            try:
                tds_voltage = tds_channel.voltage
                tds_ppm = voltage_to_tds(tds_voltage, temp_c if temp_c else 25.0)
                tds_str = f"{tds_ppm:8.1f} ppm"
            except Exception:
                tds_str = "  ERROR  "

            # Turbidity
            try:
                turb_voltage = turbidity_channel.voltage
                ntu = voltage_to_turbidity(turb_voltage)
                turb_str = f"{ntu:10.1f} NTU"
            except Exception:
                turb_str = "  ERROR  "

            print(f"{timestamp}  {temp_str}  {tds_str}  {turb_str}")
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()