import heapq
import math


def heuristic(a, b):

    return math.sqrt(
        (a[0] - b[0]) ** 2 +
        (a[1] - b[1]) ** 2
    )


def astar(start, goal, obstacles):

    open_set = []

    heapq.heappush(open_set, (0, start))

    came_from = {}

    g = {start: 0}

    while open_set:

        _, current = heapq.heappop(open_set)

        if current == goal:
            break

        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:

                neighbor = (
                    current[0] + dx,
                    current[1] + dy
                )

                if neighbor in obstacles:
                    continue

                tentative = g[current] + 1

                if tentative < g.get(neighbor, 9999):

                    g[neighbor] = tentative

                    f = tentative + heuristic(neighbor, goal)

                    heapq.heappush(open_set, (f, neighbor))

                    came_from[neighbor] = current

    path = [goal]

    while path[-1] != start:

        path.append(came_from[path[-1]])

    path.reverse()

    return path