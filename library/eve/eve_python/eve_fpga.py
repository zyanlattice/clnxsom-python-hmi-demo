import ctypes
import eve.eve_python.eve_sdk_structs as structs

EveFpgaCallbackFn = ctypes.CFUNCTYPE(None, ctypes.POINTER(structs.CFpgaCallbackControl))

class EveFpgaCameraPlugin:
    def __init__(self, dll_path: str):
        self.cdll = ctypes.CDLL(dll_path)
        
        # EveFpgaInterface.h
        self.cdll.EveFpgaConnect.restype = structs.EveFpgaSerialStatus
        self.cdll.EveFpgaConnect.argtypes = [structs.CFpgaParameters, EveFpgaCallbackFn]
        self.cdll.EveFpgaRead.restype = structs.EveFpgaMetadata
        self.cdll.EveFpgaRead.argtypes = []
        self.cdll.EveFpgaReadJson.restype = structs.EveFpgaJsonMetadata
        self.cdll.EveFpgaReadJson.argtypes = []
        
    # EveFpgaInterface.h
    def EveFpgaConnect(self, parameters: structs.CFpgaParameters, callback) -> structs.EveFpgaSerialStatus:
        return self.cdll.EveFpgaConnect(parameters, callback)
    
    def EveFpgaRead(self) -> structs.EveFpgaMetadata:
        return self.cdll.EveFpgaRead()
    
    def EveFpgaReadJson(self) -> structs.EveFpgaJsonMetadata:
        return self.cdll.EveFpgaReadJson()
        
