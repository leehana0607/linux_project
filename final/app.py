# Flask 웹 서버를 만들기 위한 기본 기능을 불러온다.
# render_template: HTML 파일을 화면에 보여줄 때 사용
# request: 사용자가 웹에서 입력한 값을 Flask 서버로 받을 때 사용
from flask import Flask, render_template, request

# JSON 형식의 데이터 파일(station_metadata.json)을 읽기 위해 사용한다.
import json

# 다익스트라 알고리즘에서 우선순위 큐를 사용하기 위해 불러온다.
# 비용이 가장 낮은 경로부터 탐색할 수 있게 해준다.
import heapq

# 현재 파일 위치를 기준으로 데이터 파일 경로를 만들기 위해 사용한다.
import os


# Flask 애플리케이션 객체를 생성한다.
# 이 객체를 기준으로 웹 페이지 라우팅과 서버 실행이 이루어진다.
app = Flask(__name__)


# 현재 app.py 파일이 있는 폴더 경로를 가져온다.
BASE_DIR = os.path.dirname(__file__)

# data 폴더 안의 station_metadata.json 파일 경로를 만든다.
# 즉, 지하철역 정보와 라벨링 데이터가 저장된 JSON 파일을 불러오기 위한 경로이다.
DATA_PATH = os.path.join(BASE_DIR, "data", "station_metadata.json")


# station_metadata.json 파일을 UTF-8 형식으로 열어 읽는다.
# JSON 파일 안의 데이터를 Python 딕셔너리 형태로 변환한다.
with open(DATA_PATH, "r", encoding="utf-8") as f:
    DATA = json.load(f)


# 호선별 역 목록과 역별 상세 정보가 들어 있는 데이터이다.
LINE_DATA = DATA["line_data"]

# 각 역이 어떤 호선에 속해 있는지 저장한 데이터이다.
# 같은 역이 여러 호선에 포함되어 있으면 환승역으로 판단하는 데 사용된다.
STATION_LINES = DATA["station_lines"]

# 환승역별 라벨링 정보이다.
# 엘리베이터 여부, 혼잡도, 수유실 여부, 환승 페널티 등을 담고 있다.
TRANSFER_METADATA = DATA.get("transfer_metadata", {})


# 데이터에 포함된 호선 목록을 리스트로 저장한다.
LINES = list(LINE_DATA.keys())


# LINE_DATA에서 각 호선별 역 이름만 추출하여 저장한다.
# 예: {"2호선": ["시청", "을지로입구", ...]}
STATIONS_BY_LINE = {
    line: [item["station"] for item in stations]
    for line, stations in LINE_DATA.items()
}


# 각 역이 해당 호선에서 몇 번째 위치에 있는지 저장한다.
# 방면 계산에서 현재 역과 다음 역의 순서를 비교할 때 사용된다.
LINE_INDEX = {
    line: {station: idx for idx, station in enumerate(stations)}
    for line, stations in STATIONS_BY_LINE.items()
}


# 역 이름으로 해당 역의 상세 정보를 바로 찾기 위한 구조이다.
# 예: STATION_INFO_BY_LINE["2호선"]["시청"] → 시청역의 상세 정보
STATION_INFO_BY_LINE = {
    line: {item["station"]: item for item in stations}
    for line, stations in LINE_DATA.items()
}


# HTML 화면에서 넘어오는 호선 값과 Python 내부 데이터의 호선 이름을 맞춰주는 매핑이다.
# 화면에서는 "1", "2"처럼 넘어올 수 있고, 내부 데이터는 "1호선", "2호선" 형태를 사용한다.
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


# HTML 드롭다운에 전달할 호선별 역 목록이다.
# HTML에서는 호선을 "1", "2", "5", "7"로 구분하므로 그 형식에 맞춰 다시 정리한다.
STATIONS_BY_LINE_FOR_UI = {
    "1": STATIONS_BY_LINE.get("1호선", []),
    "2": STATIONS_BY_LINE.get("2호선", []),
    "5": STATIONS_BY_LINE.get("5호선", []),
    "7": STATIONS_BY_LINE.get("7호선", []),
}


