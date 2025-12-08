"""
Extended EVE Wrapper with thread-safe improvements and additional functionality.
This class inherits from the EVE library's EveWrapper without modifying the library itself.

Key enhancements:
- Thread-safe data access using RLock for concurrent operations
- Atomic frame data retrieval to ensure consistency
- Improved shutdown sequence with proper resource cleanup
- Enhanced error handling and logging
"""

import os
import sys
import threading
import time

# Add the library path to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), 'eve'))

from eve.eve_wrapper import EveWrapper
from eve.eve_python import eve_sdk as sdk


class EveWrapperExt(EveWrapper):
    """Extended EVE Wrapper with thread-safe operations and enhanced functionality"""
    
    def __init__(self, comport, i2cAdapter, i2cDevice, i2cIRQ, pipelineVersion, evePath, toJpg, copyImage, maxWidth, driverPath, objectDetection):
        """Initialize the extended wrapper with a thread-safe lock"""
        super().__init__(comport, i2cAdapter, i2cDevice, i2cIRQ, pipelineVersion, evePath, toJpg, copyImage, maxWidth, driverPath, objectDetection)
        # Add reentrant lock for thread safety
        self._data_lock = threading.RLock()
    
    # configure features method
    def set_features(self, features, wait=10):
        if self.isFpgaEnabled():
            self.configureFpga(features)
            for _ in range(wait):
                self.querySettings()
                time.sleep(0.5)
                self.poll_settings()
                time.sleep(0.5)
                actual_state = self.getFpgaState()
                if all(actual_state.get(k, {}).get("enabled", False) == v.get("enabled", False) for k, v in features.items()):
                    return True
                time.sleep(1)
            raise RuntimeError(f"Feature sync failed after {wait} seconds: {actual_state}")
        else:
            self.configure(features)

    # Override getter methods to be thread-safe
    def get_frame_id(self):
        """Get the current frame ID in a thread-safe manner"""
        with self._data_lock:
            return self._frame_id
    
    def get_json(self):
        """Get a copy of the JSON metadata in a thread-safe manner"""
        with self._data_lock:
            return self._json.copy() if self._json else None
    
    def get_json_str(self):
        """Get the JSON string in a thread-safe manner"""
        with self._data_lock:
            return self._jsonStr
    
    def get_image_jpg(self):
        """Get the JPEG-encoded image in a thread-safe manner"""
        with self._data_lock:
            return self._image
    
    def get_image(self):
        """Get a copy of the image in a thread-safe manner"""
        with self._data_lock:
            return self._imageClone.copy() if self._imageClone is not None else None
    
    def get_frame_data(self):
        """
        Thread-safe method to get consistent frame data (metadata, image, frame_id) atomically.
        This ensures that the metadata, image, and frame_id all come from the same frame.
        
        Returns:
            dict: A dictionary containing:
                - 'metadata': Copy of JSON metadata (or None)
                - 'image': Copy of the image (or None)
                - 'frame_id': Current frame ID
        """
        with self._data_lock:
            return {
                'metadata': self._json.copy() if self._json else None,
                'image': self._imageClone.copy() if self._imageClone is not None else None,
                'frame_id': self._frame_id
            }
    
    def readJson(self):
        """
        Override readJson to return values instead of setting instance variables directly.
        This allows for atomic updates in the callback function.
        
        Returns:
            tuple: (json_data, frame_id, json_string)
        """
        # Import eve_sdk from parent's globals
        from eve.eve_wrapper import eve_sdk
        
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        
        tmp_jsonStr_ = tmp_json = None
        tmp_frame_id = self._frame_id
        fpgaJson = eve_sdk.FpgaReadJson()
        if fpgaJson.textStart:
            import ctypes
            import json
            jsonStr = ctypes.string_at(fpgaJson.textStart, fpgaJson.textSize)
            tmp_jsonStr_ = jsonStr
            dataJson = json.loads(jsonStr)
            if dataJson and dataJson['serial_status'] == 'success':
                tmp_frame_id += 1            
                tmp_json = dataJson
        return tmp_json, tmp_frame_id, tmp_jsonStr_
    
    def eve_callback(self, return_data):
        """
        Override the callback to implement thread-safe data updates.
        Uses temporary variables and atomic lock-protected assignment.
        """
        # Import required modules and globals
        import cv2
        import numpy as np
        import sys
        from eve.eve_wrapper import eve_sdk, LOCAL_PIPELINE, requested_state
        
        if LOCAL_PIPELINE:
            tmp_image = tmp_imageClone = None
            tmp_json, tmp_frame_id, tmp_jsonStr = self.readJson()
            processed_image = eve_sdk.EveGetProcessedImage()
            if processed_image.error != sdk.structs.EveError.EVE_ERROR_NO_ERROR:
                print(f"EveGetProcessedImage() error code: {processed_image.error}")
            else:
                img = np.ctypeslib.as_array(processed_image.data, shape=(processed_image.height, processed_image.width, processed_image.channels)).astype(np.uint8)
                
                if processed_image.channels == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_YUV2BGR_YUYV)
                    
                if img.shape[2] == 1 or img.shape[2] == 3:
                    # Rescale to self._maxWidth max width
                    if self._maxWidth > 0:
                        scaleFactor = self._maxWidth / processed_image.width
                        if scaleFactor < 1:
                            img = cv2.resize(img, (0, 0), fx=scaleFactor, fy=scaleFactor, interpolation=cv2.INTER_AREA)
                    
                    if self._toJpg:
                        tmp_image = cv2.imencode('.jpg', img)[1].tobytes()
                    if self._copyImage:
                        tmp_imageClone = img.copy()
                    tmp_frame_id += 1
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
                        'available': True,
                        'gesture': int(self.convert_gesture(gesture.type)) + 1}
                    }
                    break
                    print(f"G: {gesture.handId} ({gesture.type})")
            
            return_data.contents.requestedState = requested_state

            # Atomic update of all frame data under lock
            with self._data_lock:
                self._json = tmp_json if tmp_json is not None else self._json
                self._jsonStr = tmp_jsonStr if tmp_jsonStr is not None else self._jsonStr
                self._image = tmp_image if tmp_image is not None else self._image
                self._imageClone = tmp_imageClone if tmp_imageClone is not None else self._imageClone
                self._frame_id = tmp_frame_id

        else:
            import ctypes
            import json
            
            fpgaJson = eve_sdk.EveFpgaReadJson()
            if fpgaJson.textStart:
                jsonStr = ctypes.string_at(fpgaJson.textStart, fpgaJson.textSize)
                with self._data_lock:
                    self._jsonStr = jsonStr
                    dataJson = json.loads(jsonStr)
                    if dataJson and dataJson['serial_status'] == 'success':
                        self._frame_id += 1
                        self._json = dataJson
            return_data.contents.request = requested_state
    
    def stop(self):
        """
        Override stop method with improved shutdown sequence.
        Ensures proper cleanup and prevents "media device still in use" errors.
        """
        # Import required modules and globals
        from eve.eve_wrapper import eve_sdk, LOCAL_PIPELINE, requested_state
        import platform
        
        if not eve_sdk:
            raise RuntimeError(f"Eve SDK not initialized")
        
        print("Stopping EVE")
        if platform.system() == "Windows":
            import pythoncom
            pythoncom.CoUninitialize()
        
        if LOCAL_PIPELINE:
            # First, signal the callback thread to stop
            import eve.eve_wrapper as ew
            ew.requested_state = sdk.structs.EveRequestedProcessingState.EVE_REQUESTED_PROCESSING_STATE_STOP
            
            # Wait for any ongoing callback operations to complete
            # Use the data lock to ensure callback isn't in the middle of processing
            with self._data_lock:
                print("Acquired data lock - safe to shutdown")
                
            # Increased delay to ensure callback thread processes the stop state
            time.sleep(0.5)  # More time for callback to fully process stop signal
            
            # Now safely shutdown the EVE SDK
            print("Calling ShutdownEve()...")
            err = eve_sdk.ShutdownEve()
            if err != sdk.structs.EveError.EVE_ERROR_NO_ERROR:
                print(f"ShutdownEve error code: {err}")
            
            # CRITICAL: Wait for EVE to release all video device handles
            # This prevents "media device still in use" errors on media0/media2
            print("Waiting for video device handles to be released...")
            time.sleep(2.0)  # Allow kernel time to cleanup video device references
            
            print("EVE shutdown complete")
        else:
            import eve.eve_wrapper as ew
            ew.requested_state = sdk.structs.EveFpgaConnectionRequest.EVE_FPGA_STOP
    
    def getFpgaState(self):
        """
        Get the current FPGA state in a user-friendly format.
        Returns a dictionary mapping feature names to their enabled state and settings.
        
        Returns:
            dict: Feature states with enabled status and IPS settings
        """
        # Map pipeline types to feature names
        type_to_feature = {
            sdk.structs.pipeline_config_type_t.PT_FD: "face_detection",
            sdk.structs.pipeline_config_type_t.PT_LM_FV: "face_validation",
            sdk.structs.pipeline_config_type_t.PT_FID: "face_id",
            sdk.structs.pipeline_config_type_t.PT_PD: "person_detection",
            sdk.structs.pipeline_config_type_t.PT_HD: "hand_landmarks",
        }
        
        features_state = {}
        
        for pipeline_type, feature_name in type_to_feature.items():
            if pipeline_type in self._fpgaState:
                feature_settings = self._fpgaState[pipeline_type]
                enabled_value = feature_settings.get(sdk.structs.setting_type_t.CS_ENABLED, 0)
                features_state[feature_name] = {
                    "enabled": bool(enabled_value)
                }
                # Add IPS if available
                if sdk.structs.setting_type_t.CS_IPS in feature_settings:
                    features_state[feature_name]["max_ips"] = feature_settings[sdk.structs.setting_type_t.CS_IPS]
        
        return features_state
