from __future__ import annotations

import heapq
import math
import os
import re
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from flask import Flask, render_template, request
app = Flask(__name__)

DATA_PATH = os.environ.get("LABELING_METADATA_JSON", os.path.join("data", "station_metadata.json"))

# 화면에서 선택할 1·2·5·7호선 범위. 역명은 내부 계산용으로 '역'을 뺀 표준명으로 관리한다.
STATIONS_BY_LINE: Dict[str, List[str]] = {
    "1": ["서울역", "시청", "종각", "종로3가", "종로5가", "동대문", "신설동", "제기동", "청량리"],
    "2": ["시청", "을지로입구", "을지로3가", "을지로4가", "동대문역사문화공원", "신당", "왕십리", "건대입구", "잠실", "강남", "교대", "사당", "신림", "신도림", "홍대입구"],
    "5": ["방화", "김포공항", "송정", "마곡", "발산", "목동", "영등포구청", "여의도", "공덕", "충정로", "광화문", "종로3가", "동대문역사문화공원", "왕십리", "군자"],
    "7": ["장암", "도봉산", "수락산", "노원", "중계", "하계", "태릉입구", "먹골", "상봉", "군자", "건대입구", "청담", "강남구청", "고속터미널", "이수", "가산디지털단지"],
}

TIME_COLUMNS = [
    "5시30분", "6시00분", "6시30분", "7시00분", "7시30분", "8시00분", "8시30분", "9시00분", "9시30분",
    "10시00분", "10시30분", "11시00분", "11시30분", "12시00분", "12시30분", "13시00분", "13시30분",
    "14시00분", "14시30분", "15시00분", "15시30분", "16시00분", "16시30분", "17시00분", "17시30분",
    "18시00분", "18시30분", "19시00분", "19시30분", "20시00분", "20시30분", "21시00분", "21시30분",
    "22시00분", "22시30분", "23시00분", "23시30분", "00시00분", "00시30분",
]

@dataclass
class StationMeta:
    station: str
    has_elevator: str = "Y"
    has_nursery: str = "N"
    congestion_avg: float = 0.0
    congestion_peak: float = 0.0
    transfer_difficulty: str = "보통"
    transfer_penalty: float = 25.0
    base_accessibility_score: float = 35.0
    route_label: str = "보통"
    note: str = ""


def normalize_station_name(name: Optional[str]) -> str:
    """폼/엑셀/프론트에서 들어오는 역명을 같은 형태로 통일한다."""
    if not name:
        return ""
    name = str(name).strip()
    name = re.sub(r"\s+", "", name)
    if name != "서울역" and name.endswith("역"):
        name = name[:-1]
    return name


def parse_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def congestion_grade(peak: float) -> str:
    if peak >= 100:
        return "매우높음"
    if peak >= 70:
        return "높음"
    if peak >= 30:
        return "보통"
    return "낮음"


def default_transfer_difficulty(station: str, transfer_count: int) -> str:
    # 라벨링 예시에 명시된 환승역은 더 보수적으로 처리한다.
    difficult = {
        "서울역", "신도림", "잠실", "사당", "왕십리", "고속터미널", "김포공항", "여의도",
        "동대문역사문화공원", "가산디지털단지",
    }
    high = {"종로3가", "대림", "교대", "공덕", "군자", "태릉입구", "노원", "도봉산", "충정로"}
    if station in difficult or transfer_count >= 3:
        return "회피권장"
    if station in high:
        return "높음"
    return "보통"


def transfer_penalty_from_difficulty(difficulty: str) -> float:
    if difficulty == "회피권장":
        return 80.0
    if difficulty == "높음":
        return 50.0
    return 25.0


def label_from_score(score: float) -> str:
    if score <= 20:
        return "추천"
    if score <= 50:
        return "보통"
    if score <= 90:
        return "주의"
    return "회피"


def user_weight_profile(user_type: str) -> Dict[str, float]:
    """이용자 유형에 따라 같은 역이라도 가중치를 다르게 준다."""
    if user_type == "휠체어 사용자":
        return {"elevator": 1.5, "nursery": 0.0, "congestion": 1.1, "transfer": 1.2}
    if user_type == "유아차 사용자":
        return {"elevator": 1.25, "nursery": 1.0, "congestion": 1.0, "transfer": 1.0}
    return {"elevator": 1.15, "nursery": 0.5, "congestion": 1.0, "transfer": 1.1}


