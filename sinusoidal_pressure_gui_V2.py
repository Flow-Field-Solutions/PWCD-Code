import time
import csv
import math
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from ADS1263 import ADS1263
from smbus2 import SMBus, i2c_msg
import RPi.GPIO as GPIO
import os

# ==== CONFIGURATION ====
I2C_BUS = 1
TCA_ADDRESS = 0x70
TIC_INLET_CHANNEL = 1
TIC_EXHAUST_CHANNEL = 0
TIC_COMMAND_SET_TARGET = 0xE0

INLET_STEP_SIZE = 20
EXHAUST_STEP_SIZE = 40
EXHAUST_DURATION = 5  # seconds
SAMPLE_INTERVAL = 0.2

# === Pressure Conversion ===
VREF = 5.0
ADC_MAX = 0x7FFFFFFF
SHUNT_RESISTOR = 200.0

def voltage_to_pressure(v):
    return (v * 9.28125) - 21.785

# === I2C Utilities ===
bus = SMBus(I2C_BUS)

def select_tca_channel(channel):
    if 0 <= channel <= 7:
        bus.write_byte(TCA_ADDRESS, 1 << channel)

def set_tic_target(channel, target):
    try:
        select_tca_channel(channel)
        time.sleep(0.05)  # Allow time for the channel switch
        target = int(target)
        data = [TIC_COMMAND_SET_TARGET] + list(target.to_bytes(4, byteorder='little', signed=True))
        msg = i2c_msg.write(0x0E, data)
        bus.i2c_rdwr(msg)
    except Exception as e:
        print(f"I2C Error on channel {channel} with target {target}: {e}")

# === Global Vars ===
adc = ADS1263()
data_log = []
stop_flag = threading.Event()
filepath = ""

# === GUI Setup ===
root = tk.Tk()
root.title("Sinusoidal Pressure Control")

file_label = tk.Label(root, text="No file selected", fg="gray")
file_label.pack()

def select_file():
    global filepath
    filepath = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    if filepath:
        file_label.config(text=os.path.basename(filepath))
    else:
        file_label.config(text="No file selected")

params = {}

for label in ["Min Pressure (psi)", "Max Pressure (psi)", "Period (s)", "Oscillations", "ADC Channel"]:
    tk.Label(root, text=label).pack()
    e = tk.Entry(root)
    e.pack()
    params[label] = e
params["ADC Channel"].insert(0, "0")

# === Logging and Plotting ===
times, pressures, targets = [], [], []
fig, ax = plt.subplots()
line_actual, = ax.plot([], [], label="Measured Pressure")
line_target, = ax.plot([], [], linestyle='--', label="Target Pressure")
pressure_text = ax.text(0.02, 0.95, '', transform=ax.transAxes, fontsize=12, verticalalignment='top', bbox=dict(facecolor='white', alpha=0.6))

ax.set_xlabel("Time (s)")
ax.set_ylabel("Pressure (psi)")
ax.set_title("Live Pressure vs. Target")
ax.legend()
ax.grid(True)

canvas = FigureCanvasTkAgg(fig, master=root)
canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

