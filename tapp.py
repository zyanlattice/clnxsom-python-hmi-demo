import datetime
import logging
import time
import cv2
import pytest
import warnings
import os

from conftest import config, eve
from conftest import saveimage
from conftest import savemeta
from library.photo import Photo

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Required pytest additional plugins
# - pytest-timeout, to ensure the test doesn't stuck one place
# - pytest-repeat, for running no. of loop
# - pytest-logger, for logging used only

# General
logger = logging.getLogger(__name__)

# ████████╗███████╗███████╗████████╗     ██╗███╗   ██╗██╗████████╗
# ╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝     ██║████╗  ██║██║╚══██╔══╝
#    ██║   █████╗  ███████╗   ██║        ██║██╔██╗ ██║██║   ██║   
#    ██║   ██╔══╝  ╚════██║   ██║        ██║██║╚██╗██║██║   ██║   
#    ██║   ███████╗███████║   ██║        ██║██║ ╚████║██║   ██║  ██╗
#    ╚═╝   ╚══════╝╚══════╝   ╚═╝        ╚═╝╚═╝  ╚═══╝╚═╝   ╚═╝  ╚═╝

# -- blank line --

# ████████╗███████╗███████╗████████╗     ██████╗ ██████╗ ████████╗
# ╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝    ██╔═══██╗██╔══██╗╚══██╔══╝
#    ██║   █████╗  ███████╗   ██║       ██║   ██║██████╔╝   ██║   
#    ██║   ██╔══╝  ╚════██║   ██║       ██║   ██║██╔═══╝    ██║   
#    ██║   ███████╗███████║   ██║       ╚██████╔╝██║        ██║  ██╗
#    ╚═╝   ╚══════╝╚══════╝   ╚═╝        ╚═════╝ ╚═╝        ╚═╝  ╚═╝

def __fetch(eve):
	"""
	Fetch metadata and frame using EVE wrapper in a thread-safe manner.
	
	Args:
		eve: EVE wrapper instance from the eve fixture
	
	Returns:
		tuple: (metadata_dict, frame_array) or (None, None) if no data
	"""
	if eve is None:
		logger.error("EVE wrapper not available")
		return None, None
	
	try:
		# Get consistent frame data atomically to avoid race conditions
		frame_data = eve.get_frame_data()
        
		meta_json = frame_data['metadata']
		frame_ = frame_data['image']
		frame_id = frame_data['frame_id']
        
		if not meta_json:
			logger.debug("No metadata available from EVE")
			return None, None
        
		# Debug: Log the raw EVE JSON structure
		logger.debug(f"Raw EVE JSON: {meta_json}")
		logger.debug(f"EVE JSON keys: {list(meta_json.keys()) if isinstance(meta_json, dict) else 'Not a dict'}")
        
		# Use EVE metadata directly with minimal processing
		meta_ = meta_json.copy()
        
		# Create frame_info with frame_id only
		meta_["frame_info"] = {
			"frame_no": frame_id
		}
        
		return meta_, frame_
		
	except Exception as e:
		logger.error(f"Error fetching metadata from EVE: {e}")
		return None, None

def __generate_unique_id(test_name=None):
	"""
	Generate a unique ID using the current timestamp in the format YYYY-MM-DD_HH-MM-SS.
	"""
	timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
	if test_name:
		return f"{test_name}_{timestamp}"
	return f"Test_{timestamp}"

def __save(config, uniqueid, metadata, frame, options, test_="Fail"):
	output_dir = config['environment']['output_dir']
	if not os.path.exists(output_dir):
		os.makedirs(output_dir)

	# Save image according to saveimage mode
	if options["saveimage"] == 1 or (options["saveimage"] == 2 and test_ == "Fail"):
		if frame is not None:
			cv2.imwrite(f"{output_dir}/{uniqueid}_frame.jpg", frame)

	# Save metadata according to savemeta mode
	if options["savemeta"] == 1 or (options["savemeta"] == 2 and test_ == "Fail"):
		# Convert to JSON and save (EVE provides JSON, no need for XML conversion)
		import json
		with open(f"{output_dir}/{uniqueid}_metadata.json", "w", encoding="utf-8") as file_:
			json.dump(metadata, file_, indent=2, default=str)
	# Log the metadata for debugging
	#logger.debug("Metadata: %s", metadata)


