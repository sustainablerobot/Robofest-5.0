import cv2
import mediapipe as mp
import numpy as np
import joblib
from collections import deque
import os

class PoseProcessor:
    """
    Uses MediaPipe Pose to extract body landmarks and classifies gestures
    using a custom 16-feature TFLite model with feature scaling.
    """
    def __init__(self, model_path='gesture_model1.tflite', scaler_path='scaler.save'):
        # 1. Init MediaPipe Pose
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7,
            model_complexity=0
        )
        self.mp_draw = mp.solutions.drawing_utils
        
        # 2. Init OpenCV DNN for TFLite inference (Lightweight)
        try:
            self.net = cv2.dnn.readNetFromTFLite(model_path)
            print(f"[SYSTEM] OpenCV DNN loaded TFLite model: {model_path}")
        except Exception as e:
            print(f"[ERROR] Failed to load model via OpenCV: {e}")
            self.net = None
        
        # 3. Load Scaler
        self.scaler = None
        if os.path.exists(scaler_path):
            try:
                # Check for dummy
                fsize = os.path.getsize(scaler_path)
                if fsize < 1000:
                    print(f"[CRITICAL WARNING] '{scaler_path}' looks like a DUMMY file ({fsize} bytes). Gestures will fail!")
                
                self.scaler = joblib.load(scaler_path)
                print(f"[SYSTEM] Loaded feature scaler from: {scaler_path}")
            except Exception as e:
                print(f"[WARNING] Failed to load scaler: {e}")
        else:
            print(f"[WARNING] Scaler file {scaler_path} not found. Running without scaling.")

        # 4. Prediction Smoothing (Per-Person ID)
        self.buffers = {} 
        
        self.gesture_names = {
            0: "ARM", 1: "TAKEOFF", 2: "STOP", 3: "SWARM", 4: "NO_GESTURE", 5: "NAMASTE"
        }
        

    def extract_features_with_flip(self, landmarks, roi_bbox, frame_shape):
        """
        Calculates 16 features (8 landmarks * 2 [x,y]) in the FLIPPED coordinate space
        matching the user's training pipeline.
        """
        lm = landmarks.landmark
        fh, fw = frame_shape[:2]
        rx1, ry1, rx2, ry2 = roi_bbox
        rw, rh = rx2 - rx1, ry2 - ry1

        # Flip math: In flipped full frame, ROI starts at fw - rx2
        rx1_f = fw - rx2
        
        def to_flipped_full_frame(l_norm_x, l_norm_y):
            # l_norm_x is in flipped crop from MediaPipe
            abs_x_f = l_norm_x * rw + rx1_f
            abs_y = l_norm_y * rh + ry1
            return abs_x_f / fw, abs_y / fh

        ls_raw = lm[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        rs_raw = lm[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        
        ls_x_f, ls_y = to_flipped_full_frame(ls_raw.x, ls_raw.y)
        rs_x_f, rs_y = to_flipped_full_frame(rs_raw.x, rs_raw.y)

        center_x_f = (ls_x_f + rs_x_f) / 2
        center_y_f = (ls_y + rs_y) / 2

        target_ids = [
            self.mp_pose.PoseLandmark.LEFT_SHOULDER.value,
            self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value,
            self.mp_pose.PoseLandmark.LEFT_ELBOW.value,
            self.mp_pose.PoseLandmark.RIGHT_ELBOW.value,
            self.mp_pose.PoseLandmark.LEFT_WRIST.value,
            self.mp_pose.PoseLandmark.RIGHT_WRIST.value,
            self.mp_pose.PoseLandmark.LEFT_HIP.value,
            self.mp_pose.PoseLandmark.RIGHT_HIP.value
        ]

        features = []
        for i in target_ids:
            l_raw = lm[i]
            x_f, y = to_flipped_full_frame(l_raw.x, l_raw.y)
            features.append(x_f - center_x_f)
            features.append(y - center_y_f)

        features = np.array(features, dtype=np.float32).reshape(1, 16)
        if self.scaler is not None:
            features = self.scaler.transform(features)
        return features

    def process_roi(self, frame, roi_bbox, tracker_id=999):
        """
        Processes the pilot's ROI using MediaPipe Pose.
        Returns: crop, landmarks, and gesture label (with per-ID smoothing).
        """
        x1, y1, x2, y2 = roi_bbox
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return crop, None, "None"
            
        # Flip crop to match training (Horizontal mirror)
        # Note: We flip the crop, run pose, then landmarks will be relative to flipped crop.
        # But we must be careful with LEFT/RIGHT if the model expects them flipped.
        # The user's script flips BEFORE pose.process().
        crop_flipped = cv2.flip(crop, 1)
        crop_rgb = cv2.cvtColor(crop_flipped, cv2.COLOR_BGR2RGB)
        result = self.pose.process(crop_rgb)
        
        gesture_label = "None"
        if result.pose_landmarks:
            # Re-map landmarks back to full frame
            # Since we flipped the crop, result.pose_landmarks.landmark[i].x is flipped.
            # We don't really need to un-flip them if the model was trained on flipped images.
            # But the 'roi_bbox' is in un-flipped frame coordinates.
            # This could get messy. Let's simplify and NOT flip at first, 
            # as MediaPipe is usually mirror-invariant for body Pose.
            
            # RE-EVALUATION: The user flips for the model. 
            # If I run Pose on un-flipped crop, landmarks are 'native'.
            # If I then calculate features (x - center_x), the SIGN of X will be swapped.
            # I will flip the crop to match the user's training flow exactly.
            
            # To map back to full-frame, we need to know the 'x' in un-flipped space.
            # x_unflipped = 1.0 - x_flipped (within the crop)
            
            # Map landmarks back to full frame coordinates
            features = self.extract_features_with_flip(result.pose_landmarks, roi_bbox, frame.shape)
            
            # Predict
            if self.net:
                self.net.setInput(features.astype(np.float32))
                output = self.net.forward()[0] # cv2 dnn returns [1, 6] usually
                
                confidence = np.max(output)
                pred = np.argmax(output)
                
                # Active debugging for User
                if confidence > 0.4: # Log low confidence too
                     pred_name = self.gesture_names.get(pred, "???")
                     print(f"[GESTURE DBG] ID {tracker_id}: {pred_name} (Conf: {confidence:.2f})")
                
                if tracker_id not in self.buffers:
                    self.buffers[tracker_id] = deque(maxlen=5)
                
                if confidence > 0.75:
                    self.buffers[tracker_id].append(pred)
                    if len(self.buffers[tracker_id]) >= 3:
                        final_pred = max(set(self.buffers[tracker_id]), key=list(self.buffers[tracker_id]).count)
                        gesture_label = self.gesture_names.get(final_pred, "NO_GESTURE")
                    else:
                        gesture_label = self.gesture_names.get(pred, "NO_GESTURE")
                else:
                    gesture_label = "NO_GESTURE"
                
        return crop, result.pose_landmarks, gesture_label

    def draw_landmarks(self, frame, pose_landmarks, roi_bbox):
        """
        Draws landmarks onto the main frame, adjusting coordinates by the ROI offset.
        Note: landmarks are originally from a FLIPPED crop. We must UNFLIP for display.
        """
        if not pose_landmarks:
            return frame
            
        x1, y1, x2, y2 = roi_bbox
        cw, ch = x2 - x1, y2 - y1
        
        for lm in pose_landmarks.landmark:
            # Unflip x: 1.0 - lm.x (since Display is unflipped)
            px = int((1.0 - lm.x) * cw) + x1
            py = int(lm.y * ch) + y1
            cv2.circle(frame, (px, py), 3, (0, 255, 0), -1)
            
        return frame
