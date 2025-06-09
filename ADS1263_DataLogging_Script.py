import time
import csv
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from ADS1263 import ADS1263
import RPi.GPIO as GPIO

# === CONFIG ===
VREF = 5.0
ADC_MAX = 0x7FFFFFFF
SHUNT_RESISTOR = 200.0
SAMPLE_INTERVAL = 0.5  # seconds
MAX_POINTS = 60

# Pressure Calibration
def voltage_to_pressure(v):
    return (v * 9.28125) - 21.785

# === Globals ===
adc = ADS1263()
data_queue = queue.Queue()
stop_flag = threading.Event()
csv_file = None
csv_writer = None
csv_filepath = ""
channel = 0
times, pressures = [], []
start_time = None

# === Tkinter GUI ===
def select_file():
    global csv_filepath
    csv_filepath = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
    file_label.config(text=csv_filepath if csv_filepath else "No file selected")

def start_logging():
    global csv_file, csv_writer, start_time, times, pressures, channel

    if not csv_filepath:
        messagebox.showerror("Error", "Please select a CSV file path.")
        return

    try:
        channel = int(channel_entry.get())
        assert 0 <= channel <= 9
    except:
        messagebox.showerror("Invalid Channel", "Enter a valid ADC channel number (0-9).")
        return

    try:
        if adc.ADS1263_init_ADC1('ADS1263_10SPS') == -1:
            raise RuntimeError("Failed to initialize ADS1263.")
        adc.ADS1263_SetMode(0)
    except Exception as e:
        messagebox.showerror("ADC Error", str(e))
        return

    csv_file = open(csv_filepath, mode='w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["Timestamp", "Voltage (V)", "Current (mA)", "Pressure (psi)"])

    times.clear()
    pressures.clear()
    start_time = time.time()
    stop_flag.clear()

    threading.Thread(target=adc_reader_thread, daemon=True).start()
    threading.Thread(target=plot_and_log_thread, daemon=True).start()

def stop_logging():
    stop_flag.set()
    adc.ADS1263_Exit()
    GPIO.cleanup()
    if csv_file:
        csv_file.close()
    root.quit()

# === ADC Reader Thread ===
def adc_reader_thread():
    while not stop_flag.is_set():
        try:
            raw = adc.ADS1263_GetChannalValue(channel)
            voltage = raw * VREF / ADC_MAX
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            current_ma = (voltage / SHUNT_RESISTOR) * 1000.0
            pressure = voltage_to_pressure(voltage)
            data_queue.put((time.time() - start_time, pressure, voltage, current_ma, pressure, timestamp))
        except Exception as e:
            print("ADC read error:", e)
        time.sleep(SAMPLE_INTERVAL)

# === Plot + Log Thread ===
def plot_and_log_thread():
    fig, ax = plt.subplots()
    line, = ax.plot([], [], lw=2)
    pressure_text = ax.text(0.02, 0.95, '', transform=ax.transAxes, fontsize=12,
                            verticalalignment='top', bbox=dict(facecolor='white', alpha=0.6))
    ax.set_ylim(-15, 16)
    ax.set_xlim(0, MAX_POINTS * SAMPLE_INTERVAL)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Pressure (psi)")
    ax.set_title(f"Live Pressure from Channel {channel}")
    ax.grid(True)

    def init():
        line.set_data([], [])
        pressure_text.set_text('')
        return line, pressure_text

    def update(frame):
        while not data_queue.empty():
            t, p, v, c, pr, ts = data_queue.get()
            times.append(t)
            pressures.append(p)
            csv_writer.writerow([ts, f"{v:.5f}", f"{c:.3f}", f"{pr:.2f}"])
            csv_file.flush()
        if len(times) > MAX_POINTS:
            del times[:-MAX_POINTS]
            del pressures[:-MAX_POINTS]
        line.set_data(times, pressures)
        pressure_text.set_text(f"Current Pressure: {pressures[-1]:.2f} psi" if pressures else '')
        ax.set_xlim(times[0] if times else 0, times[-1] if times else MAX_POINTS * SAMPLE_INTERVAL)
        return line, pressure_text

    ani = FuncAnimation(fig, update, init_func=init, interval=SAMPLE_INTERVAL * 1000, blit=True)
    plt.show()

# === GUI Init ===
root = tk.Tk()
root.title("Queued Pressure Logger")

tk.Label(root, text="CSV Output File:").pack(pady=5)
file_label = tk.Label(root, text="No file selected", fg="gray")
file_label.pack()
tk.Button(root, text="Select File", command=select_file).pack(pady=5)

tk.Label(root, text="ADC Channel (0–9):").pack()
channel_entry = tk.Entry(root)
channel_entry.insert(0, "0")
channel_entry.pack()

tk.Button(root, text="Start Logging", command=start_logging, bg="green", fg="white").pack(pady=10)
tk.Button(root, text="Stop & Exit", command=stop_logging, bg="red", fg="white").pack(pady=5)

root.mainloop()