# === Control Thread ===
def control_loop(min_p, max_p, period, cycles, channel):
    global csv_file, csv_writer
    try:
        if adc.ADS1263_init_ADC1('ADS1263_10SPS') == -1:
            raise RuntimeError("Failed to initialize ADC")
        adc.ADS1263_SetMode(0)
    except Exception as e:
        messagebox.showerror("ADC Error", str(e))
        return

    print("Waiting 5 seconds before starting test...")
    for _ in range(25):
        if stop_flag.is_set():
            return
        try:
            raw = adc.ADS1263_GetChannalValue(channel)
            voltage = raw * VREF / ADC_MAX
            pressure = voltage_to_pressure(voltage)
            t = 0 if not times else times[-1] + SAMPLE_INTERVAL
            times.append(t)
            pressures.append(pressure)
            targets.append(0.0)
            csv_writer.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), round(t,2), 0.0, round(pressure,2), 0, 0])
            csv_file.flush()
            time.sleep(SAMPLE_INTERVAL)
        except Exception as e:
            print("Warm-up read failed:", e)
            time.sleep(SAMPLE_INTERVAL)

    print("Starting sinusoidal control...")
    start_time = time.time()
    duration = period * cycles
    range_p = (max_p - min_p) / 2
    mid_p = min_p + range_p  # Now min_p is the bottom of the sinusoid

    inlet_pos = 0
    exhaust_pos = 0

    try:
        csv_file = open(filepath, mode='w', newline='')
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["Timestamp", "Time (s)", "Target Pressure", "Actual Pressure", "Inlet Step", "Exhaust Step"])

        # Initial warm-up pressure sampling (already performed)
        for i in range(len(times)):
            csv_writer.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), round(times[i], 2), round(targets[i], 2), round(pressures[i], 2), 0, 0])
        csv_file.flush()
        csv_writer.writerow(["Timestamp", "Time (s)", "Target Pressure", "Actual Pressure", "Inlet Step", "Exhaust Step"])

        if adc.ADS1263_init_ADC1('ADS1263_10SPS') == -1:
            raise RuntimeError("Failed to initialize ADC")
        adc.ADS1263_SetMode(0)
    except Exception as e:
        messagebox.showerror("ADC Error", str(e))
        return

    while not stop_flag.is_set() and (time.time() - start_time) <= duration:
        t = time.time() - start_time
        target = mid_p + range_p * math.sin(2 * math.pi * t / period)  # Oscillates between min_p and max_p

        raw = adc.ADS1263_GetChannalValue(channel)
        voltage = raw * VREF / ADC_MAX
        pressure = voltage_to_pressure(voltage)

        error = target - pressure

        if error > 0.1:
            step_inlet = int(min(max(5, abs(error) * 200), 100))  # Scaled for 1/2 microstepping
            step_exhaust = int(min(max(5, abs(error) * 200), 100))
            inlet_pos = max(inlet_pos - step_inlet, -4000)
            set_tic_target(TIC_INLET_CHANNEL, inlet_pos)
            exhaust_pos = min(exhaust_pos + step_exhaust, 0)
            set_tic_target(TIC_EXHAUST_CHANNEL, exhaust_pos)
        elif error < -0.1:
            step_inlet = int(min(max(5, abs(error) * 200), 100))
            step_exhaust = int(min(max(5, abs(error) * 200), 100))
            exhaust_pos = max(exhaust_pos - step_exhaust, -4000)
            set_tic_target(TIC_EXHAUST_CHANNEL, exhaust_pos)
            inlet_pos = min(inlet_pos + step_inlet, 0)
            set_tic_target(TIC_INLET_CHANNEL, inlet_pos)

        times.append(t)
        pressures.append(pressure)
        targets.append(target)

        csv_writer.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), round(t,2), round(target,2), round(pressure,2), inlet_pos, exhaust_pos])
        csv_file.flush()

        time.sleep(SAMPLE_INTERVAL)

    run_shutdown_sequence()

# === Shutdown Logic ===
def run_shutdown_sequence():
    # Open exhaust fully
    set_tic_target(TIC_EXHAUST_CHANNEL, -4000)  # Fully open (max negative)
    time.sleep(EXHAUST_DURATION)
    # Close both valves
    set_tic_target(TIC_EXHAUST_CHANNEL, 0)
    set_tic_target(TIC_INLET_CHANNEL, 0)

    def finalize():
        try:
            if csv_file:
                csv_file.close()
            messagebox.showinfo("Test Complete", "Tank exhausted and valves closed. CSV saved.")
        except Exception as e:
            messagebox.showerror("File Error", f"Failed to save CSV: {e}")
        root.quit()

    root.after(0, finalize)

# === Start/Stop Handlers ===
def start_test():
    try:
        min_p = float(params["Min Pressure (psi)"].get())
        max_p = float(params["Max Pressure (psi)"].get())
        period = float(params["Period (s)"].get())
        cycles = int(params["Oscillations"].get())
        channel = int(params["ADC Channel"].get())
    except ValueError:
        messagebox.showerror("Input Error", "Please enter valid numeric parameters.")
        return

    if not filepath:
        messagebox.showerror("File Error", "Please select an output CSV file.")
        return

    stop_flag.clear()
    threading.Thread(target=control_loop, args=(min_p, max_p, period, cycles, channel), daemon=True).start()
    update_plot()

def stop_test():
    stop_flag.set()

# === Embedded Plot Update ===
def update_plot():
    if times:
        line_actual.set_data(times, pressures)
        line_target.set_data(times, targets)
        pressure_text.set_text(f"Current: {pressures[-1]:.2f} psi\nTarget: {targets[-1]:.2f} psi")
        ax.set_xlim(max(0, times[-1] - 60), times[-1] + 5)
        ax.set_ylim(min(min(pressures[-60:], default=-15), min(targets[-60:], default=-15)) - 1,
                    max(max(pressures[-60:], default=15), max(targets[-60:], default=15)) + 1)
    canvas.draw()
    if not stop_flag.is_set():
        root.after(200, update_plot)

# === GUI Buttons ===
tk.Button(root, text="Select CSV Output", command=select_file).pack(pady=5)
tk.Button(root, text="Start Test", command=start_test, bg="green", fg="white").pack(pady=10)
tk.Button(root, text="Stop & Exhaust", command=stop_test, bg="red", fg="white").pack(pady=5)

root.mainloop()
