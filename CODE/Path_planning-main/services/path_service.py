from __future__ import annotations

import heapq
import math

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union


def _build_local_transformers(origin_lat: float, origin_lon: float) -> tuple[Transformer, Transformer]:
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={origin_lat} +lon_0={origin_lon} +x_0=0 +y_0=0 +units=m +datum=WGS84"
    )
    to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    to_geo = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    return to_local, to_geo


def _latlng_to_local_point(lat: float, lon: float, to_local: Transformer) -> Point:
    x, y = to_local.transform(lon, lat)
    return Point(float(x), float(y))


def _latlngs_to_local_polygon(latlngs: list[list[float]], to_local: Transformer) -> Polygon:
    coords: list[tuple[float, float]] = []
    for lat, lon in latlngs:
        x, y = to_local.transform(lon, lat)
        coords.append((float(x), float(y)))
    return Polygon(coords)


def _local_path_to_latlng(path_xy: list[tuple[float, float]], to_geo: Transformer) -> list[list[float]]:
    latlng_path: list[list[float]] = []
    for x, y in path_xy:
        lon, lat = to_geo.transform(x, y)
        latlng_path.append([float(lat), float(lon)])
    return latlng_path


def _nearest_valid_node(target: tuple[int, int], is_valid, max_radius: int) -> tuple[int, int]:
    tx, ty = target
    if is_valid(target):
        return target

    for radius in range(1, max_radius + 1):
        best_node: tuple[int, int] | None = None
        best_dist = float("inf")

        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue

                node = (tx + dx, ty + dy)
                if not is_valid(node):
                    continue

                dist = dx * dx + dy * dy
                if dist < best_dist:
                    best_dist = dist
                    best_node = node

        if best_node is not None:
            return best_node

    raise ValueError("Could not place start/goal on valid free space.")


def _astar_path(
    rectangle: Polygon,
    obstacles,
    start_pt: Point,
    goal_pt: Point,
    resolution_m: float,
) -> list[tuple[float, float]]:
    min_x, min_y, max_x, max_y = rectangle.bounds

    def node_to_xy(node: tuple[int, int]) -> tuple[float, float]:
        return min_x + node[0] * resolution_m, min_y + node[1] * resolution_m

    def xy_to_node(x: float, y: float) -> tuple[int, int]:
        return int(round((x - min_x) / resolution_m)), int(round((y - min_y) / resolution_m))

    obstacle_shape = None
    if obstacles is not None and not obstacles.is_empty:
        obstacle_shape = obstacles

    valid_cache: dict[tuple[int, int], bool] = {}

    def is_valid(node: tuple[int, int]) -> bool:
        if node in valid_cache:
            return valid_cache[node]

        point = Point(*node_to_xy(node))
        if not rectangle.covers(point):
            valid_cache[node] = False
            return False

        if obstacle_shape is not None and obstacle_shape.intersects(point):
            valid_cache[node] = False
            return False

        valid_cache[node] = True
        return True

    edge_cache: dict[tuple[tuple[int, int], tuple[int, int]], bool] = {}

    def is_edge_valid(a: tuple[int, int], b: tuple[int, int]) -> bool:
        key = (a, b) if a <= b else (b, a)
        if key in edge_cache:
            return edge_cache[key]

        segment = LineString([node_to_xy(a), node_to_xy(b)])
        if not rectangle.covers(segment):
            edge_cache[key] = False
            return False

        if obstacle_shape is not None and obstacle_shape.intersects(segment):
            edge_cache[key] = False
            return False

        edge_cache[key] = True
        return True

    start_node = xy_to_node(start_pt.x, start_pt.y)
    goal_node = xy_to_node(goal_pt.x, goal_pt.y)

    span = max(max_x - min_x, max_y - min_y)
    max_radius = int(max(30, math.ceil(span / resolution_m) + 5))
    start_node = _nearest_valid_node(start_node, is_valid, max_radius)
    goal_node = _nearest_valid_node(goal_node, is_valid, max_radius)

    moves = [
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    ]

    def heuristic(a: tuple[int, int], b: tuple[int, int]) -> float:
        return float(np.hypot(b[0] - a[0], b[1] - a[1]))

    open_heap: list[tuple[float, float, tuple[int, int]]] = []
    heapq.heappush(open_heap, (heuristic(start_node, goal_node), 0.0, start_node))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {start_node: 0.0}

    while open_heap:
        _, current_g, current = heapq.heappop(open_heap)
        if current_g > g_score.get(current, float("inf")) + 1e-12:
            continue

        if current == goal_node:
            break

        for dx, dy in moves:
            neighbor = (current[0] + dx, current[1] + dy)
            if not is_valid(neighbor):
                continue
            if not is_edge_valid(current, neighbor):
                continue

            step_cost = float(np.hypot(dx, dy)) * resolution_m
            tentative_g = current_g + step_cost
            if tentative_g >= g_score.get(neighbor, float("inf")):
                continue

            came_from[neighbor] = current
            g_score[neighbor] = tentative_g
            f_score = tentative_g + heuristic(neighbor, goal_node) * resolution_m
            heapq.heappush(open_heap, (f_score, tentative_g, neighbor))

    if goal_node not in came_from and goal_node != start_node:
        raise ValueError("No safe path found. Move start/goal or mine placement.")

    path_nodes = [goal_node]
    while path_nodes[-1] != start_node:
        path_nodes.append(came_from[path_nodes[-1]])
    path_nodes.reverse()

    return [node_to_xy(node) for node in path_nodes]


