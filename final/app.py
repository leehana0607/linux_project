from flask import Flask, render_template, request
import json
import heapq
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "station_metadata.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    DATA = json.load(f)

LINE_DATA = DATA["line_data"]
STATION_LINES = DATA["station_lines"]
TRANSFER_METADATA = DATA.get("transfer_metadata", {})

LINES = list(LINE_DATA.keys())

STATIONS_BY_LINE = {
    line: [item["station"] for item in stations]
    for line, stations in LINE_DATA.items()
}

LINE_INDEX = {
    line: {station: idx for idx, station in enumerate(stations)}
    for line, stations in STATIONS_BY_LINE.items()
}

STATION_INFO_BY_LINE = {
    line: {item["station"]: item for item in stations}
    for line, stations in LINE_DATA.items()
}

LINE_VALUE_MAP = {
    "1": "1호선",
    "2": "2호선",
    "5": "5호선",
    "7": "7호선",
    "1호선": "1호선",
    "2호선": "2호선",
    "5호선": "5호선",
    "7호선": "7호선",
}

STATIONS_BY_LINE_FOR_UI = {
    "1": STATIONS_BY_LINE.get("1호선", []),
    "2": STATIONS_BY_LINE.get("2호선", []),
    "5": STATIONS_BY_LINE.get("5호선", []),
    "7": STATIONS_BY_LINE.get("7호선", []),
}


def normalize_line(line):
    return LINE_VALUE_MAP.get(line, line)


def node_id(line, station):
    return f"{line}|{station}"


def split_node(node):
    return node.split("|", 1)


def get_direction(line, current_station, next_station):
    """같은 호선에서 다음 역 방향을 기준으로 '종착역 방면'을 계산한다."""
    if line not in LINE_INDEX:
        return ""

    if current_station not in LINE_INDEX[line] or next_station not in LINE_INDEX[line]:
        return ""

    current_idx = LINE_INDEX[line][current_station]
    next_idx = LINE_INDEX[line][next_station]
    stations = STATIONS_BY_LINE[line]

    if next_idx > current_idx:
        return f"{line} {stations[-1]} 방면"
    if next_idx < current_idx:
        return f"{line} {stations[0]} 방면"
    return ""


def transfer_weight(station, user_type):
    """라벨링된 환승역 데이터를 내부 계산에만 사용한다.
    화면에는 혼잡도 점수나 접근성 점수를 출력하지 않는다.
    """
    info = TRANSFER_METADATA.get(station, {})

    # 기본 환승 비용
    weight = 4.0

    # 라벨링 점수가 있으면 환승 비용에 반영
    if info.get("score") is not None:
        weight += float(info["score"]) / 25.0

    if info.get("transfer_penalty") is not None:
        weight += float(info["transfer_penalty"]) / 20.0

    # 엘리베이터 없음은 교통약자에게 큰 불편 요소
    if info.get("has_elevator") == "N":
        if user_type == "휠체어 사용자":
            weight += 8.0
        elif user_type == "유아차 사용자":
            weight += 6.0
        else:
            weight += 4.0

    # 수유실은 유아차 사용자에게만 내부 가중치에서 약간 유리하게 반영
    if user_type == "유아차 사용자" and info.get("has_nursing_room") == "Y":
        weight -= 1.0

    return max(weight, 2.0)


def build_graph(user_type):
    """전체 역 목록을 그래프로 구성한다.
    - 같은 호선의 인접 역은 이동 간선으로 연결
    - 같은 역명이 여러 호선에 있으면 환승 간선으로 연결
    """
    graph = {}

    # 같은 호선 내 인접역 연결
    for line, stations in STATIONS_BY_LINE.items():
        for idx, station in enumerate(stations):
            current = node_id(line, station)
            graph.setdefault(current, [])

            if idx > 0:
                graph[current].append((node_id(line, stations[idx - 1]), 1.0))
            if idx < len(stations) - 1:
                graph[current].append((node_id(line, stations[idx + 1]), 1.0))

    # 환승역 연결
    for station, lines in STATION_LINES.items():
        if len(lines) < 2:
            continue

        cost = transfer_weight(station, user_type)

        for from_line in lines:
            for to_line in lines:
                if from_line == to_line:
                    continue

                start = node_id(from_line, station)
                end = node_id(to_line, station)

                if start in graph and end in graph:
                    graph[start].append((end, cost))

    return graph


