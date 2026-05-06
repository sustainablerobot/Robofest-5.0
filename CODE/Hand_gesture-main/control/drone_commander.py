class DroneCommander:
    """
    Translates gesture states (e.g., thumb up, open palm, closed fist) 
    into directional commands or statuses.
    """
    def __init__(self, mode="mock"):
        self.mode = mode
        self.state = "hover" # "hover", "forward", "backward", "left", "right"
        print(f"Initialized DroneCommander in {self.mode} mode.")

    def parse_gestures(self, gesture_label):
        """
        Translates a categorical gesture label into a specific control vector.
        """
        self.state = gesture_label
        
        # User defined 6 classes
        if gesture_label == "ARM":
            print(">>> COMM: ARMING DRONE")
            return self._hover()
        elif gesture_label == "TAKEOFF":
            print(">>> COMM: TAKEOFF INITIATED")
            return self._send_command(0.0, 0.0, 0.5, 0.0) # Vertical climb
        elif gesture_label == "STOP":
            return self._hover()
        elif gesture_label == "SWARM":
            print(">>> COMM: TRIGGERING SWARM BEHAVIOR")
            return self._hover()
        elif gesture_label == "NAMASTE": # Used for locking
            return self._hover()
        elif gesture_label == "NO_GESTURE":
            return self._hover()
        else:
            return self._hover()

    def _hover(self):
        self.state = "hover"
        return self._send_command(0.0, 0.0, 0.0, 0.0)

    def trigger_failsafe(self):
        """
        Called when PilotTracker loses ID track for > 1.5s.
        """
        print(">>> COMM: Failsafe triggered. Halting velocity.")
        return self._hover()

    def _send_command(self, vx, vy, vz, yaw):
        if self.mode == "mock":
            # print(f"Drone Command V=({vx},{vy},{vz}) Y={yaw}")
            pass
        elif self.mode == "mavlink":
            # Send to PyMavlink
            pass
        return self.state