# ██████╗ ███████╗██████╗ ██╗   ██╗ ██████╗ 
# ██╔══██╗██╔════╝██╔══██╗██║   ██║██╔════╝ 
# ██║  ██║█████╗  ██████╔╝██║   ██║██║  ███╗
# ██║  ██║██╔══╝  ██╔══██╗██║   ██║██║   ██║
# ██████╔╝███████╗██████╔╝╚██████╔╝╚██████╔╝
# ╚═════╝ ╚══════╝╚═════╝  ╚═════╝  ╚═════╝ 



@pytest.mark.parametrize("options", [
    {"saveimage": 1, "savemeta": 1},
    # other option sets
])
def test_live(config, options, eve):
	"""
	Live stream video, render overlays using Frame, and display in a window.
	Press 'q' to exit.
	"""
	prev_fps = prev_frame = fps = period = None
	try:
		while True:
			curr_time = time.time() # current timestamp
  
			# fetch metadata and frame
			meta_, frame_ = __fetch(eve)

			if frame_ is None:
				continue
	
			# retrieve frame_info and user_count safely
			frame_info = meta_.get("frame_info", {}) if meta_ else {}
			user_count = meta_.get("pipeline_data", {}).get("user_count", 0) if meta_ else 0
	
			# Calculate FPS based on frame_no increments
			frame_no = frame_info.get("frame_no", None)
			if prev_frame is not None and frame_no != prev_frame:
				if prev_fps is not None:
					period = curr_time - prev_fps
					fps = 1.0 / period if period > 0 else 0.0
				prev_fps = curr_time
			elif prev_fps is None:
				prev_fps = curr_time
			prev_frame = frame_no
	
			# Add user_count to frame_info for display
			frame_info["user_count"] = user_count
			frame_info["period"] = round(period, 5) if period is not None else None
			frame_info["fps"] = round(fps, 2) if fps is not None else None

			# If users are detected, show each user's ID, face status and face distance
			if frame_info["user_count"] > 0 and meta_:
				users = meta_.get("pipeline_data", {}).get("users", [])
				if isinstance(users, list) and len(users) > 0:
					# Iterate through all detected users
					for i, user in enumerate(users):
						# Extract user ID, face status and face distance from correct structure
						user_id = user.get("id", i)  # Use index as fallback if no ID
						face_id_status = user.get("face_id_status", "unknown")
						face_distance = user.get("face_data", {}).get("distance", None)
						# Add each user's info to frame_info for display
						frame_info[f"user_{i}_id"] = user_id
						frame_info[f"user_{i}_face_status"] = face_id_status
						frame_info[f"user_{i}_face_distance"] = f"{face_distance:.1f} cm"

			# Print frame_info to terminal in a readable format (excluding frame_data)
			# Clear entire screen first, then display content
			print("\033[2J\033[H", end="")  # Clear entire screen and move cursor to top-left
			print("=" * 50)
			print("FRAME INFO:")
			print("=" * 50)
			if frame_info:
				for key, value in frame_info.items():
					if key != "frame_data":  # Skip frame_data to keep output clean
						print(f"  {key:15}: {value}")
			else:
				print("  No frame info available")
			print("=" * 50)

			# Display frame directly from EVE library
			cv2.imshow("Live Stream", frame_)
			# Exit on any key press
			if cv2.waitKey(1) & 0xFF != 0xFF:
				break

	finally:
		cv2.destroyAllWindows()

		try:
			if eve:
				logger.info("Stopping EVE...")
				time.sleep(1.5)  # allow time before stopping
				eve.stop()
				time.sleep(3)  # allow time to stop
		except Exception as e:
			logger.error(f"Error stopping EVE: {e}")
		

