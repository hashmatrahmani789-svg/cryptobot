import threading
import time
import importlib

# Import signals by their new names
ema_vol   = importlib.import_module("1H_EMA_VOL")
import signal2
import signal3
import signal4
import signal5
import signal6
import signal7

if __name__ == "__main__":
    t1 = threading.Thread(target=ema_vol.run,   daemon=True)
    t2 = threading.Thread(target=signal2.run,   daemon=True)
    t3 = threading.Thread(target=signal3.run,   daemon=True)
    t4 = threading.Thread(target=signal4.run,   daemon=True)
    t5 = threading.Thread(target=signal5.run,   daemon=True)
    t6 = threading.Thread(target=signal6.run,   daemon=True)
    t7 = threading.Thread(target=signal7.run,   daemon=True)

    t1.start()
    t2.start()
    t3.start()
    t4.start()
    t5.start()
    t6.start()
    t7.start()

    while True:
        time.sleep(60)