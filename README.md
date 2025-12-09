## Running Tests

### Configuration

Edit `config.yaml` to configure I2C parameters:

```yaml
i2c:
  bus: 0                              # I2C bus number
  device_address: 0x30                # Target device address
  read_buffer_size: 1000              # Buffer size for reads
  irq_pin: 26                         # GPIO pin for interrupts
  library: "./build/libi2c_lib.so"    # Path to compiled library
```

### Run the Test

The test script is designed for pytest execution only. Run the I2C communication test:

```bash
pytest tmain.py::test_app -v
```

**For more verbose output:**
```bash
pytest tmain.py::test_app -v -s
```

The test will:
- Initialize I2C communication with configured parameters
- Read sensor data frames
- Validate data integrity using Fletcher checksums
- Process up to 10 frames or run for 30 seconds maximum
- Display frame information and raw data

## Library APIs

### C++ API (i2c_adapter.h)

The main C++ class `I2CDevice` provides:

- **Constructor:** `I2CDevice(adapter_number, device_address)`
- **Constructor with IRQ:** `I2CDevice(adapter_number, device_address, irq_pin)`
- **Read/Write with page/address:** `read_data()`, `write_data()`
- **Direct device I/O:** `read_from_device()`, `write_to_device()`
- **Interrupt handling:** `read_device_interrupt()`, `write_device_interrupt()`, `clear_device_interrupt()`

### Pure C API (i2c_pure_c.h)

For Python ctypes integration:

- **Device management:** `i2c_device_create()`, `i2c_device_destroy()`
- **I/O operations:** `i2c_read_data()`, `i2c_write_data()`
- **Direct operations:** `i2c_read_from_device()`, `i2c_write_to_device()`
- **Interrupt handling:** `i2c_read_device_interrupt()`, `i2c_write_device_interrupt()`

## Python Usage Example

```python
from ctypes import *
from driver.i2c import I2C

# Method 1: Using the I2C Python wrapper class
ser = I2C(
    bus=0,
    device_address=0x30,
    read_buffer_size=1000,
    irq_pin=26,
    library_name="./build/libi2c_lib.so"
)

# Read data
data = ser.read(10)  # Read 10 bytes

# Method 2: Direct ctypes usage
lib = CDLL("./build/libi2c_lib.so")
device = lib.i2c_device_create(1, 0x30)
read_buffer = (c_uint8 * 1000)()
read_count = lib.i2c_read_from_device(device, read_buffer, 1000)
lib.i2c_device_destroy(device)
```

## File Structure

```
├── rbuild                        # Build script (use this to build the library)
├── config.yaml                   # Test configuration
├── tmain.py                      # Main test script
├── conftest.py                   # pytest configuration
├── CMakeLists.txt                # CMake build configuration
├── toolchain-arm.cmake           # ARM cross-compilation toolchain
├── build/                        # Build output directory
│   └── libi2c_lib.so            # Compiled shared library
└── driver/
    ├── i2c.py                    # Python I2C wrapper class
    └── i2c_adapter/
        └── rpi_i2c/
            ├── i2c_adapter.{h,cc}     # C++ API
            ├── i2c_pure_c.{h,cc}      # C API for Python ctypes
            ├── i2c_intr_gpio.{h,cc}   # GPIO interrupt handling
            ├── ctypes_example.py       # Direct ctypes usage example
            └── Makefile                # Local build file
```

## Troubleshooting

1. **Missing libi2c:** Install with `sudo apt install libi2c-dev`
2. **Missing WiringPi:** Install with `sudo apt install libwiringpi-dev`
3. **Permission denied:** Make sure your user is in the `i2c` group: `sudo usermod -a -G i2c $USER`
4. **I2C not enabled:** Enable I2C using `sudo raspi-config` → Interface Options → I2C

## License

Copyright(c) 2025 Mirametrix Inc. All rights reserved.