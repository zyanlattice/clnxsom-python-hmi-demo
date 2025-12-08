import tkinter as tk
import cv2
import time
import logging

# Use the same logger approach as tapp.py - leverages conftest.py configuration
logger = logging.getLogger(__name__)

class Photo:
    """
    A class to display and save images using OpenCV (cv2).
    """
    def __init__(self, image_path=None):
        self.image = None
        self.window_names = set()  # Track windows created by this instance
        if image_path:
            
            self.load(image_path)

    def load(self, image_path):
        """Load an image from a file path."""
        self.image = cv2.imread(image_path)
        if self.image is None:
            raise ValueError(f"Failed to load image from {image_path}")

    def show(self, window_name="Photo", timeout_seconds=5):
        """
        Display the image in a window with reliable error handling and verification.
        Attempts to ensure the image is actually displayed on screen.
        """
        if self.image is None:
            raise ValueError("No image loaded to display.")

        screen_res = self._get_screen_resolution()
        img_h, img_w = self.image.shape[:2]
        # Scale image to fit full screen height, width by aspect ratio
        scale = screen_res[1] / img_h
        new_h = screen_res[1]
        new_w = int(img_w * scale)
        new_w = int(img_w * scale)
        resized_img = cv2.resize(self.image, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Safely close any existing windows with same name
        try:
            # Check if window exists before trying to destroy it
            window_property = cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE)
            if window_property >= 0:  # Window exists
                cv2.destroyWindow(window_name)
                # Remove from tracking since we're about to recreate it
                self.window_names.discard(window_name)
        except cv2.error:
            # Window doesn't exist, which is fine
            pass
        
        # Wait for window cleanup
        for _ in range(5):
            cv2.waitKey(10)
        
        success = False
        attempts = 0
        max_attempts = 5
        
        while not success and attempts < max_attempts:
            try:
                # Create window
                cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
                cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                
                # Track this window so we can close it later
                self.window_names.add(window_name)
                
                # Display image
                cv2.imshow(window_name, resized_img)
                
                # Verify window exists and is displaying
                window_property = cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE)
                if window_property > 0:  # Window is visible
                    success = True
                    # Additional refreshes to ensure content is drawn
                    for _ in range(5):
                        cv2.waitKey(20)
                else:
                    attempts += 1
                    time.sleep(0.1)  # Brief pause before retry
            except Exception as e:
                attempts += 1
                print(f"Display attempt {attempts} failed: {e}")
                time.sleep(0.1)
        
        if not success:
            raise RuntimeError(f"Failed to display image after {max_attempts} attempts")
        
        return success

    # _center_window removed for cross-platform compatibility
    def _get_screen_resolution(self):
        """Get the screen resolution (width, height) using Tkinter (cross-platform)."""
        try:
            root = tk.Tk()
            root.withdraw()  # Hide the window immediately
            root.update_idletasks()  # Ensure window is properly initialized
            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            root.quit()  # Properly quit before destroy
            root.destroy()
            # Small delay to ensure Tkinter cleanup completes
            import time
            time.sleep(0.01)
            return (screen_w, screen_h)
        except Exception:
            # Fallback to 1920x1080 if detection fails
            return (1920, 1080)

    def hide(self, window_name="Photo"):
        """Hide the image window if it is open."""
        try:
            # Check if window exists before trying to destroy it
            window_property = cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE)
            if window_property >= 0:  # Window exists
                cv2.destroyWindow(window_name)
                cv2.waitKey(1)  # Allow time for window destruction
                
                # Remove from our tracking set since we closed it
                self.window_names.discard(window_name)
        except cv2.error:
            # Window doesn't exist, remove from tracking if it was there
            self.window_names.discard(window_name)
            pass

    def close(self):
        """Close only the OpenCV windows created by this Photo instance."""
        try:
            # Close only windows created by this instance
            for window_name in self.window_names.copy():  # Use copy to avoid modification during iteration
                try:
                    # Check if window still exists before trying to destroy it
                    window_property = cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE)
                    if window_property >= 0:  # Window exists
                        cv2.destroyWindow(window_name)
                        logger.debug(f"Closed window: {window_name}")
                    
                    # Remove from our tracking set
                    self.window_names.discard(window_name)
                    
                except cv2.error as e:
                    # Window might have been closed already, remove from tracking
                    self.window_names.discard(window_name)
                    logger.debug(f"Window {window_name} was already closed: {e}")
                except Exception as e:
                    logger.warning(f"Error closing window {window_name}: {e}")
                    # Still remove from tracking to avoid future issues
                    self.window_names.discard(window_name)
            
            # Process any pending CV2 events for the windows we closed
            # This is much more targeted than cv2.destroyAllWindows()
            for _ in range(5):
                cv2.waitKey(1)
            
        except Exception as e:
            logger.warning(f"Unexpected error during Photo window cleanup: {e}")
        
        # Clear the image reference to free memory
        self.image = None

if __name__ == "__main__":
    import sys

    print("Photo class local test")
    if len(sys.argv) < 2:
        print("Usage: python photo.py <image_path>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    photo = Photo(image_path)
    photo.show()
    
    print("Press 'Enter' in the terminal to exit ...")
    input()
    photo.close()
    