import Foundation
import Combine

class DashboardViewModel: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var data = DashboardData()
    @Published var isConnected = false
    @Published var connectionError: String? = nil
    @Published var ipAddress: String = "172.20.10.2"

    private var dataTask: URLSessionDataTask?
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
        connectionError = nil
        buffer = ""
        dataTask?.cancel()

        var request = URLRequest(url: url)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.timeoutInterval = Double.infinity

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
            if let err = error {
                let desc = err.localizedDescription
                if !desc.contains("cancelled") {
                    self.connectionError = desc
                }
            }
        }
        // 연결 끊기면 3초 후 재연결 시도
        if self.isConnected == false {
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                guard let self = self, !self.isConnected else { return }
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