def dijkstra(start_node, end_node, user_type):
    graph = build_graph(user_type)

    if start_node not in graph or end_node not in graph:
        return None

    queue = [(0, start_node, [])]
    visited = set()

    while queue:
        cost, current, path = heapq.heappop(queue)

        if current in visited:
            continue
        visited.add(current)

        new_path = path + [current]

        if current == end_node:
            return new_path

        for neighbor, weight in graph.get(current, []):
            if neighbor not in visited:
                heapq.heappush(queue, (cost + weight, neighbor, new_path))

    return None



def get_transfer_stations_from_path(path):
    """경로에서 실제 환승이 발생한 역 이름만 추출한다."""
    parsed = [split_node(node) for node in path]
    transfer_stations = []

    for idx in range(1, len(parsed)):
        prev_line, prev_station = parsed[idx - 1]
        cur_line, cur_station = parsed[idx]

        if prev_station == cur_station and prev_line != cur_line:
            transfer_stations.append(cur_station)

    return transfer_stations


def get_route_station_pairs(path):
    """경로에 포함된 역을 중복 없이 (호선, 역명) 형태로 반환한다."""
    parsed = [split_node(node) for node in path]
    seen = set()
    pairs = []

    for line, station in parsed:
        key = (line, station)
        if key not in seen:
            seen.add(key)
            pairs.append(key)

    return pairs


def get_station_info(line, station):
    """2번째 데이터 기반 station_metadata에서 역별 정보를 가져온다."""
    return STATION_INFO_BY_LINE.get(line, {}).get(station, {})


def get_station_info_any(station):
    """호선이 특정되지 않은 경우 같은 역명에 해당하는 정보를 가져온다."""
    if station in TRANSFER_METADATA:
        return TRANSFER_METADATA.get(station, {})

    for line in LINES:
        info = STATION_INFO_BY_LINE.get(line, {}).get(station)
        if info:
            return info

    return {}


def format_yes_no(value, yes_text="있음", no_text="없음"):
    if value == "Y":
        return yes_text
    if value == "N":
        return no_text
    return "정보 없음"


def format_facility_for_step(line, station):
    """추천 이동 흐름에서 환승역/도착역별 시설 정보를 함께 표시한다."""
    info = get_station_info(line, station) or get_station_info_any(station)

    elevator = format_yes_no(
        info.get("has_elevator"),
        yes_text="있음",
        no_text="없음"
    )

    floor_range = info.get("elevator_floor_range")
    if floor_range not in (None, "", "None"):
        elevator_text = f"엘리베이터: {elevator} ({floor_range})"
    else:
        elevator_text = f"엘리베이터: {elevator}"

    if info.get("has_nursing_room") == "Y":
        nursing_location = info.get("nursing_room_location")
        if nursing_location not in (None, "", "None"):
            nursing_text = f"수유실: 있음 ({nursing_location})"
        else:
            nursing_text = "수유실: 있음"
    else:
        nursing_text = "수유실: 없음"

    return f"<br><span class=\"facility-text\">- {elevator_text}</span><br><span class=\"facility-text\">- {nursing_text}</span>"


def build_detail_infos(path):
    """결과 화면 하단 정보 박스에 넣을 문장을 만든다.
    - 엘리베이터/혼잡도 정보는 선택된 환승 구간을 중심으로 안내한다.
    - 수유실 정보는 전체 경로에 수유실이 포함되어 있을 때 위치까지 표시한다.
    - 주의사항에는 엘리베이터 점검 여부만 표시한다.
    """
    transfer_stations = get_transfer_stations_from_path(path)
    route_pairs = get_route_station_pairs(path)

    elevator_lines = []
    congestion_lines = []
    notice_lines = []

    if transfer_stations:
        for station in transfer_stations:
            info = get_station_info_any(station)

            elevator_text = format_yes_no(
                info.get("has_elevator"),
                yes_text="엘리베이터 있음",
                no_text="엘리베이터 없음"
            )
            floor_range = info.get("elevator_floor_range")
            if floor_range not in (None, "", "None"):
                elevator_lines.append(f"{station}: {elevator_text} ({floor_range})")
            else:
                elevator_lines.append(f"{station}: {elevator_text}")

            congestion = info.get("congestion_peak")
            if congestion not in (None, "", "None"):
                congestion_lines.append(f"{station}: 최대 혼잡도 {congestion}")
            else:
                congestion_lines.append(f"{station}: 혼잡도 정보 없음")

            maintenance = (
                info.get("elevator_maintenance")
                or info.get("maintenance")
                or info.get("elevator_inspection")
                or info.get("inspection")
                or info.get("is_elevator_under_maintenance")
            )
            if maintenance in (None, "", "None"):
                notice_lines.append(f"{station}: 엘리베이터 점검 정보 없음")
            else:
                notice_lines.append(f"{station}: 엘리베이터 점검 여부 - {maintenance}")
    else:
        elevator_lines.append("환승역이 없는 경로이므로 별도의 환승 엘리베이터 정보가 없습니다.")
        congestion_lines.append("환승역이 없는 경로이므로 환승 혼잡도 정보가 적용되지 않았습니다.")
        notice_lines.append("환승역이 없는 경로이므로 엘리베이터 점검 여부 확인 대상이 없습니다.")

    nursing_lines = []
    seen_nursing = set()
    for line, station in route_pairs:
        info = get_station_info(line, station)
        if info.get("has_nursing_room") == "Y" and station not in seen_nursing:
            seen_nursing.add(station)
            location = info.get("nursing_room_location")
            if location not in (None, "", "None"):
                nursing_lines.append(f"{station}: 수유실 있음 ({location})")
            else:
                nursing_lines.append(f"{station}: 수유실 있음")

    if not nursing_lines:
        nursing_lines.append("선택된 경로 내 수유실 정보가 없습니다.")

    return {
        "elevator_info": " / ".join(elevator_lines),
        "congestion_info": " / ".join(congestion_lines),
        "nursing_room_info": " / ".join(nursing_lines),
        "notice": " / ".join(notice_lines)
    }


