import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = DashboardViewModel()

    var body: some View {
        Group {
            if viewModel.isConnected {
                DashboardView()
                    .environmentObject(viewModel)
                    .ignoresSafeArea()
            } else {
                ConnectView()
                    .environmentObject(viewModel)
            }
        }
        .preferredColorScheme(.dark)
    }
}

struct ConnectView: View {
    @EnvironmentObject var viewModel: DashboardViewModel

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 28) {
                VStack(spacing: 6) {
                    Text("G4 Dashboard")
                        .font(.system(size: 34, weight: .bold, design: .rounded))
                        .foregroundColor(.white)
                    Text("openpilot 실시간 계기판")
                        .font(.system(size: 15))
                        .foregroundColor(Color(white: 0.5))
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("기기 IP 주소")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(Color(white: 0.5))
                    TextField("172.20.10.2", text: $viewModel.ipAddress)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 20, design: .monospaced))
                        .keyboardType(.numbersAndPunctuation)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .frame(width: 260)
                }

                if let error = viewModel.connectionError {
                    Text(error)
                        .font(.system(size: 13))
                        .foregroundColor(Color(red: 1, green: 0.4, blue: 0.4))
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 280)
                }

                Button(action: { viewModel.connect() }) {
                    Text("연결")
                        .font(.system(size: 20, weight: .semibold))
                        .frame(width: 180, height: 52)
                        .background(Color(red: 0.18, green: 0.45, blue: 0.95))
                        .foregroundColor(.white)
                        .cornerRadius(14)
                }

                VStack(spacing: 4) {
                    Text("아이폰 핫스팟 켜기 → openpilot 기기 연결")
                        .font(.system(size: 13))
                        .foregroundColor(Color(white: 0.38))
                    Text("기기 IP는 보통 172.20.10.2")
                        .font(.system(size: 13))
                        .foregroundColor(Color(white: 0.38))
                }
            }
        }
    }
}