def load_station_metadata(json_path: str) -> Dict[str, StationMeta]:
    """전처리된 라벨링 JSON을 읽어 역별 접근성 점수 메타데이터를 만든다.

    원본 라벨링 엑셀은 data/라벨링.xlsx로 함께 보관하고,
    Docker 실행 시에는 빠르고 안정적인 로딩을 위해 station_metadata.json을 사용한다.
    """
    if not os.path.exists(json_path):
        return build_fallback_metadata()

    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    metadata: Dict[str, StationMeta] = {}
    for station_name, item in raw.items():
        station = normalize_station_name(item.get("station") or station_name)
        metadata[station] = StationMeta(
            station=station,
            has_elevator=str(item.get("has_elevator", "Y")).strip().upper(),
            has_nursery=str(item.get("has_nursery", "N")).strip().upper(),
            congestion_avg=parse_float(item.get("congestion_avg"), 0.0),
            congestion_peak=parse_float(item.get("congestion_peak"), 0.0),
            transfer_difficulty=str(item.get("transfer_difficulty", "보통")).strip(),
            transfer_penalty=parse_float(item.get("transfer_penalty"), 25.0),
            base_accessibility_score=parse_float(item.get("base_accessibility_score"), 35.0),
            route_label=str(item.get("route_label", "보통")).strip() or "보통",
            note=str(item.get("note", "")).strip(),
        )

    apply_transfer_defaults(metadata)
    return metadata

def build_fallback_metadata() -> Dict[str, StationMeta]:
    stations = {station for stations in STATIONS_BY_LINE.values() for station in stations}
    metadata = {station: StationMeta(station=station) for station in stations}
    apply_transfer_defaults(metadata)
    return metadata


def apply_transfer_defaults(metadata: Dict[str, StationMeta]) -> None:
    counts: Dict[str, int] = {}
    for stations in STATIONS_BY_LINE.values():
        for station in stations:
            counts[station] = counts.get(station, 0) + 1
            metadata.setdefault(station, StationMeta(station=station))

    for station, count in counts.items():
        if count >= 2:
            meta = metadata[station]
            if meta.transfer_difficulty == "보통" and meta.transfer_penalty == 25:
                meta.transfer_difficulty = default_transfer_difficulty(station, count)
                meta.transfer_penalty = transfer_penalty_from_difficulty(meta.transfer_difficulty)


def calculate_accessibility_score(
    peak: float,
    has_elevator: str,
    has_nursery: str,
    transfer_penalty: float,
    user_type: str,
) -> float:
    weights = user_weight_profile(user_type)

    # 라벨링 기준: peak>=100 매우높음, >=70 높음, >=30 보통, 그 외 낮음
    if peak >= 100:
        congestion_penalty = 60
    elif peak >= 70:
        congestion_penalty = 40
    elif peak >= 30:
        congestion_penalty = 20
    else:
        congestion_penalty = 5

    elevator_penalty = 100 if has_elevator == "N" else 0
    nursery_bonus = 10 if has_nursery == "Y" else 0

    score = (
        congestion_penalty * weights["congestion"]
        + elevator_penalty * weights["elevator"]
        + transfer_penalty * weights["transfer"]
        - nursery_bonus * weights["nursery"]
    )
    return round(max(score, 0), 1)


def station_cost(station: str, user_type: str, is_transfer: bool = False) -> float:
    meta = STATION_METADATA.get(station, StationMeta(station=station))
    score = calculate_accessibility_score(
        peak=meta.congestion_peak,
        has_elevator=meta.has_elevator,
        has_nursery=meta.has_nursery,
        transfer_penalty=meta.transfer_penalty if is_transfer else 0,
        user_type=user_type,
    )
    # 역 한 번 지날 때 전체 점수를 다 더하면 장거리 경로가 지나치게 불리해져서 일부만 반영한다.
    return score * (0.18 if not is_transfer else 1.0)


def build_graph(user_type: str) -> Dict[Tuple[str, str], List[Tuple[Tuple[str, str], float, str]]]:
    graph: Dict[Tuple[str, str], List[Tuple[Tuple[str, str], float, str]]] = {}

    def add_edge(a: Tuple[str, str], b: Tuple[str, str], weight: float, description: str) -> None:
        graph.setdefault(a, []).append((b, weight, description))
        graph.setdefault(b, []).append((a, weight, description))

    # 같은 호선 내 인접역 이동
    for line, stations in STATIONS_BY_LINE.items():
        for s1, s2 in zip(stations, stations[1:]):
            base_move_cost = 10.0
            weight = base_move_cost + station_cost(s2, user_type, is_transfer=False)
            add_edge((line, s1), (line, s2), round(weight, 1), f"{line}호선 이동")

    # 같은 역에서 다른 호선으로 갈아타는 환승 edge
    station_to_lines: Dict[str, List[str]] = {}
    for line, stations in STATIONS_BY_LINE.items():
        for station in stations:
            station_to_lines.setdefault(station, []).append(line)

    for station, lines in station_to_lines.items():
        if len(lines) < 2:
            continue
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                weight = station_cost(station, user_type, is_transfer=True)
                add_edge((lines[i], station), (lines[j], station), round(weight, 1), f"{station} 환승")

    return graph