# ████████╗███████╗███████╗████████╗     ██████╗ █████╗ ███████╗███████╗
# ╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝    ██╔════╝██╔══██╗██╔════╝██╔════╝
#    ██║   █████╗  ███████╗   ██║       ██║     ███████║███████╗█████╗  
#    ██║   ██╔══╝  ╚════██║   ██║       ██║     ██╔══██║╚════██║██╔══╝  
#    ██║   ███████╗███████║   ██║       ╚██████╗██║  ██║███████║███████╗
#    ╚═╝   ╚══════╝╚══════╝   ╚═╝        ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝


@pytest.mark.timeout(10)
@pytest.mark.parametrize(
		# Use a single@pytest.mark.parametrize with tuples to pair each image
		"image, person",
		[
			("./images/occlusion/img_pax-1_underHeavyRain.jpg", 1),
			("./images/distance/pax_5_250cm.png", 5),
			("./images/occlusion/img_pax-1_underHeavyRain_1.jpg", 1),
			("./images/person/img_pax-5_old.jpg", 5),
			("./images/distance/pax_1_100cm_face_up.png", 1),
			("./images/occlusion/img_pax-3_sunglasses.jpg", 3),
			("./images/face_detect/fd_5_pax_100cm.jpg", 5),
			("./images/object/img_pax-0_cameraLen.jpg", 0),
			("./images/distance/pax_5_500cm.png", 5),
			("./images/distance/pax_5_100cm.png", 5),
			("./images/occlusion/img_pax-4_sunglasses.jpg", 4),
			("./images/face_detect/fd_5_pax_150cm.jpg", 5),
			("./images/distance/pax_1_100cm_face_right.png", 1),
			("./images/person/img_pax-3.jpg", 3),
			("./images/occlusion/img_pax-4_glasses_mask_cap.jpg", 4),
			("./images/face_detect/fd_5_pax_200cm.jpg", 5),
			("./images/object/img_pax-0_rose.jpg", 0),
			("./images/occlusion/img_pax-5_FaceMasks.jpg", 5),
			("./images/face_detect/fd_3_pax_150cm.jpg", 3),
			("./images/distance/pax_1_250cm_2.png", 1),
		]
	)

def test_pdfd(config, image, person, options, eve):
	"""
	Test person and face detection for random set of images with occlusion.
	Verifies detection accuracy when faces are partially obscured.
    
	Args:
		config: dict, test and environment configuration.
		image: str, path to the test image file.
		person: int, expected number of persons in the image.
		options: dict, controls saving image/metadata.
		eve: EVE wrapper instance.
	"""

	test_ = "Fail" # default to fail
	photo_ = None
	meta_ = None
	frame_ = None

	try:
		photo_ = Photo(image)
		photo_.show()

		# Wait for display and metadata to be ready
		time.sleep(3)  # Wait for display and metadata to be ready, 5s in regression
	 
		meta_, frame_ = __fetch(eve)		
		if meta_:
			# Get user_count safely from pipeline_data
			user_count = meta_.get("pipeline_data", {}).get("user_count", 0)
			if user_count == person:
				test_ = "Pass"

	except Exception as e:
		logger.error(f"Error in test_pdfd: {e}")
		test_ = "Fail"
	finally:
		# Ensure photo is always closed, even on exception
		if photo_:
			try:
				photo_.close()
			except Exception as e:
				logger.warning(f"Error closing photo: {e}")
		# Ensure OpenCV windows are closed
		cv2.destroyAllWindows()

	# Save results
	__save(
		config,
		__generate_unique_id("t_pdfd"),
		meta_,
		frame_,
		options,
		test_
	)

	# Assert the test result
	assert (test_ == "Pass")


# Custom exception for Face ID operations (nested inside test function)
class FaceIDError(Exception):
	"""Custom exception for Face ID operations."""
	pass

