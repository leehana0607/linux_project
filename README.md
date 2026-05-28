# 교통약자를 위한 지하철 최적 환승 경로

## 실행 방법

```bash
docker build -t accessible-subway-route .
docker run -p 5000:5000 accessible-subway-route
```

브라우저에서 `http://localhost:5000` 접속.

## 알고리즘 요약

최단거리 대신 `접근성 비용(accessibility cost)`이 가장 낮은 경로를 선택한다.

- 일반 이동 비용: 역 간 이동 기본 비용 + 도착역 접근성 비용
- 환승 비용: 환승역 접근성 비용 + 환승 페널티
- 접근성 비용: 혼잡도, 엘리베이터 유무, 수유실 유무, 환승 난이도를 반영
- 탐색 알고리즘: Dijkstra shortest path, 단 weight가 거리가 아니라 접근성 점수

엑셀 라벨링 기준에 따라 점수가 낮을수록 교통약자 친화적인 경로로 판단한다.
