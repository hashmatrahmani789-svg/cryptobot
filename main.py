import threading
import time
import signal1
import signal2
import signal3
import signal4

if __name__ == "__main__":
    t1 = threading.Thread(target=signal1.run, daemon=True)
    t2 = threading.Thread(target=signal2.run, daemon=True)
    t3 = threading.Thread(target=signal3.run, daemon=True)
    t4 = threading.Thread(target=signal4.run, daemon=True)

    t1.start()
    t2.start()
    t3.start()
    t4.start()

    # Keep main thread alive forever
    while True:
        time.sleep(60)