# 화면에서 받은 호선 값을 내부 데이터 형식으로 변환한다.
# 예: "1" → "1호선"
def normalize_line(line):
    return LINE_VALUE_MAP.get(line, line)


# 호선과 역 이름을 하나의 노드 ID로 합친다.
# 그래프에서 같은 역이라도 호선이 다르면 다른 노드로 구분해야 하기 때문에 "호선|역명" 형태를 사용한다.
def node_id(line, station):
    return f"{line}|{station}"


# "호선|역명" 형태의 노드 ID를 다시 호선과 역명으로 분리한다.
def split_node(node):
    return node.split("|", 1)


# 현재 역과 다음 역을 비교해서 어느 방면으로 가야 하는지 계산한다.
def get_direction(line, current_station, next_station):
    """같은 호선에서 다음 역 방향을 기준으로 '종착역 방면'을 계산한다."""
    # 해당 호선의 인덱스 정보가 없으면 방면을 계산할 수 없으므로 빈 문자열을 반환한다.
    if line not in LINE_INDEX:
        return ""

    # 현재 역 또는 다음 역이 호선 목록에 없으면 방면을 계산할 수 없으므로 빈 문자열을 반환한다.
    if current_station not in LINE_INDEX[line] or next_station not in LINE_INDEX[line]:
        return ""

    # 현재 역과 다음 역의 호선 내 위치를 가져온다.
    current_idx = LINE_INDEX[line][current_station]
    next_idx = LINE_INDEX[line][next_station]

    # 해당 호선의 전체 역 목록을 가져온다.
    stations = STATIONS_BY_LINE[line]

    # 다음 역이 현재 역보다 뒤쪽에 있으면 해당 호선의 마지막 역 방면으로 이동한다고 판단한다.
    if next_idx > current_idx:
        return f"{line} {stations[-1]} 방면"

    # 다음 역이 현재 역보다 앞쪽에 있으면 해당 호선의 첫 번째 역 방면으로 이동한다고 판단한다.
    if next_idx < current_idx:
        return f"{line} {stations[0]} 방면"

    # 위치가 같으면 방면을 계산하지 않는다.
    return ""


# 환승역의 접근성 정보를 반영하여 환승 비용을 계산한다.
# 다익스트라 알고리즘에서 이 비용이 낮을수록 더 선호되는 경로가 된다.
def transfer_weight(station, user_type):
    """라벨링된 환승역 데이터를 내부 계산에만 사용한다.
    화면에는 혼잡도 점수나 접근성 점수를 출력하지 않는다.
    """
    # 해당 환승역의 라벨링 정보를 가져온다.
    info = TRANSFER_METADATA.get(station, {})

    # 기본 환승 비용
    weight = 4.0

    # 라벨링 점수가 있으면 환승 비용에 반영
    if info.get("score") is not None:
        weight += float(info["score"]) / 25.0

    # 환승 페널티 값이 있으면 환승 비용에 반영한다.
    if info.get("transfer_penalty") is not None:
        weight += float(info["transfer_penalty"]) / 20.0

    # 엘리베이터 없음은 교통약자에게 큰 불편 요소
    if info.get("has_elevator") == "N":
        # 휠체어 사용자는 엘리베이터가 없을 때 가장 큰 불편을 겪기 때문에 큰 페널티를 부여한다.
        if user_type == "휠체어 사용자":
            weight += 8.0
        # 유아차 사용자도 엘리베이터가 없으면 이동이 어렵기 때문에 큰 페널티를 부여한다.
        elif user_type == "유아차 사용자":
            weight += 6.0
        # 그 외 이용자 유형에도 엘리베이터 부재에 대한 기본 페널티를 부여한다.
        else:
            weight += 4.0

    # 수유실은 유아차 사용자에게만 내부 가중치에서 약간 유리하게 반영
    if user_type == "유아차 사용자" and info.get("has_nursing_room") == "Y":
        weight -= 1.0

    # 환승 비용이 지나치게 낮아지지 않도록 최소 비용을 2.0으로 제한한다.
    return max(weight, 2.0)


