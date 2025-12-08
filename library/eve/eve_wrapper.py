import os
import sys
import cv2
import ctypes
import platform
import numpy as np
import json
from pathlib import Path
from .eve_python import eve_sdk as sdk
from .eve_python import eve_fpga as fpga
from subprocess import run, CalledProcessError, TimeoutExpired

LOCAL_PIPELINE = True

FACE_ID_CLEAR = sdk.structs.setting_type_t.CS_COMMAND + 0
FACE_ID_REGISTER = sdk.structs.setting_type_t.CS_COMMAND + 1
FACE_ID_CLEAR_ID = sdk.structs.setting_type_t.CS_COMMAND + 2
FACE_ID_SECONDARY_USERS = sdk.structs.setting_type_t.CS_CUSTOM
            
frames = 0
if LOCAL_PIPELINE:
    requested_state = sdk.structs.EveRequestedProcessingState.EVE_REQUESTED_PROCESSING_STATE_CONTINUE
else:
    requested_state = sdk.structs.EveFpgaConnectionRequest.EVE_FPGA_CONTINUE
eve_sdk = None
callback = None

class EveWrapper():
    def __init__(self, comport, i2cAdapter, i2cDevice, i2cIRQ, pipelineVersion, evePath, toJpg, copyImage, maxWidth, driverPath, objectDetection):
        self._data = None
        self._image = None
        self._imageClone = None
        self._json = None
        self._jsonStr = ""
        self._frame_id = 0
        self._fpga_enabled = False
        self._comport = comport
        self._i2cAdapter = i2cAdapter
        self._i2cDevice = i2cDevice
        self._i2cIRQ = i2cIRQ
        self._driverPath = driverPath
        self._pipelineVersion = pipelineVersion
        self._evePath = evePath
        self._is_windows = platform.system() == "Windows"
        self._toJpg = toJpg
        self._copyImage = copyImage
        self._maxWidth = maxWidth
        self._fpgaState = {}
        self._fpgaCameraId = -1
        self._metaDataFpgaCameraId = -1
        self._usedCameraId = -1
        self._objectDetection = objectDetection
        self._ulpActivated = False

    def isInitialized(self):
        return eve_sdk != None

    def preloadCameraDriver(self):
        """Load camera driver at startup before mode selection"""
        if not self._is_windows:
            try:
                # Check if driver is already loaded
                check_res = run(
                    ["lsmod"],
                    check=True, capture_output=True, text=True, timeout=5
                )
                if "imx219" in check_res.stdout:
                    print("Camera driver already loaded")
                    return "Camera driver already loaded"
                
                # Driver not loaded, load it now
                out = f"Preloading camera driver\n"
                res = run(
                    ["sudo", "insmod", f"{self._driverPath}/lscc-imx219.ko"],
                    check=True, capture_output=True, text=True, timeout=5
                )
                out += res.stdout + "\n"
                print(out)
                return out
            except TimeoutExpired:
                print("Camera driver preload timed out")
                return "Timed out"
            except CalledProcessError as e:
                # Driver might already be loaded, which is fine
                print(f"Camera driver preload: {e.stderr or e.stdout}")
                return f"Note: {e.stderr or e.stdout}"
        return "Windows - no driver preload needed"
        
    def enableSomCamera(self, enabled: bool):
        try:
            out = f"enableSomCamera: {enabled}\n"
            if enabled:
                res = run(
                    ["sudo", "pinctrl", "set", "21", "dh"],
                    check=True, capture_output=True, text=True, timeout=5
                )
                out += res.stdout + "\n"
                # Commented out because camera driver is already loaded at startup
                # if res.returncode == 0:
                #     res = run(
                #         ["sudo", "insmod", f"{self._driverPath}/lscc-imx219.ko"],
                #         check=True, capture_output=True, text=True, timeout=5
                #     )
                #     out += res.stdout + "\n"
            else:
                res = run(
                    ["sudo", "pinctrl", "set", "21", "dl"],
                    check=True, capture_output=True, text=True, timeout=5
                )
                out += res.stdout + "\n"
            return out
        except TimeoutExpired:
            return "Timed out"
        except CalledProcessError as e:
            return f"Failed: {e.stderr or e.stdout}"

    def init(self, useMetadataCamera: bool):    
        print("Initializing EVE")
        if self._is_windows:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            
        global eve_sdk
        global callback
        
        root = Path(os.path.abspath(__file__)).parent
        backup_cwd = os.getcwd()
        os.chdir(self._evePath)
            
        if LOCAL_PIPELINE:
            if self._is_windows:
                eve_sdk_path = os.path.join(self._evePath,"EveSDK.dll")
                if not os.path.isfile(eve_sdk_path):
                    eve_sdk_path = os.path.join(root.parent.parent,self._evePath,"EveSDK.dll")
                eve_sdk = sdk.EveSDK(eve_sdk_path)
            else:
                eve_sdk_path = os.path.join(self._evePath,"libEveSDK.so")
                if not os.path.isfile(eve_sdk_path):
                    eve_sdk_path = os.path.join(self._evePath,"..","lib","libEveSDK.so")
                eve_sdk = sdk.EveSDK(eve_sdk_path)
                
                print(self.enableSomCamera(not useMetadataCamera))
                self.enableUlp(self._ulpActivated)
                    
                
            ByteArray512 = ctypes.c_byte * 512
            encoded = os.path.dirname(eve_sdk_path).encode('utf-8')
            pathOverride = ByteArray512(*encoded, *([0] * (512 - len(encoded))))  # zero-pad to 512

            startup_options = sdk.structs.EveStartupParameters(pathOverride=pathOverride, gpuPreference=sdk.structs.EveGpuPreference.EVE_NO_GPU)
            err = eve_sdk.CreateEve(startup_options)
            if (err != sdk.structs.EveError.EVE_ERROR_NO_ERROR):
                print(f"CreateEve error code: {err}")
                sys.exit(err)
                
            
                        
            # From EdgeVisionEngine\AutoSentrySample\AutoSentrySample.cpp            
            i = 0
            while True:
                cameraInfo = eve_sdk.EveGetCamera( i )
                if cameraInfo.error == sdk.structs.EveError.EVE_INVALID_CAMERA_ID or cameraInfo.error == sdk.structs.EveError.EVE_NO_MORE_DATA:
                    break
            
                pid = ctypes.cast(cameraInfo.data.pid, ctypes.c_char_p).value
                vid = ctypes.cast(cameraInfo.data.vid, ctypes.c_char_p).value
                if cameraInfo.data.isFpgaCamera == 1:
                    if self._metaDataFpgaCameraId == -1 and vid == b'META' and pid == b'DATA':
                        self._metaDataFpgaCameraId = i
                    elif self._fpgaCameraId == -1:
                        self._fpgaCameraId = i
                print(i, self._fpgaCameraId, self._metaDataFpgaCameraId, cameraInfo.error, pid, vid)
                if self._fpgaCameraId >= 0 and self._metaDataFpgaCameraId >= 0:
                    break
                i += 1
            if self._fpgaCameraId == -1 and self._metaDataFpgaCameraId == -1:
                raise RuntimeError("No FPGA camera found")
            print(f" \n\t\t *** FPGA camera found: {self._fpgaCameraId}, metadata {self._metaDataFpgaCameraId}\n" )
            
            if useMetadataCamera:
                self._usedCameraId = self._metaDataFpgaCameraId
            else:
                self._usedCameraId = self._fpgaCameraId
            
            # Default:
            cameraFormat = sdk.structs.CCameraFormat()
            # Note that putting higher values here fails on the RPI,
            # It takes another resolution, aspect ratio is screwed, there's lines added at the wrong place, etc.
            # Since the lowest in EveGetFormats() is 720, using 640 works for Windows, but doesn't fail on linux 
            # (using index 0, which is at least not crashing on startup)
            if self._is_windows:
                cameraFormat.resolution.width = 640
                cameraFormat.resolution.height = 360
            else:
                cameraFormat.resolution.width = 1600
                cameraFormat.resolution.height = 1200
                
            cameraFormat.compareResolution = sdk.structs.EveCompare.EVE_AT_MOST
            cameraFormat.compareFps = sdk.structs.EveCompare.EVE_AT_LEAST
            formats = eve_sdk.EveGetFormats(self._usedCameraId, cameraFormat)
            
            
            filter = None
            if formats.formatsCount > 0:
                for i in range(formats.formatsCount):
                    f = formats.formats[i]
                    print(f"{i}: {f.resolution.width}x{f.resolution.height}")
                    # Doing "at most" here
                    if f.resolution.width <= cameraFormat.resolution.width and f.resolution.height <= cameraFormat.resolution.height:
                        if not filter or (f.resolution.width >= filter.resolution.width and f.resolution.height >= filter.resolution.height):
                            filter = f
                            print(f"\t Switching to {f.resolution.width}x{f.resolution.height}")
                if not filter: 
                    filter = formats.formats[0]
                        
            if not filter:            
                filter = sdk.structs.CCameraFormat()
                filter.resolution.width = cameraFormat.resolution.width
                filter.resolution.height = cameraFormat.resolution.height
            filter.compareResolution = cameraFormat.compareResolution
            filter.compareFps = cameraFormat.compareFps

            print(f"camera selected: ID#{self._usedCameraId}: {filter.resolution.width}x{filter.resolution.height}, Format: {filter.format} @ {filter.fps}FPS")
            
            
            errorCode = eve_sdk.EveSetCamera( self._usedCameraId, filter )
            if errorCode != sdk.structs.EveError.EVE_ERROR_NO_ERROR:
                raise RuntimeError(f"Could't set camera {errorCode}")
                
                
            self.initFpga(useMetadataCamera=useMetadataCamera)
           

            callback = sdk.EveProcessingCallbackFn(self.eve_callback)
            err = eve_sdk.EveRegisterDataCallback(callback)
            if (err != sdk.structs.EveError.EVE_ERROR_NO_ERROR):
                print(f"EveRegisterDataCallback error code: {err}")
                sys.exit(err)

            err = eve_sdk.StartEve()
            if (err != sdk.structs.EveError.EVE_ERROR_NO_ERROR):
                print(f"StartEve error code: {err}")
                sys.exit(err)
            self.querySettings()
        else:
            if self._is_windows:
                eve_sdk = fpga.EveFpgaCameraPlugin("./EveFpgaCameraPlugin.dll")
            else:
                eve_sdk = fpga.EveFpgaCameraPlugin("../lib/libEveFpgaCameraPlugin.so")
                
            parameters = sdk.structs.CFpgaParameters(
                comport=self._comport, 
                pipelineVersion=self._pipelineVersion)
                
            callback = fpga.EveFpgaCallbackFn(self.eve_callback)
            print("EveFpgaConnect", eve_sdk.EveFpgaConnect(parameters, callback))
            
        os.chdir(backup_cwd)
        print("EVE initialized")
        
    def initFpga(self, useMetadataCamera: bool):
        fpgaParameters = sdk.structs.CFpgaParameters()
        fpgaParameters.comport = self._comport
        fpgaParameters.forceCameraOn = 1
        fpgaParameters.pipelineVersion = self._pipelineVersion
        fpgaParameters.connection = 2 #EveFpgaConnectionType::EVE_FPGA_AUTO_SELECT=0, UART=1, U2C=2
        fpgaParameters.i2cAdapterNumber = self._i2cAdapter
        fpgaParameters.i2cDeviceNumber = self._i2cDevice
        fpgaParameters.i2cIRQPin = self._i2cIRQ
                   
        #if self._hostConfig["busses"][0]["bus_type"] == "UART":
        #    fpgaParameters.connection = 1
        # Else auto select, I2C first.
        options = sdk.structs.EveFpgaOptions()
        options.parameters = fpgaParameters
        options = eve_sdk.EveConfigureFpga( options );
        if options.error != sdk.structs.EveError.EVE_ERROR_NO_ERROR:
            raise RuntimeError(f"Could't configure FPGA {options.error}")
            
        self.enableFpga(True, useMetadataCamera=useMetadataCamera)
        
    def querySettings(self):
        typeMask = 0
        settingsMask = 0
        for pt in [sdk.structs.pipeline_config_type_t.PT_FD, sdk.structs.pipeline_config_type_t.PT_LM_FV, sdk.structs.pipeline_config_type_t.PT_FID, sdk.structs.pipeline_config_type_t.PT_PD]:
            typeMask |= ( 1 << pt )
        for st in [sdk.structs.setting_type_t.CS_ENABLED, sdk.structs.setting_type_t.CS_IPS, sdk.structs.setting_type_t.CS_CUSTOM]:
            settingsMask |= ( 1 << st )
        print("\t\tTYPE", typeMask, "SETTINGS", settingsMask)
        return eve_sdk.QueryFpgaSettings(typeMask, settingsMask, notify=True)
            
    def enableFpga(self, activate: bool, useMetadataCamera: bool):
        if not self.isInitialized():
            self.init(useMetadataCamera)
            
        self._fpga_enabled = activate
        
        fpgaDebugOptions = sdk.structs.EveFpgaDebugOptions()
        fpgaDebugOptions.enableDrawingOnImage = 1 if self._fpga_enabled else 0
        options = eve_sdk.EveConfigureFpgaDebug( fpgaDebugOptions );
        if options.error != sdk.structs.EveError.EVE_ERROR_NO_ERROR:
            raise RuntimeError(f"Could't configure FPGA {options.error}")
            
    def enableUlp(self, enabled: bool):
        if not self.isFpgaEnabled or not self.isUsingMetadata():
            return "ULP Not available"
        try:
            out = f"enableUlp: {enabled}\n"
            res = run(
                ["sudo", "pinctrl", "set", "13", "dl" if enabled else "dh"],
                check=True, capture_output=True, text=True, timeout=5
            )
            out += res.stdout + "\n"
            if res.returncode == 0:
                res = run(
                    ["sudo", "pinctrl", "set", "6", "dl" if enabled else "dh"],
                    check=True, capture_output=True, text=True, timeout=5
                )                
                out += res.stdout + "\n"
                if res.returncode == 0:
                    self._ulpActivated = enabled
            return out
        except TimeoutExpired:
            return "Timed out"
        except CalledProcessError as e:
            return f"Failed: {e.stderr or e.stdout}"

    def registerFaceID(self):
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        
        command = sdk.structs.pipeline_config_t(type=sdk.structs.pipeline_config_type_t.PT_FID, 
            setting=sdk.structs.pipeline_setting_t(
                settingType=FACE_ID_REGISTER,
                value=1))
        eve_sdk.SendSetSetting(command)
    
    def clearFaceID(self):
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        
        command = sdk.structs.pipeline_config_t(type=sdk.structs.pipeline_config_type_t.PT_FID, 
            setting=sdk.structs.pipeline_setting_t(
                settingType=FACE_ID_CLEAR,
                value=1))
        eve_sdk.SendSetSetting(command)

    def isFpgaEnabled(self):
        if not eve_sdk:
            return False
        return self._fpga_enabled
    
    def isUsingMetadata(self):
        if not eve_sdk:
            return False
        return self._metaDataFpgaCameraId == self._usedCameraId
         
    def isUlpEnabled(self):
        if not eve_sdk:
            return False
        return self._ulpActivated
        
    def configure(self, feats):              
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")              
        for featureName in feats:
            f = feats[featureName]
            if "enabled" in f:
                enabled = 1 if f["enabled"] else 0
                print(f"{featureName}: {enabled}")
                
                if featureName == "hand_landmarks":
                    eve_sdk.EveConfigureHandGesture(sdk.structs.EveHandGestureOptions(enabled=enabled))
                elif featureName == "person_detection":
                    eve_sdk.EveConfigurePersonDetection(sdk.structs.EvePersonDetectionOptions(enabled=enabled))
                elif featureName == "face_detection":
                    mode = sdk.structs.EveFaceTrackerMinimumMode.EVE_FACETRACKER_MINIMUM_MODE_AVERAGE if enabled else sdk.structs.EveFaceTrackerMinimumMode.EVE_FACETRACKER_MINIMUM_MODE_OFF
                    eve_sdk.EveConfigureFaceTracker(sdk.structs.EveFaceTrackerOptions(faceTrackerMode=mode))
                elif featureName == "face_id":
                    # TODO: GalleryPath?
                    eve_sdk.EveConfigureFaceId(sdk.structs.EveFaceIdOptions(enabled=enabled))
                elif featureName == "object_detection":
                    eve_sdk.EveConfigureObjectDetection(sdk.structs.EveObjectDetectionOptions(enabled=enabled))

        return True
    def configureFpga(self, feats):
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        for featureName in feats:
    
            if featureName == "hand_landmarks":
                featureType = sdk.structs.pipeline_config_type_t.PT_HD
            elif featureName == "person_detection":
                featureType = sdk.structs.pipeline_config_type_t.PT_PD
            elif featureName == "face_detection":
                featureType = sdk.structs.pipeline_config_type_t.PT_FD
            elif featureName == "face_validation":
                featureType = sdk.structs.pipeline_config_type_t.PT_LM_FV
            elif featureName == "face_id":
                featureType = sdk.structs.pipeline_config_type_t.PT_FID
            elif featureName == "face_id_multi":
                featureType = sdk.structs.pipeline_config_type_t.PT_FID                    
                f = feats[featureName]
                
                FACE_ID_SECONDARY_USERS = sdk.structs.setting_type_t.CS_CUSTOM + 0
                if "enabled" in f:
                    enabled = 1 if f["enabled"] else 0
                    print(f"{featureName}: {enabled}")
                    
                    # TODO: Not for all features all the time, only the ones that changed.
                    command = sdk.structs.pipeline_config_t(type=featureType, 
                        setting=sdk.structs.pipeline_setting_t(
                            settingType=FACE_ID_SECONDARY_USERS,
                            value=1 if enabled else 0))
                    eve_sdk.SendSetSetting(command)
                continue
            else:
                print(f"Unknown feature name: '{featureName}'")
                return False
            
            f = feats[featureName]
            if "enabled" in f:
                enabled = 1 if f["enabled"] else 0
                print(f"{featureName}: {enabled}")
                
                # TODO: Not for all features all the time, only the ones that changed.
                command = sdk.structs.pipeline_config_t(type=featureType, 
                    setting=sdk.structs.pipeline_setting_t(
                        settingType=sdk.structs.setting_type_t.CS_ENABLED,
                        value=1 if enabled else 0))
                eve_sdk.SendSetSetting(command)
            if "max_ips" in f:
                ips = int(f["max_ips"])
                print(f"{featureName} IPS: {ips}")
                
                command = sdk.structs.pipeline_config_t(type=featureType, 
                    setting=sdk.structs.pipeline_setting_t(
                        settingType=sdk.structs.setting_type_t.CS_IPS,
                        value=ips))
                eve_sdk.SendSetSetting(command)
                
        return True        

    def get_frame_id(self):  
        return self._frame_id
        
    def get_json(self):
        return self._json
        
    def get_json_str(self):
        return self._jsonStr
        
    def get_image_jpg(self):
        return self._image
        
    def get_image(self):
        return self._imageClone
        
    def eve_callback(self, return_data):
        if LOCAL_PIPELINE:
            self.readJson()
            processed_image = eve_sdk.EveGetProcessedImage()
            if processed_image.error != sdk.structs.EveError.EVE_ERROR_NO_ERROR:
                print(f"EveGetProcessedImage() error code: {error}")
            else:
            
                img = np.ctypeslib.as_array(processed_image.data, shape=(processed_image.height, processed_image.width, processed_image.channels)).astype(np.uint8)
                
                if processed_image.channels == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_YUV2BGR_YUYV)
                    
                if img.shape[2] == 1 or img.shape[2] == 3:
                    # Rescale to self._maxWidth max width
                    if self._maxWidth > 0:
                        scaleFactor=self._maxWidth/processed_image.width
                        if scaleFactor < 1:
                            img = cv2.resize(img, (0,0), fx=scaleFactor, fy=scaleFactor, interpolation=cv2.INTER_AREA)
                        
                    if self._toJpg:
                        self._image = cv2.imencode('.jpg', img)[1].tobytes()
                    if self._copyImage:
                        self._imageClone = img.copy()
                    self._frame_id += 1
                    #print(f"Frame #{self._frame_id}")
        
            # Gestures only to test:
            gestures_data = eve_sdk.EveGetStaticGestureDetections()
            if gestures_data.errorCode != sdk.structs.EveError.EVE_ERROR_NO_ERROR:
                print(f"EveGetStaticGestureDetections() error code: {gestures_data.errorCode}")
                sys.exit(gestures_data.errorCode)

            data = gestures_data.gestures
            if not data.count:
                self._data = None

            for gesture in data.gestures[:data.count]:
                if gesture.handId != 0:
                    self._data = {'hand':{
                        'available':True,
                        'gesture': int(self.convert_gesture(gesture.type))+1}
                        }
                    break
                    print(f"G: {gesture.handId} ({gesture.type})")
            return_data.contents.requestedState = requested_state
        else:
        
            fpgaJson = eve_sdk.EveFpgaReadJson()
            if fpgaJson.textStart:
                jsonStr = ctypes.string_at(fpgaJson.textStart, fpgaJson.textSize)
                self._jsonStr = jsonStr
                dataJson = json.loads(jsonStr)
                if dataJson and dataJson['serial_status'] == 'success':
                    self._frame_id += 1
                    self._json = dataJson
            return_data.contents.request = requested_state
                

    def poll_frame(self):
        return self._data

    def poll_setting(self):
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        setting = eve_sdk.PopQueuedSetting()
        if setting.message.serialStatus != sdk.structs.EveFpgaSerialStatus.EVE_FPGA_SUCCESS or setting.message.responseType == sdk.structs.response_type_t.RT_NONE:
            return None
        
        return setting
        
    def poll_settings(self):
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        setting = self.poll_setting()
        while setting:            
            print(f"\t\t--------setting response type: -- {setting.message.responseType} -- pipeline  {setting.type}, setting {setting.setting}, value {setting.value}")            
            
            if not setting.type in self._fpgaState and setting.type < sdk.structs.pipeline_config_type_t.PT_SIZE:
                self._fpgaState[sdk.structs.pipeline_config_type_t(setting.type)] = {}
            feature = self._fpgaState[setting.type]
            #if not setting.setting in feature:
            if setting.setting < sdk.structs.setting_type_t.CS_MAX:
                feature[sdk.structs.setting_type_t(setting.setting)] = setting.value
            setting = self.poll_setting()
        
    def readJson(self):
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        fpgaJson = eve_sdk.FpgaReadJson()
        if fpgaJson.textStart:
            jsonStr = ctypes.string_at(fpgaJson.textStart, fpgaJson.textSize)
            self._jsonStr = jsonStr
            dataJson = json.loads(jsonStr)
            if dataJson and dataJson['serial_status'] == 'success':
                self._frame_id += 1            
                self._json = dataJson

    def stop(self):
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        print("Stopping EVE")
        if self._is_windows:
            import pythoncom
            pythoncom.CoUninitialize()
        global requested_state
        if LOCAL_PIPELINE:
            requested_state = sdk.structs.EveRequestedProcessingState.EVE_REQUESTED_PROCESSING_STATE_STOP
        else:
            requested_state = sdk.structs.EveFpgaConnectionRequest.EVE_FPGA_STOP
