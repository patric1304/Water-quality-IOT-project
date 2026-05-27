python3 -c "
import board, busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS1115(i2c)
ads.gain = 1
for i in range(4):
    ch = AnalogIn(ads, i)
    print(f'A{i}: {ch.voltage:.4f} V')
"