# 전체 지하철 데이터를 그래프 구조로 변환한다.
# 같은 호선의 인접역은 이동 간선으로 연결하고, 환승역은 환승 간선으로 연결한다.
def build_graph(user_type):
    """전체 역 목록을 그래프로 구성한다.
    - 같은 호선의 인접 역은 이동 간선으로 연결
    - 같은 역명이 여러 호선에 있으면 환승 간선으로 연결
    """
    # 그래프를 저장할 딕셔너리이다.
    # 예: graph["2호선|시청"] = [("2호선|을지로입구", 1.0), ...]
    graph = {}

    # 같은 호선 내 인접역 연결
    for line, stations in STATIONS_BY_LINE.items():
        for idx, station in enumerate(stations):
            # 현재 역을 그래프 노드로 만든다.
            current = node_id(line, station)

            # 현재 노드가 그래프에 없으면 빈 리스트로 초기화한다.
            graph.setdefault(current, [])

            # 현재 역의 이전 역이 있으면 이전 역과 연결한다.
            if idx > 0:
                graph[current].append((node_id(line, stations[idx - 1]), 1.0))

            # 현재 역의 다음 역이 있으면 다음 역과 연결한다.
            if idx < len(stations) - 1:
                graph[current].append((node_id(line, stations[idx + 1]), 1.0))

    # 환승역 연결
    for station, lines in STATION_LINES.items():
        # 하나의 역이 2개 미만의 호선에만 속하면 환승역이 아니므로 건너뛴다.
        if len(lines) < 2:
            continue

        # 이용자 유형과 환승역 라벨링 데이터를 반영해 환승 비용을 계산한다.
        cost = transfer_weight(station, user_type)

        # 같은 역에 연결된 모든 호선 조합을 확인한다.
        for from_line in lines:
            for to_line in lines:
                # 같은 호선끼리는 환승이 아니므로 건너뛴다.
                if from_line == to_line:
                    continue

                # 환승 전 노드와 환승 후 노드를 만든다.
                start = node_id(from_line, station)
                end = node_id(to_line, station)

                # 두 노드가 실제 그래프에 존재할 때만 환승 간선을 추가한다.
                if start in graph and end in graph:
                    graph[start].append((end, cost))

    # 완성된 그래프를 반환한다.
    return graph


# 다익스트라 알고리즘을 이용해 출발 노드에서 도착 노드까지의 최소 비용 경로를 찾는다.
def dijkstra(start_node, end_node, user_type):
    # 이용자 유형에 맞는 가중치가 반영된 그래프를 생성한다.
    graph = build_graph(user_type)

    # 출발 노드나 도착 노드가 그래프에 없으면 경로를 찾을 수 없다.
    if start_node not in graph or end_node not in graph:
        return None

    # 우선순위 큐를 초기화한다.
    # 각 원소는 (현재까지의 비용, 현재 노드, 현재까지의 경로) 형태이다.
    queue = [(0, start_node, [])]

    # 이미 방문한 노드를 저장한다.
    visited = set()

    # 탐색할 노드가 남아 있는 동안 반복한다.
    while queue:
        # 현재까지 비용이 가장 낮은 노드를 꺼낸다.
        cost, current, path = heapq.heappop(queue)

        # 이미 방문한 노드라면 다시 처리하지 않는다.
        if current in visited:
            continue

        # 현재 노드를 방문 처리한다.
        visited.add(current)

        # 현재 노드를 기존 경로에 추가한다.
        new_path = path + [current]

        # 현재 노드가 도착 노드라면 최종 경로를 반환한다.
        if current == end_node:
            return new_path

        # 현재 노드와 연결된 이웃 노드들을 확인한다.
        for neighbor, weight in graph.get(current, []):
            # 아직 방문하지 않은 이웃 노드만 큐에 추가한다.
            if neighbor not in visited:
                heapq.heappush(queue, (cost + weight, neighbor, new_path))

    # 모든 경로를 확인해도 도착할 수 없으면 None을 반환한다.
    return None