def compute_path(
    start: list[float],
    goal: list[float],
    mines: list[list[float]],
    polygon: list[list[float]] | None,
    rectangle: list[list[float]] | None,
    grid_resolution: float,
    mine_radius: float,
) -> list[list[float]]:
    if polygon and len(polygon) >= 3:
        area_latlngs = polygon
        area_label = "selected area"
    elif rectangle and len(rectangle) >= 4:
        area_latlngs = rectangle
        area_label = "selected rectangle"
    else:
        raise ValueError("Search area is invalid.")

    origin_lat, origin_lon = area_latlngs[0]
    to_local, to_geo = _build_local_transformers(origin_lat, origin_lon)

    area_poly = _latlngs_to_local_polygon(area_latlngs, to_local)
    if not area_poly.is_valid or area_poly.area <= 0:
        raise ValueError("Selected area geometry is invalid.")

    start_pt = _latlng_to_local_point(float(start[0]), float(start[1]), to_local)
    goal_pt = _latlng_to_local_point(float(goal[0]), float(goal[1]), to_local)

    if not area_poly.covers(start_pt) or not area_poly.covers(goal_pt):
        raise ValueError(f"Start and goal must be inside {area_label}.")

    mine_buffers = []
    for mine_lat, mine_lon in mines:
        mine_pt = _latlng_to_local_point(float(mine_lat), float(mine_lon), to_local)
        mine_buffers.append(mine_pt.buffer(float(mine_radius)))

    obstacle_union = unary_union(mine_buffers) if mine_buffers else None
    if obstacle_union is not None and not obstacle_union.is_empty:
        obstacle_union = obstacle_union.buffer(1e-6)

    if obstacle_union is not None:
        if obstacle_union.intersects(start_pt):
            raise ValueError("Start point is inside a mine safety circle.")
        if obstacle_union.intersects(goal_pt):
            raise ValueError("Goal point is inside a mine safety circle.")

    path_xy = _astar_path(area_poly, obstacle_union, start_pt, goal_pt, float(grid_resolution))
    safe_line = LineString(path_xy)

    if obstacle_union is not None and safe_line.intersects(obstacle_union):
        raise ValueError("Computed path intersects mine safety zone.")

    return _local_path_to_latlng(path_xy, to_geo)