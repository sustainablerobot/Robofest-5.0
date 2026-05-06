import math

def interpolate_path(path, step=1):

    new_path = []

    for i in range(len(path) - 1):

        x1, y1 = path[i]
        x2, y2 = path[i + 1]

        dist = math.hypot(x2 - x1, y2 - y1)

        steps = int(dist / step) + 1

        for j in range(steps):

            t = j / steps

            lat = x1 + (x2 - x1) * t
            lon = y1 + (y2 - y1) * t

            new_path.append((lat, lon))

    new_path.append(path[-1])

    return new_path