# 계산된 경로에서 실제 환승이 발생한 역만 추출한다.
def get_transfer_stations_from_path(path):
    """경로에서 실제 환승이 발생한 역 이름만 추출한다."""
    # "호선|역명" 형태의 노드들을 [호선, 역명] 형태로 변환한다.
    parsed = [split_node(node) for node in path]

    # 환승역 이름을 저장할 리스트이다.
    transfer_stations = []

    # 경로를 앞뒤로 비교하면서 환승 여부를 확인한다.
    for idx in range(1, len(parsed)):
        prev_line, prev_station = parsed[idx - 1]
        cur_line, cur_station = parsed[idx]

        # 역 이름은 같고 호선이 다르면 실제 환승이 발생한 것으로 판단한다.
        if prev_station == cur_station and prev_line != cur_line:
            transfer_stations.append(cur_station)

    # 추출한 환승역 목록을 반환한다.
    return transfer_stations


# 경로에 포함된 모든 역을 중복 없이 (호선, 역명) 형태로 반환한다.
def get_route_station_pairs(path):
    """경로에 포함된 역을 중복 없이 (호선, 역명) 형태로 반환한다."""
    # 경로 노드를 호선과 역명으로 분리한다.
    parsed = [split_node(node) for node in path]

    # 이미 추가한 역을 확인하기 위한 집합이다.
    seen = set()

    # 중복을 제거한 역 목록을 저장할 리스트이다.
    pairs = []

    # 경로에 포함된 역들을 순서대로 확인한다.
    for line, station in parsed:
        # 호선과 역명을 묶어 중복 확인용 키로 사용한다.
        key = (line, station)

        # 아직 추가하지 않은 역이면 목록에 추가한다.
        if key not in seen:
            seen.add(key)
            pairs.append(key)

    # 중복이 제거된 경로 내 역 목록을 반환한다.
    return pairs


# 특정 호선의 특정 역에 대한 상세 정보를 가져온다.
def get_station_info(line, station):
    """2번째 데이터 기반 station_metadata에서 역별 정보를 가져온다."""
    return STATION_INFO_BY_LINE.get(line, {}).get(station, {})


# 호선을 모르는 경우, 역 이름만으로 해당 역의 정보를 가져온다.
def get_station_info_any(station):
    """호선이 특정되지 않은 경우 같은 역명에 해당하는 정보를 가져온다."""
    # 환승역 메타데이터에 해당 역이 있으면 우선 그 정보를 사용한다.
    if station in TRANSFER_METADATA:
        return TRANSFER_METADATA.get(station, {})

    # 환승역 메타데이터에 없으면 전체 호선 데이터를 돌면서 해당 역 정보를 찾는다.
    for line in LINES:
        info = STATION_INFO_BY_LINE.get(line, {}).get(station)
        if info:
            return info

    # 어떤 정보도 찾지 못하면 빈 딕셔너리를 반환한다.
    return {}


# Y/N 형태의 값을 화면에 보여줄 문장으로 변환한다.
def format_yes_no(value, yes_text="있음", no_text="없음"):
    # 값이 Y이면 있음에 해당하는 문구를 반환한다.
    if value == "Y":
        return yes_text

    # 값이 N이면 없음에 해당하는 문구를 반환한다.
    if value == "N":
        return no_text

    # 값이 없거나 Y/N이 아니면 정보 없음으로 처리한다.
    return "정보 없음"