def summarize_route_for_original_ui(path):
    """기존 index.html의 result.route 리스트 구조에 맞게 문장 리스트로 변환한다."""
    parsed = [split_node(node) for node in path]

    start_line, start_station = parsed[0]
    end_line, end_station = parsed[-1]

    route_steps = []

    # 출발역 + 방면
    start_direction = ""
    if len(parsed) > 1:
        next_line, next_station = parsed[1]
        if next_line == start_line:
            start_direction = get_direction(start_line, start_station, next_station)

    if start_direction:
        route_steps.append(f"출발역: {start_station} | {start_direction}")
    else:
        route_steps.append(f"출발역: {start_station} | {start_line}")

    # 환승역은 여러 개면 각각 한 줄씩 표시
    transfer_count = 0
    for idx in range(1, len(parsed)):
        prev_line, prev_station = parsed[idx - 1]
        cur_line, cur_station = parsed[idx]

        if prev_station == cur_station and prev_line != cur_line:
            transfer_count += 1

            direction = ""
            if idx + 1 < len(parsed):
                next_line, next_station = parsed[idx + 1]
                if next_line == cur_line:
                    direction = get_direction(cur_line, cur_station, next_station)

            facility_info = format_facility_for_step(cur_line, cur_station)

            if direction:
                route_steps.append(f"환승역: {cur_station} | {prev_line} → {cur_line} · {direction}{facility_info}")
            else:
                route_steps.append(f"환승역: {cur_station} | {prev_line} → {cur_line}{facility_info}")

    if transfer_count == 0:
        route_steps.append("환승역: 없음")

    destination_facility_info = format_facility_for_step(end_line, end_station)
    route_steps.append(f"도착역: {end_station} | {end_line}{destination_facility_info}")

    return route_steps


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        start_line = normalize_line(request.form.get("start_line"))
        start_station = request.form.get("start_station")
        end_line = normalize_line(request.form.get("end_line"))
        end_station = request.form.get("end_station")
        user_type = request.form.get("user_type")

        if not start_line or not start_station or not end_line or not end_station or not user_type:
            error = "출발 호선, 출발역, 도착 호선, 도착역, 이용자 유형을 모두 선택해 주세요."
        else:
            path = dijkstra(
                node_id(start_line, start_station),
                node_id(end_line, end_station),
                user_type
            )

            if path is None:
                error = "선택한 역 사이의 경로를 찾을 수 없습니다."
            else:
                detail_infos = build_detail_infos(path)

                result = {
                    "start": start_station,
                    "end": end_station,
                    "user_type": user_type,
                    "route": summarize_route_for_original_ui(path),
                    "message": "라벨링 데이터를 내부 계산에 반영하여 선택한 최적 환승 경로입니다.",
                    "elevator_info": detail_infos["elevator_info"],
                    "congestion_info": detail_infos["congestion_info"],
                    "nursing_room_info": detail_infos["nursing_room_info"],
                    "notice": detail_infos["notice"]
                }

    return render_template(
        "index.html",
        lines=LINES,
        stations_by_line=STATIONS_BY_LINE_FOR_UI,
        result=result,
        error=error
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