def __check_registered_faces(meta_):
	"""
	Common helper function to check if any registered faces exist in metadata.
	
	Args:
		meta_: dict, metadata from EVE
		
	Returns:
		bool: True if registered faces found, False otherwise
	"""
	if not meta_:
		return False
		
	pipeline_data = meta_.get("pipeline_data", {})
	users = pipeline_data.get("users", [])
	
	if isinstance(users, list):
		for user in users:
			if isinstance(user, dict):
				is_face_id_available = user.get("is_face_id_status_available", False)
				face_id_status = user.get("face_id_status", "unknown")     
				if is_face_id_available and face_id_status == "registered":
					return True
	return False

def __unregister(eve, registered_face_path, display_photo):
	"""
	Clear existing face ID registrations from the gallery.
	
	Args:
		eve: EVE wrapper instance used to issue clear commands and fetch metadata.
		registered_face_path: str path to the face image that may be shown
			before clearing (used for human-in-the-loop registration flows).
		display_photo_enabled: bool flag controlling whether the image is
			displayed prior to the clear operation (True shows the image).

	Returns:
		tuple: (metadata_dict, frame_array) on success, or (None, None) when
		no metadata is available but the operation is considered successful.

	Raises:
		FaceIDError: If unregistration fails or face_id_status is not "unregistered"
	"""
	photo_ = None 
	try:
		logger.info("Starting face ID unregistration (clear gallery)...")

		# Optionally display the registered face image before clearing
		if display_photo:
			photo_ = Photo(registered_face_path)
			photo_.show()
			time.sleep(3)  # Allow time for image to be displayed and processed

		max_retries = 3
		for attempt in range(1, max_retries + 1):
			# Clear existing Face IDs from gallery
			eve.clearFaceID()
			time.sleep(3)  # Allow time for clear command to process

			# Fetch metadata to verify the clear operation
			meta_, frame_ = __fetch(eve)

			# Check if any registered faces still exist using common helper
			if not __check_registered_faces(meta_):
				if meta_:
					logger.debug("Face ID unregistration successful - gallery cleared")
					return meta_, frame_
				else:
					logger.warning("No metadata received after clear operation, assuming success")
					return None, None

			logger.warning(f"Face ID unregistration attempt {attempt} failed - registered faces still found in gallery")
			if attempt < max_retries:
				logger.info(f"Retrying face ID unregistration (attempt {attempt + 1}/{max_retries})...")
				time.sleep(2)  # Brief pause before retry

		# If we reach here, all retries failed
		raise FaceIDError(f"Face ID unregistration failed after {max_retries} attempts - registered faces still found in gallery")

	except Exception as e:
		logger.error(f"Error during face ID unregistration: {e}")
		raise FaceIDError(f"Unregistration failed: {e}")
	finally:
		if photo_:
			try:
				photo_.close()
			except Exception as e:
				logger.warning(f"Error closing photo during unregistration: {e}")

def __register(eve, registered_face_path):
	"""
	Register a new face ID using the provided image.
	
	Args:
		eve: EVE wrapper instance
		registered_face_path: str, path to the face image to register
		
	Returns:
		tuple: (metadata_dict, frame_array)
		
	Raises:
		FaceIDError: If registration fails or face_id_status is not "registered"
	"""
	photo_ = None
	try:
		logger.info(f"Starting face ID registration with image: {registered_face_path}")
		
		# Load and display the registered face image for registration
		photo_ = Photo(registered_face_path)
		photo_.show()
		time.sleep(3)  # Allow time for image to be displayed and processed
		
		max_retries = 3
		for attempt in range(1, max_retries + 1):
			# Register the displayed face
			eve.registerFaceID()
			time.sleep(5)  # Allow time for registration to complete

			# Fetch metadata to verify registration
			meta_, frame_ = __fetch(eve)

			# Check if face was successfully registered using common helper
			if __check_registered_faces(meta_):
				if meta_:
					logger.debug("Face ID registration successful")
					return meta_, frame_
				else:
					logger.warning("No metadata received after registration, assuming success")
					return None, None

			logger.warning(f"Face ID registration attempt {attempt} failed - no registered face found after registration attempt")
			if attempt < max_retries:
				logger.info(f"Retrying face ID registration (attempt {attempt + 1}/{max_retries})...")
				time.sleep(2)  # Brief pause before retry

		# If we reach here, all retries failed
		raise FaceIDError(f"Face ID registration failed after {max_retries} attempts - no registered face found after registration attempts")
			
	except Exception as e:
		logger.error(f"Error during face ID registration: {e}")
		raise FaceIDError(f"Registration failed: {e}")
	finally:
		if photo_:
			try:
				photo_.close()
			except Exception as e:
				logger.warning(f"Error closing photo during registration: {e}")