# 추천 이동 흐름 안에서 환승역과 도착역별 시설 정보를 HTML 문자열로 만든다.
def format_facility_for_step(line, station):
    """추천 이동 흐름에서 환승역/도착역별 시설 정보를 함께 표시한다."""
    # 우선 해당 호선의 역 정보를 가져오고, 없으면 역 이름만으로 정보를 찾는다.
    info = get_station_info(line, station) or get_station_info_any(station)

    # 엘리베이터 여부를 있음/없음/정보 없음으로 변환한다.
    elevator = format_yes_no(
        info.get("has_elevator"),
        yes_text="있음",
        no_text="없음"
    )

    # 엘리베이터 층 정보가 있으면 함께 표시한다.
    floor_range = info.get("elevator_floor_range")
    if floor_range not in (None, "", "None"):
        elevator_text = f"엘리베이터: {elevator} ({floor_range})"
    else:
        elevator_text = f"엘리베이터: {elevator}"

    # 수유실이 있는 경우 위치 정보까지 함께 표시한다.
    if info.get("has_nursing_room") == "Y":
        nursing_location = info.get("nursing_room_location")
        if nursing_location not in (None, "", "None"):
            nursing_text = f"수유실: 있음 ({nursing_location})"
        else:
            nursing_text = "수유실: 있음"
    # 수유실이 없으면 없음으로 표시한다.
    else:
        nursing_text = "수유실: 없음"

    # HTML에서 줄바꿈과 시설 정보 스타일이 적용되도록 문자열을 반환한다.
    return f"<br><span class=\"facility-text\">- {elevator_text}</span><br><span class=\"facility-text\">- {nursing_text}</span>"


# 결과 화면 하단 정보 박스에 들어갈 엘리베이터, 혼잡도, 수유실, 주의사항 문장을 만든다.
def build_detail_infos(path):
    """결과 화면 하단 정보 박스에 넣을 문장을 만든다.
    - 엘리베이터/혼잡도 정보는 선택된 환승 구간을 중심으로 안내한다.
    - 수유실 정보는 전체 경로에 수유실이 포함되어 있을 때 위치까지 표시한다.
    - 주의사항에는 엘리베이터 점검 여부만 표시한다.
    """
    # 경로에서 실제 환승이 발생한 역 목록을 가져온다.
    transfer_stations = get_transfer_stations_from_path(path)

    # 경로에 포함된 전체 역 목록을 중복 없이 가져온다.
    route_pairs = get_route_station_pairs(path)

    # 결과 화면에 표시할 문장들을 저장할 리스트이다.
    elevator_lines = []
    congestion_lines = []
    notice_lines = []

    # 환승역이 있는 경우, 환승역 중심으로 엘리베이터/혼잡도/점검 정보를 구성한다.
    if transfer_stations:
        for station in transfer_stations:
            # 환승역의 상세 정보를 가져온다.
            info = get_station_info_any(station)

            # 엘리베이터 여부를 화면 표시용 문장으로 변환한다.
            elevator_text = format_yes_no(
                info.get("has_elevator"),
                yes_text="엘리베이터 있음",
                no_text="엘리베이터 없음"
            )

            # 엘리베이터 층 정보가 있으면 함께 표시한다.
            floor_range = info.get("elevator_floor_range")
            if floor_range not in (None, "", "None"):
                elevator_lines.append(f"{station}: {elevator_text} ({floor_range})")
            else:
                elevator_lines.append(f"{station}: {elevator_text}")

            # 환승역의 최대 혼잡도 정보를 가져온다.
            congestion = info.get("congestion_peak")
            if congestion not in (None, "", "None"):
                congestion_lines.append(f"{station}: 최대 혼잡도 {congestion}")
            else:
                congestion_lines.append(f"{station}: 혼잡도 정보 없음")

            # 엘리베이터 점검 관련 정보를 여러 가능한 키 이름으로 확인한다.
            maintenance = (
                info.get("elevator_maintenance")
                or info.get("maintenance")
                or info.get("elevator_inspection")
                or info.get("inspection")
                or info.get("is_elevator_under_maintenance")
            )

            # 점검 정보가 없으면 정보 없음으로 안내한다.
            if maintenance in (None, "", "None"):
                notice_lines.append(f"{station}: 엘리베이터 점검 정보 없음")
            # 점검 정보가 있으면 해당 내용을 표시한다.
            else:
                notice_lines.append(f"{station}: 엘리베이터 점검 여부 - {maintenance}")
    # 환승역이 없는 경로라면 환승 관련 정보가 없다는 문구를 표시한다.
    else:
        elevator_lines.append("환승역이 없는 경로이므로 별도의 환승 엘리베이터 정보가 없습니다.")
        congestion_lines.append("환승역이 없는 경로이므로 환승 혼잡도 정보가 적용되지 않았습니다.")
        notice_lines.append("환승역이 없는 경로이므로 엘리베이터 점검 여부 확인 대상이 없습니다.")

    # 수유실 정보는 환승역만이 아니라 전체 경로에 포함된 역을 기준으로 확인한다.
    nursing_lines = []

    # 같은 역의 수유실 정보가 중복으로 출력되지 않도록 확인하는 집합이다.
    seen_nursing = set()

    # 경로 안의 모든 역을 순서대로 확인한다.
    for line, station in route_pairs:
        # 해당 호선과 역에 대한 상세 정보를 가져온다.
        info = get_station_info(line, station)

        # 수유실이 있는 역이고, 아직 출력하지 않은 역이면 추가한다.
        if info.get("has_nursing_room") == "Y" and station not in seen_nursing:
            seen_nursing.add(station)

            # 수유실 위치 정보가 있으면 함께 표시한다.
            location = info.get("nursing_room_location")
            if location not in (None, "", "None"):
                nursing_lines.append(f"{station}: 수유실 있음 ({location})")
            else:
                nursing_lines.append(f"{station}: 수유실 있음")

    # 경로 내 수유실 정보가 없으면 안내 문구를 표시한다.
    if not nursing_lines:
        nursing_lines.append("선택된 경로 내 수유실 정보가 없습니다.")

    # 각 정보 리스트를 하나의 문자열로 합쳐 result에 담을 수 있도록 반환한다.
    return {
        "elevator_info": " / ".join(elevator_lines),
        "congestion_info": " / ".join(congestion_lines),
        "nursing_room_info": " / ".join(nursing_lines),
        "notice": " / ".join(notice_lines)
    }


