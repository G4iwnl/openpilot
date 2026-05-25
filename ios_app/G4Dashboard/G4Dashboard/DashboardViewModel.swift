import Foundation
import Combine

class DashboardViewModel: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var data = DashboardData()
    @Published var isConnected = false
    @Published var isConnecting = false
    @Published var connectionError: String? = nil
    @Published var ipAddress: String = "172.20.10.2"
    @Published var isDemoMode = false

    private var dataTask: URLSessionDataTask?
    private var demoTimer: Timer?
    private var demoTick = 0

    func startDemo() {
        isDemoMode = true
        isConnected = true
        demoTick = 0
        demoTimer?.invalidate()
        demoTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in
            self?.tickDemo()
        }
    }

    func stopDemo() {
        demoTimer?.invalidate()
        demoTimer = nil
        isDemoMode = false
        isConnected = false
    }

    private func tickDemo() {
        demoTick += 1
        let t = Double(demoTick)
        let baseSpeed = 85.0 + sin(t * 0.04) * 12.0
        let blink = (demoTick / 14) % 8 == 0
        data = DashboardData(
            speed: baseSpeed,
            setSpeed: 100.0,
            speedLimit: 100,
            leftBlinker: blink && (demoTick / 14) % 16 < 8,
            rightBlinker: false,
            cruiseEnabled: true,
            cruiseAvailable: true,
            accel: sin(t * 0.06) * 0.8,
            leadDist: 35.0 + sin(t * 0.03) * 15.0,
            leadSpeed: baseSpeed - 8.0,
            leadRelSpeed: -8.0 + sin(t * 0.05) * 3,
            hasLead: true,
            steeringAngle: sin(t * 0.025) * 18.0,
            brakePressed: false,
            gasPressed: false,
            gear: "D",
            opEnabled: true,
            laneLineProbs: [0.92, 0.85, 0.88, 0.95],
            hasLeadLeft: demoTick % 120 > 30,
            leadLeftDist: 28.0 + sin(t * 0.05) * 10.0,
            leadLeftRelSpeed: -3.0 + sin(t * 0.04) * 4.0,
            leadLeftDPath: 0.0,
            hasLeadRight: demoTick % 100 > 20,
            leadRightDist: 18.0 + sin(t * 0.07) * 8.0,
            leadRightRelSpeed: 2.0 + sin(t * 0.03) * 5.0,
            leadRightDPath: 0.0
        )
    }
    private var streamSession: URLSession!
    private var buffer = ""

    override init() {
        super.init()
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = Double.infinity
        config.timeoutIntervalForResource = Double.infinity
        streamSession = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }

    func connect() {
        let urlString = "http://\(ipAddress):8082/api/dashboard/stream"
        guard let url = URL(string: urlString) else {
            DispatchQueue.main.async { self.connectionError = "잘못된 IP 주소입니다" }
            return
        }
        DispatchQueue.main.async {
            self.connectionError = nil
            self.isConnecting = true
        }
        buffer = ""
        dataTask?.cancel()

        var request = URLRequest(url: url)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 10

        dataTask = streamSession.dataTask(with: request)
        dataTask?.resume()
    }

    func disconnect() {
        dataTask?.cancel()
        dataTask = nil
        DispatchQueue.main.async {
            self.isConnected = false
        }
    }

    // MARK: - URLSessionDataDelegate

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask,
                    didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        DispatchQueue.main.async {
            self.isConnected = true
            self.isConnecting = false
            self.connectionError = nil
        }
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard let text = String(data: data, encoding: .utf8) else { return }
        buffer += text
        while let range = buffer.range(of: "\n\n") {
            let chunk = String(buffer[buffer.startIndex..<range.lowerBound])
            buffer.removeSubrange(buffer.startIndex..<range.upperBound)
            for line in chunk.components(separatedBy: "\n") {
                if line.hasPrefix("data: ") {
                    parseJSON(String(line.dropFirst(6)))
                }
            }
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        DispatchQueue.main.async {
            self.isConnected = false
            self.isConnecting = false
            if let err = error {
                let desc = err.localizedDescription
                if !desc.contains("cancelled") {
                    self.connectionError = desc.contains("timed out") ? "연결 시간 초과 — IP를 확인하세요" : desc
                }
            }
        }
        // 연결됐다가 끊어진 경우에만 자동 재연결 (최초 실패는 제외)
        if self.isDemoMode == false {
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                guard let self = self, !self.isConnected, !self.isConnecting, self.connectionError == nil else { return }
                self.connect()
            }
        }
    }

    private func parseJSON(_ json: String) {
        guard let jsonData = json.data(using: .utf8) else { return }
        do {
            let decoded = try JSONDecoder().decode(DashboardData.self, from: jsonData)
            DispatchQueue.main.async { self.data = decoded }
        } catch {
            // ignore parse error
        }
    }
}
