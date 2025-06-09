from smbus2 import SMBus, i2c_msg
import time

# Constants
BUS_NUM = 1
TCA_ADDR = 0x70
TCA_CHANNELS = [0, 1]  # Channel 0 = Valve 1, Channel 1 = Valve 2
TIC_ADDR = 0x0E
COMMAND_SET_TARGET_POSITION = 0xE0
COMMAND_GET_CURRENT_POSITION = 0x22
COMMAND_GET_ERROR_STATUS = 0x02

def select_tca_channel(bus, channel):
    bus.write_byte(TCA_ADDR, 1 << channel)

def set_target_position(bus, steps):
    data = [COMMAND_SET_TARGET_POSITION] + list(steps.to_bytes(4, byteorder='little', signed=True))
    bus.i2c_rdwr(i2c_msg.write(TIC_ADDR, data))

def get_current_position(bus):
    bus.write_byte(TIC_ADDR, COMMAND_GET_CURRENT_POSITION)
    read = i2c_msg.read(TIC_ADDR, 4)
    bus.i2c_rdwr(read)
    return int.from_bytes(bytes(read), 'little', signed=True)

def get_error_status(bus):
    bus.write_byte(TIC_ADDR, COMMAND_GET_ERROR_STATUS)
    read = i2c_msg.read(TIC_ADDR, 2)
    bus.i2c_rdwr(read)
    return int.from_bytes(bytes(read), 'little')

def move_valve(bus, channel, position_steps):
    print(f"\nActivating channel {channel}")
    select_tca_channel(bus, channel)
    time.sleep(0.1)

    print(f"  Moving to {position_steps} steps")
    set_target_position(bus, position_steps)
    time.sleep(2)

    pos = get_current_position(bus)
    err = get_error_status(bus)
    print(f"  Position: {pos}")
    print(f"  Error Status: {err}")

# Main
with SMBus(BUS_NUM) as bus:
    # Move both valves open
    for channel in TCA_CHANNELS:
        move_valve(bus, channel, -80)

    time.sleep(3)

    # Move both valves closed
    for channel in TCA_CHANNELS:
        move_valve(bus, channel, 0)

    print("\nAll valves cycled.")
