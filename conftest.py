import logging
import pytest
import yaml
import os
import sys
import time

# Add library path for EVE imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'library'))

def pytest_addoption(parser):
    parser.addoption(
        "--saveimage",
        action="store",
        default="0",
        choices=["0", "1", "2"],
        help="Image saving mode: 0=default, 1=save all, 2=save only fail"
    )
    parser.addoption(
        "--savemeta",
        action="store",
        default="0",
        choices=["0", "1", "2"],
        help="Metadata saving mode: 0=default, 1=save all, 2=save only fail"
    )
    parser.addoption(
        "--image",
        action="store",
        default=None,
        help="Path to an image file to use for tests that accept --image"
    )

@pytest.fixture
def saveimage(request):
    return int(request.config.getoption("--saveimage"))

@pytest.fixture
def savemeta(request):
    return int(request.config.getoption("--savemeta"))


@pytest.fixture
def image(request):
    """Return the --image option value (or None)."""
    return request.config.getoption("--image")

# Grouped options fixture
@pytest.fixture
def options(saveimage, savemeta):
    return {
        "saveimage": saveimage,
        "savemeta": savemeta
    }

@pytest.fixture(scope="session")
def config():
    try:
        with open("config.yaml") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        pytest.fail("config.yaml not found. Please ensure configuration file exists.")
    except Exception as e:
        pytest.fail(f"Error loading config: {e}")

@pytest.fixture(scope="session")
def eve(request, config):
    """Main startup fixture providing an EVE wrapper instance.
    Prefer the extended wrapper (`EveWrapperExt`) if available to expose FPGA state helpers
    without modifying the original library.
    """
    try:
        from eve_wrapper_ext import EveWrapperExt
    except ImportError as e:
        logging.warning(f"EVE wrapper not available: {e}")
        yield None
        return

    i2c_config = config.get('i2c', {})
    eve_sdk_config = config.get('eve', {})
    
    try:
        wrapper = EveWrapperExt(
            comport=eve_sdk_config.get('comport', 0),
            i2cAdapter=i2c_config.get('bus', 0),
            i2cDevice=i2c_config.get('device_address', 0x30),
            i2cIRQ=i2c_config.get('irq_pin', 26),
            pipelineVersion=eve_sdk_config.get('pipeline_version', 0),
            evePath=eve_sdk_config.get('eve_path', '/opt/EVE-6.7.21-Source/bin'),
            toJpg=eve_sdk_config.get('to_jpg', True),
            copyImage=eve_sdk_config.get('copy_image', True),
            maxWidth=eve_sdk_config.get('max_width', 800),
            driverPath=eve_sdk_config.get('driver_path', '/home/lattice/mY_Work/eve-cam/clnx_camDrvEn'),
            objectDetection=eve_sdk_config.get('object_detection', False)
        )
        
        # Initialize if hardware is available
        try:
            # Preload camera driver
            wrapper.preloadCameraDriver()
            
            # Use the metadata camera setting directly from config.yaml
            use_metadata_camera = eve_sdk_config.get('use_metadata_camera', True)
            logging.debug("Initializing EVE wrapper - this should only appear once per test session")
            wrapper.init(useMetadataCamera=use_metadata_camera)

            # Configure features
            features = config.get('features', {})
            if wrapper.isFpgaEnabled():
                wrapper.configureFpga(features)
            else:
                wrapper.configure(features)

            # Get stabilization time from config['environment'], default to 0s
            eve_stabilize_time = config.get('environment', {}).get('eve_stabilize_time', 0)
            time.sleep(eve_stabilize_time)

            yield wrapper

            # Fixture cleanup (this runs when session ends or fixture is torn down)
            try:
                logging.debug("Starting EVE shutdown sequence...")
                
                # Get shutdown sleep time from config['environment'], default to 2s
                eve_shutdown_time = config.get('environment', {}).get('eve_shutdown_time', 2)
                time.sleep(eve_shutdown_time)
                
                wrapper.stop()
                logging.debug("EVE wrapper stopped successfully.")

            except Exception as e:
                logging.warning(f"Warning during EVE cleanup: {e}")

        except Exception as e:
            logging.warning(f"Failed to initialize EVE: {e}")
            yield None
            
    except Exception as e:
        logging.warning(f"Failed to create EVE wrapper: {e}")
        yield None

 
@pytest.fixture(scope="session", autouse=True)
def clear_logfile_once():
    # Truncate the log file only once at the start of the test session
    with open("logfile.txt", "a"):
        pass

def pytest_sessionfinish(session, exitstatus):
    """
    Hook that runs after all tests complete, before pytest exits.
    This ensures proper cleanup is completed before pytest terminates.
    """
    # Additional cleanup time to ensure all operations complete
    logging.debug("Waiting for final system cleanup (2 seconds)...")
    time.sleep(2)
    
    # Force flush all logs
    for handler in logging.getLogger().handlers:
        handler.flush()
    
    logging.debug("Session cleanup completed - pytest will now exit")
    
    # Force a final sync to ensure all file operations complete
    try:
        os.sync()
    except AttributeError:
        pass  # os.sync() not available on Windows

@pytest.fixture(autouse=True)
def configure_logging():
    # Clear any existing handlers to avoid duplication
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    logging.basicConfig(
        filename="logfile.txt",
        level=logging.INFO,
        #level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True
    )
    
    # Only add console handler if not running under pytest
    import sys
    if 'pytest' not in sys.modules:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(console)