def dijkstra_optimal_route(start_station: str, end_station: str, user_type: str) -> Optional[Dict]:
    start = normalize_station_name(start_station)
    end = normalize_station_name(end_station)
    graph = build_graph(user_type)

    start_nodes = [node for node in graph if node[1] == start]
    end_nodes = {node for node in graph if node[1] == end}
    if not start_nodes or not end_nodes:
        return None

    pq: List[Tuple[float, Tuple[str, str]]] = []
    dist: Dict[Tuple[str, str], float] = {}
    prev: Dict[Tuple[str, str], Tuple[Tuple[str, str], str, float]] = {}

    for node in start_nodes:
        dist[node] = 0.0
        heapq.heappush(pq, (0.0, node))

    best_end = None
    while pq:
        current_cost, node = heapq.heappop(pq)
        if current_cost > dist.get(node, math.inf):
            continue
        if node in end_nodes:
            best_end = node
            break

        for next_node, weight, description in graph.get(node, []):
            new_cost = current_cost + weight
            if new_cost < dist.get(next_node, math.inf):
                dist[next_node] = new_cost
                prev[next_node] = (node, description, weight)
                heapq.heappush(pq, (new_cost, next_node))

    if best_end is None:
        return None

    nodes = []
    edge_descriptions = []
    node = best_end
    while node in prev:
        before, desc, weight = prev[node]
        nodes.append(node)
        edge_descriptions.append((desc, weight))
        node = before
    nodes.append(node)
    nodes.reverse()
    edge_descriptions.reverse()

    return make_result(nodes, edge_descriptions, round(dist[best_end], 1), user_type)


def make_result(
    nodes: List[Tuple[str, str]],
    edge_descriptions: List[Tuple[str, float]],
    total_score: float,
    user_type: str,
) -> Dict:
    compressed_route = []
    last = None
    for line, station in nodes:
        current = f"{line}호선 {station}"
        if current != last:
            compressed_route.append(current)
            last = current

    transfer_steps = []
    for i in range(1, len(nodes)):
        prev_line, prev_station = nodes[i - 1]
        line, station = nodes[i]
        if prev_station == station and prev_line != line:
            meta = STATION_METADATA.get(station, StationMeta(station=station))
            transfer_steps.append(
                f"{station}에서 {prev_line}호선 → {line}호선 환승: "
                f"환승 난이도 {meta.transfer_difficulty}, 엘리베이터 {meta.has_elevator}, 수유실 {meta.has_nursery}"
            )

    detailed_steps = []
    for idx, (line, station) in enumerate(nodes):
        meta = STATION_METADATA.get(station, StationMeta(station=station))
        if idx == 0:
            detailed_steps.append(f"출발: {line}호선 {station} / 엘리베이터 {meta.has_elevator}")
        elif idx == len(nodes) - 1:
            detailed_steps.append(f"도착: {line}호선 {station} / 혼잡도 peak {meta.congestion_peak:.1f}, 수유실 {meta.has_nursery}")
        else:
            prev_line, prev_station = nodes[idx - 1]
            if prev_station == station and prev_line != line:
                detailed_steps.append(f"환승: {station} {prev_line}호선 → {line}호선")
            else:
                detailed_steps.append(f"이동: {line}호선 {station}")

    labels = [label_from_score(calculate_accessibility_score(
        peak=STATION_METADATA.get(station, StationMeta(station=station)).congestion_peak,
        has_elevator=STATION_METADATA.get(station, StationMeta(station=station)).has_elevator,
        has_nursery=STATION_METADATA.get(station, StationMeta(station=station)).has_nursery,
        transfer_penalty=0,
        user_type=user_type,
    )) for _, station in nodes]

    route_label = "추천"
    if "회피" in labels:
        route_label = "회피"
    elif "주의" in labels or total_score >= 120:
        route_label = "주의"
    elif total_score >= 70:
        route_label = "보통"

    return {
        "route": compressed_route,
        "steps": detailed_steps,
        "transfers": transfer_steps,
        "total_score": total_score,
        "route_label": route_label,
        "edge_costs": [f"{desc}: +{weight}" for desc, weight in edge_descriptions],
        "message": "라벨링 기준에 따라 최단거리보다 엘리베이터, 혼잡도, 수유실, 환승 난이도를 우선 반영했습니다.",
    }


STATION_METADATA = load_station_metadata(DATA_PATH)


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        start_station = request.form.get("start_station")
        end_station = request.form.get("end_station")
        user_type = request.form.get("user_type") or "이동약자"

        route_result = dijkstra_optimal_route(start_station, end_station, user_type)
        if route_result is None:
            error = "선택한 출발역과 도착역 사이의 연결 경로를 찾지 못했습니다. 현재 데이터 범위를 확인해 주세요."
        else:
            result = {
                "start": start_station,
                "end": end_station,
                "user_type": user_type,
                **route_result,
            }

    return render_template(
        "index.html",
        result=result,
        error=error,
        stations_by_line=STATIONS_BY_LINE,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