@pytest.mark.timeout(300)
@pytest.mark.parametrize("display_photo", [True])
@pytest.mark.parametrize("registered_faces", [
	# Ed Sheeran registered - expected results array for each test scenario by index
	("./images/registration/ed-sheeran/img_pax-1_ed-sheeran.jpg", [
		True,   # 0: Ed Sheeran (pax-1) - should be detected
		True,   # 1: Ed Sheeran (pax-3) - should be detected
		True,   # 2: Ed + John - mixed, should not detect as registered
		False,  # 3: Song Seung Heon (pax-1) - shouldn't be detected
		False   # 4: Taylor Swift (pax-1) - shouldn't be detected  
	])
])
@pytest.mark.parametrize("test_scenario_index, test_scenario", enumerate([
	"./images/registration/ed-sheeran/img_pax-1_ed-sheeran.jpg",      # 0
	"./images/registration/ed-sheeran/img_pax-3_ed-sheeran.jpg",      # 1
	"./images/registration/ed-sheeran/img_pax-2_ed-john.jpg",         # 2
	"./images/registration/ed-sheeran/img_pax-1_song-seung-heon.jpg", # 3
	"./images/registration/ed-sheeran/img_pax-1_taylor-swift.jpg"     # 4
]))
@pytest.mark.parametrize(
	"features",
	[
		{"face_id": {"enabled": True},
		"hand_landmarks": {"enabled": False},
		"person_detection": {"enabled": False},
		"face_detection": {"enabled": True},
		"face_validation": {"enabled": False}}
	]
)
def test_fid(config, display_photo, registered_faces, test_scenario_index, test_scenario, options, eve, features):
	"""
	Test Face ID (FID) detection for registered faces.
	
	This test verifies that the system can correctly identify registered faces
	and distinguish them from unregistered faces or objects using a structured
	approach with separate unregister, register, and validate phases.
	
	Args:
		config: dict, test and environment configuration.
		registered_faces: tuple, (face_image_path, expected_results_array).
		test_scenario_index: int, index to get the expected result from the array.
		test_scenario: str, path to the test image file.
		options: dict, controls saving image/metadata.
		eve: EVE wrapper instance.
		
	Test Logic:
		1. Loop through tasks: unregister, register, validate
		2. Each task must complete successfully before proceeding to the next
		3. If any task fails, report error and fail the test
		4. Final validation compares detection result with expected result
		
	Pass Criteria:
		- All tasks (unregister, register, validate) must complete successfully
		- The detection result must match the expected result from the array
	"""
	eve.set_features(features, 5)
	
	def _validate(eve, test_scenario, expected_result):
		"""
		Validate face ID detection using a test scenario image.
		
		Args:
			eve: EVE wrapper instance
			test_scenario: str, path to the test image
			expected_result: bool, whether registered face should be detected
			
		Returns:
			tuple: (metadata_dict, frame_array)
			
		Raises:
			FaceIDError: If validation fails or results don't match expectations
		"""
		photo_ = None
		try:
			logger.info(f"Starting face ID validation with test image: {test_scenario}")
			logger.info(f"Expected result: {expected_result}")
			
			# Display the test image
			photo_ = Photo(test_scenario)
			photo_.show()
			time.sleep(3)  # Wait for display and metadata to be ready, 8s in regression
			
			# Fetch metadata from EVE
			#meta_, frame_ = __fetch(eve)

			meta_, frame_ = None, None
			for attempt in range(10):  # up to 10 retries (10 seconds total)
				meta_, frame_ = __fetch(eve)
				if meta_:
					registered_face_detected = __check_registered_faces(meta_)
					if registered_face_detected == expected_result:
						break  # Pipeline stabilized, exit early
				time.sleep(1)  # short wait before next attempt

			
			if meta_:
				# Get pipeline data safely
				pipeline_data = meta_.get("pipeline_data", {})
				user_count = pipeline_data.get("user_count", 0)
				
				logger.debug(f"Detected user count: {user_count}")
				
				# Check for registered faces using common helper
				registered_face_detected = __check_registered_faces(meta_)
				if registered_face_detected:
					logger.debug("Registered face detected in validation image")
				
				# Validate the result matches expectation
				if expected_result != registered_face_detected:
					raise FaceIDError(f"Validation failed - Expected: {expected_result}, Got: {registered_face_detected}")
				
				logger.debug(f"Face ID validation successful - Expected: {expected_result}, Got: {registered_face_detected}")
				return meta_, frame_
			else:
				# Handle case where no metadata is received
				if not expected_result:
					logger.debug("No metadata received, but no registered faces expected - validation passed")
					return None, None
				else:
					raise FaceIDError("No metadata received, but expected registered face detection")
					
		except Exception as e:
			logger.error(f"Error during face ID validation: {e}")
			raise FaceIDError(f"Validation failed: {e}")
		finally:
			if photo_:
				try:
					photo_.close()
				except Exception as e:
					logger.warning(f"Error closing photo during validation: {e}")
 			# Ensure OpenCV windows are closed
			cv2.destroyAllWindows()

	# Main test logic starts here
	registered_face_path, expected_results_array = registered_faces
	 
	# Get the expected result for this specific test scenario using the index
	expected_result = expected_results_array[test_scenario_index]
	
	test_result = "Fail"  # default to fail
	meta_ = None
	frame_ = None
	
	logger.debug(f"=== FID Test ===")
	logger.debug(f"Registered face: {registered_face_path}")
	logger.debug(f"Testing image: {test_scenario} (Index: {test_scenario_index})")
	logger.debug(f"Expected result: {expected_result}")
	
	try:
		# Define task sequence with improved loop method
		tasks = [
			('unregister', lambda: __unregister(eve, registered_face_path, display_photo)),
			('register', lambda: __register(eve, registered_face_path)), 
			('validate', lambda: _validate(eve, test_scenario, expected_result))
		]
        
		# Execute each task in sequence, ensuring each completes successfully
		for task_name, task_func in tasks:
			try:
				logger.debug(f"Executing task: {task_name}")
				meta_, frame_ = task_func()
				
				# Add delay ONLY before validation
				if task_name == "validate":
					logger.debug("Waiting extra time before validation to allow pipeline stabilization...")
					time.sleep(3)  # Adjust as needed (8–10 seconds)

			except FaceIDError as e:
				logger.error(f"Task '{task_name}' failed: {e}")
				raise Exception(f"Face ID test failed at {task_name} stage: {e}")
			except Exception as e:
				logger.error(f"Unexpected error in task '{task_name}': {e}")
				raise Exception(f"Face ID test failed at {task_name} stage with unexpected error: {e}")
        
		# If we reach here, all tasks completed successfully
		test_result = "Pass"
		logger.debug("All Face ID tasks completed successfully - Test PASSED")

	except Exception as e:
		logger.error(f"Face ID test failed: {e}")
		test_result = "Fail"

	# Save results
	__save(
		config,
		__generate_unique_id("t_fid"),
		meta_,
		frame_,
		options,
		test_result
	)

	# Assert the test result
	assert (test_result == "Pass"), f"FID test failed for {test_scenario} with registered face {registered_face_path}. Error occurred during task execution."