# 다익스트라가 반환한 경로를 HTML 화면에 보여줄 문장 리스트로 변환한다.
def summarize_route_for_original_ui(path):
    """기존 index.html의 result.route 리스트 구조에 맞게 문장 리스트로 변환한다."""
    # "호선|역명" 형태의 경로를 [호선, 역명] 형태로 변환한다.
    parsed = [split_node(node) for node in path]

    # 출발역과 도착역 정보를 가져온다.
    start_line, start_station = parsed[0]
    end_line, end_station = parsed[-1]

    # 화면에 출력할 경로 안내 문장들을 저장한다.
    route_steps = []

    # 출발역 + 방면
    start_direction = ""

    # 다음 역이 있으면 출발역 기준 방면을 계산한다.
    if len(parsed) > 1:
        next_line, next_station = parsed[1]
        if next_line == start_line:
            start_direction = get_direction(start_line, start_station, next_station)

    # 방면 정보가 있으면 출발역과 함께 방면을 표시한다.
    if start_direction:
        route_steps.append(f"출발역: {start_station} | {start_direction}")
    # 방면 정보가 없으면 출발역과 호선만 표시한다.
    else:
        route_steps.append(f"출발역: {start_station} | {start_line}")

    # 환승역은 여러 개면 각각 한 줄씩 표시
    transfer_count = 0

    # 경로를 앞뒤 노드로 비교하면서 환승이 발생하는 지점을 찾는다.
    for idx in range(1, len(parsed)):
        prev_line, prev_station = parsed[idx - 1]
        cur_line, cur_station = parsed[idx]

        # 역명은 같지만 호선이 달라지는 경우 실제 환승으로 판단한다.
        if prev_station == cur_station and prev_line != cur_line:
            transfer_count += 1

            # 환승 후 다음 이동 방향을 계산하기 위한 변수이다.
            direction = ""

            # 환승 후 다음 역이 존재하고 같은 호선이면 방면을 계산한다.
            if idx + 1 < len(parsed):
                next_line, next_station = parsed[idx + 1]
                if next_line == cur_line:
                    direction = get_direction(cur_line, cur_station, next_station)

            # 환승역에 표시할 엘리베이터/수유실 정보를 만든다.
            facility_info = format_facility_for_step(cur_line, cur_station)

            # 방면 정보가 있으면 환승 안내에 방면과 시설 정보를 함께 붙인다.
            if direction:
                route_steps.append(f"환승역: {cur_station} | {prev_line} → {cur_line} · {direction}{facility_info}")
            # 방면 정보가 없으면 환승 호선과 시설 정보만 표시한다.
            else:
                route_steps.append(f"환승역: {cur_station} | {prev_line} → {cur_line}{facility_info}")

    # 환승이 한 번도 없으면 환승역 없음으로 표시한다.
    if transfer_count == 0:
        route_steps.append("환승역: 없음")

    # 도착역에도 엘리베이터/수유실 정보를 함께 표시한다.
    destination_facility_info = format_facility_for_step(end_line, end_station)

    # 도착역 안내 문장을 추가한다.
    route_steps.append(f"도착역: {end_station} | {end_line}{destination_facility_info}")

    # 최종 경로 안내 문장 리스트를 반환한다.
    return route_steps


