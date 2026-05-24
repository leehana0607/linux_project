from flask import Flask, render_template, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    result = None

    if request.method == "POST":
        start_station = request.form.get("start_station")
        end_station = request.form.get("end_station")
        user_type = request.form.get("user_type")

        # 아직 실제 경로 알고리즘과 DB 연동 전이므로 예시 결과 출력
        result = {
            "start": start_station,
            "end": end_station,
            "user_type": user_type,
            "route": [
                "출발역에서 엘리베이터 위치 확인",
                "혼잡도가 낮은 환승 경로 우선 선택",
                "환승역 내 엘리베이터 및 수유실 위치 확인",
                "목적지까지 이동"
            ],
            "message": "현재는 화면 시안용 예시 결과입니다. 이후 MariaDB와 경로 탐색 알고리즘을 연결하면 실제 추천 경로가 표시됩니다."
        }

    return render_template("index.html", result=result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
