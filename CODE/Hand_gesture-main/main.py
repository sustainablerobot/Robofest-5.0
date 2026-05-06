import cv2
import time

from vision.camera import ThreadedCamera
from detection.person_detector import PersonDetector
from tracking.pilot_tracker import PilotTracker
from gesture.hand_processor import PoseProcessor
from control.drone_commander import DroneCommander

import os

def main():
    print("=== Antigravity Pilot-Centric Drone Control System ===")
    
    # 1. Start Camera Frame Pre-processing (640x480)
    cam = ThreadedCamera(src=0, width=640, height=480)
    time.sleep(1) # Camera warmup
    
    # PERFORMANCE OPTIMIZATION: Check for NCNN folder first for Pi 5 speed
    model_path = "yolov8n_ncnn_model" if os.path.exists("yolov8n_ncnn_model") else "yolov8n.pt"
    
    # 2. Init YOLOv8n (Standard or NCNN)
    detector = PersonDetector(model_path=model_path, input_size=(640, 640))
    
    # 3. Init ByteTrack / Pilot tracker logic
    tracker = PilotTracker(frame_height=480, min_height_ratio=0.15)
    
    # 4. Init MediaPipe Pose (Lite model on Pi 5)
    pose_processor = PoseProcessor()
    
    # 5. Init Drone Commander (MAVLink logic)
    commander = DroneCommander(mode="mock")

    print(f"[SYSTEM] Engine: {'NCNN' if detector.is_ncnn else 'PyTorch'}")
    print("[SYSTEM] All modules loaded. Starting main loop...")
    
    frame_count = 0
    start_time = time.time()
    
    # PERFORMANCE OPTIMIZATION: Run YOLO only every N frames
    DETECTION_INTERVAL = 3 
    last_bboxes = []
    last_scores = []
    
    last_pilot_id = None
    last_lock_time = 0
    COMMAND_HOLD_TIME = 5.0 # Seconds to wait after lock before accepting flight commands

    try:
        while True:
            # Step 1: Grab Frame
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue
                
            display_frame = frame.copy()
            
            # Step 2: Adaptive YOLO Detection
            if frame_count % DETECTION_INTERVAL == 0:
                bboxes, scores = detector.detect(frame)
                last_bboxes, last_scores = bboxes, scores
            else:
                bboxes, scores = [], []
                
            # Step 3: ByteTrack Pilot Identification
            tracked_objs, frame = tracker.update(frame, bboxes, scores)
            
            # Draw tracking boxes
            for obj in tracked_objs:
                rx1, ry1, rx2, ry2 = obj['bbox']
                color = (255, 255, 0) if obj['id'] == tracker.pilot_id else (0, 0, 255)
                cv2.rectangle(display_frame, (rx1, ry1), (rx2, ry2), color, 1)
            
            # Step 3.5: If Pilot isn't locked, search for Master using "NAMASTE" gesture
            crowd_gestures = {}
            if tracker.pilot_id is None:
                # 1. First Pass: Gather all gestures
                for obj in tracked_objs:
                    _, _, gesture = pose_processor.process_roi(frame, obj['bbox'], tracker_id=obj['id'])
                    if gesture != "None" and gesture != "NO_GESTURE":
                        crowd_gestures[obj['id']] = gesture

                # 2. Update Tracker (This sets 'lock_progress' in tracked_objs)
                pilot_bbox, is_locked = tracker.get_pilot_roi(tracked_objs, frame, crowd_gesture_data=crowd_gestures)

                # 3. Second Pass: Draw search UI
                for obj in tracked_objs:
                    gesture = crowd_gestures.get(obj['id'], "None")
                    rx1, ry1, rx2, ry2 = obj['bbox']
                    
                    if gesture != "None":
                        cv2.rectangle(display_frame, (rx1, ry1), (rx2, ry2), (0, 255, 0), 1)
                        cv2.putText(display_frame, f"G: {gesture}", (rx1, ry1-10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                        
                        # Show LOCKING progress correctly now!
                        if 'lock_progress' in obj:
                            progress = obj['lock_progress']
                            # MOVE TO TOP for visibility: (rx1, ry1-30)
                            cv2.putText(display_frame, f"LOCKING: {max(0, 5.0 - progress):.1f}s", (rx1, ry1-30), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                cv2.putText(display_frame, "SEARCHING FOR MASTER (Hold NAMASTE 5s)", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            else:
                # If already locked, just get the ROI
                pilot_bbox, is_locked = tracker.get_pilot_roi(tracked_objs, frame)

            # Step 4: Logic for Locked Pilot
            if is_locked and pilot_bbox is not None:
                if tracker.pilot_id != last_pilot_id:
                    print(f"[SYSTEM] Pilot {tracker.pilot_id} LOCKED.")
                    last_pilot_id = tracker.pilot_id
                    current_command_gesture = "None"
                    command_gesture_start = 0

                x1, y1, x2, y2 = pilot_bbox
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 0, 0), 4) # Thick Blue
                cv2.putText(display_frame, f"LOCKED PILOT {tracker.pilot_id}", (x1, max(20, y1-10)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
                
                # ROI Cropping & Gesture Recognition
                crop, pose_lms, gesture = pose_processor.process_roi(frame, pilot_bbox, tracker_id=tracker.pilot_id)
                if pose_lms:
                    display_frame = pose_processor.draw_landmarks(display_frame, pose_lms, pilot_bbox)
                
                # Step 5: Command Translation with SUSTAIN (Matches user 5s request)
                SUSTAIN_TIME = 5.0 
                
                if gesture != "None" and gesture != "NO_GESTURE":
                    if gesture != current_command_gesture:
                        current_command_gesture = gesture
                        command_gesture_start = time.time()
                    
                    elapsed = time.time() - command_gesture_start
                    if elapsed >= SUSTAIN_TIME:
                        cmd_state = commander.parse_gestures(gesture)
                        cv2.putText(display_frame, f"CMD: {cmd_state}", (10, 30), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    else:
                        cmd_state = "SUSTAIN..."
                        cv2.putText(display_frame, f"{gesture}: {SUSTAIN_TIME - elapsed:.1f}s", (10, 30), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 2)
                else:
                    current_command_gesture = "None"
                    cmd_state = commander.parse_gestures("STOP")
                    cv2.putText(display_frame, "ACTIVE (No Gesture)", (10, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            else:
                last_pilot_id = None
                cmd_state = commander.trigger_failsafe()
                cv2.putText(display_frame, "FAILSAFE: NO PILOT", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

            # Debug display (remove in pure headless operations)
            cv2.imshow("Antigravity Pilot Interface", display_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
            # FPS tracking
            frame_count += 1
            if frame_count % 30 == 0:
                fps = frame_count / (time.time() - start_time)
                print(f"[METRICS] Pipeline FPS: {fps:.2f}")

    except KeyboardInterrupt:
        print("[SYSTEM] Caught interrupt. Shutting down cleanly.")
    
    finally:
        cam.stop()
        cv2.destroyAllWindows()
        print("[SYSTEM] Goodbye.")

if __name__ == "__main__":
    main()