# 웹사이트의 메인 주소("/")에 대한 라우팅이다.
# GET 요청이면 화면을 보여주고, POST 요청이면 사용자가 입력한 조건으로 경로를 계산한다.
@app.route("/", methods=["GET", "POST"])
def index():
    # 결과 데이터는 처음에는 없는 상태로 둔다.
    result = None

    # 오류 메시지도 처음에는 없는 상태로 둔다.
    error = None

    # 사용자가 검색 버튼을 눌러 POST 요청을 보낸 경우에만 경로 계산을 수행한다.
    if request.method == "POST":
        # 출발 호선을 받아 내부 데이터 형식으로 변환한다.
        start_line = normalize_line(request.form.get("start_line"))

        # 출발역을 가져온다.
        start_station = request.form.get("start_station")

        # 도착 호선을 받아 내부 데이터 형식으로 변환한다.
        end_line = normalize_line(request.form.get("end_line"))

        # 도착역을 가져온다.
        end_station = request.form.get("end_station")

        # 이용자 유형을 가져온다.
        user_type = request.form.get("user_type")

        # 필수 입력값 중 하나라도 없으면 오류 메시지를 출력한다.
        if not start_line or not start_station or not end_line or not end_station or not user_type:
            error = "출발 호선, 출발역, 도착 호선, 도착역, 이용자 유형을 모두 선택해 주세요."
        else:
            # 출발역과 도착역을 노드 ID로 변환한 뒤 다익스트라 알고리즘을 실행한다.
            path = dijkstra(
                node_id(start_line, start_station),
                node_id(end_line, end_station),
                user_type
            )

            # 경로를 찾지 못한 경우 오류 메시지를 출력한다.
            if path is None:
                error = "선택한 역 사이의 경로를 찾을 수 없습니다."
            else:
                # 경로에 대한 엘리베이터, 혼잡도, 수유실, 점검 정보를 생성한다.
                detail_infos = build_detail_infos(path)

                # HTML 화면으로 전달할 결과 데이터를 구성한다.
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

    # index.html 화면을 렌더링한다.
    # 호선 목록, 역 목록, 결과값, 오류 메시지를 HTML로 전달한다.
    return render_template(
        "index.html",
        lines=LINES,
        stations_by_line=STATIONS_BY_LINE_FOR_UI,
        result=result,
        error=error
    )


# 이 파일을 직접 실행했을 때 Flask 서버를 시작한다.
if __name__ == "__main__":
    # 외부 접속이 가능하도록 host를 0.0.0.0으로 설정하고, 5000번 포트에서 실행한다.
    # debug=True는 개발 중 오류 확인을 쉽게 하기 위한 설정이다.
    app.run(host="0.0.0.0", port=5000, debug=True)
