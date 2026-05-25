import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var viewModel: DashboardViewModel

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack {
                Color.black.ignoresSafeArea()

                HStack(spacing: 0) {
                    LeftSpeedPanel()
                        .frame(width: w * 0.21)
                    LaneView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    RightCruisePanel()
                        .frame(width: w * 0.21)
                }

                // Top overlay
                VStack(spacing: 0) {
                    HStack(alignment: .center) {
                        TurnSignalView(isLeft: true)
                        Spacer()
                        GearBadge()
                        Spacer()
                        TurnSignalView(isLeft: false)
                    }
                    .padding(.horizontal, 18)
                    .padding(.top, 6)
                    Spacer()
                    if viewModel.data.hasLead {
                        LeadCarInfoBar()
                            .padding(.bottom, 8)
                    }
                }
            }
        }
        .ignoresSafeArea()
    }
}

// MARK: - Left Panel

struct LeftSpeedPanel: View {
    @EnvironmentObject var viewModel: DashboardViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Spacer()
            // Acceleration
            Text(String(format: "%.2f", viewModel.data.accel))
                .font(.system(size: 16, weight: .semibold, design: .monospaced))
                .foregroundColor(accelColor)
                .padding(.leading, 12)

            // Current speed
            Text("\(Int(viewModel.data.speed.rounded()))")
                .font(.system(size: 88, weight: .bold, design: .rounded))
                .foregroundColor(.white)
                .minimumScaleFactor(0.4)
                .lineLimit(1)
                .padding(.leading, 6)

            // km/h label
            Text("km/h")
                .font(.system(size: 13, weight: .medium))
                .foregroundColor(Color(white: 0.4))
                .padding(.leading, 14)

            // OP status dot
            HStack(spacing: 5) {
                Circle()
                    .fill(viewModel.data.opEnabled ? Color.green : Color(white: 0.25))
                    .frame(width: 9, height: 9)
                Text(viewModel.data.opEnabled ? "ON" : "OFF")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(viewModel.data.opEnabled ? .green : Color(white: 0.35))
            }
            .padding(.leading, 14)
            .padding(.bottom, 14)

            Spacer()
        }
    }

    private var accelColor: Color {
        let a = viewModel.data.accel
        if a < -0.05 { return Color(red: 1, green: 0.3, blue: 0.3) }
        if a > 0.05  { return Color(red: 0.3, green: 1, blue: 0.5) }
        return Color(white: 0.5)
    }
}

// MARK: - Right Panel

struct RightCruisePanel: View {
    @EnvironmentObject var viewModel: DashboardViewModel

    var body: some View {
        VStack(spacing: 6) {
            Spacer()

            if viewModel.data.speedLimit > 0 {
                SpeedLimitSign(limit: viewModel.data.speedLimit)
                    .padding(.bottom, 4)
            }

            Text("SET")
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundColor(Color(white: 0.4))

            Text("\(Int(viewModel.data.setSpeed.rounded()))")
                .font(.system(size: 60, weight: .bold, design: .rounded))
                .foregroundColor(cruiseColor)
                .minimumScaleFactor(0.5)
                .lineLimit(1)

            Spacer().frame(height: 20)
        }
    }

    private var cruiseColor: Color {
        if !viewModel.data.cruiseAvailable { return Color(white: 0.25) }
        return viewModel.data.cruiseEnabled
            ? Color(red: 0.28, green: 0.78, blue: 1.0)
            : Color(white: 0.55)
    }
}

// MARK: - Speed Limit Sign

struct SpeedLimitSign: View {
    let limit: Int

    var body: some View {
        ZStack {
            Circle().fill(Color.white).frame(width: 62, height: 62)
            Circle().strokeBorder(Color.red, lineWidth: 5).frame(width: 62, height: 62)
            Text("\(limit)")
                .font(.system(size: limit >= 100 ? 18 : 22, weight: .bold))
                .foregroundColor(.black)
        }
    }
}

// MARK: - Turn Signal

struct TurnSignalView: View {
    @EnvironmentObject var viewModel: DashboardViewModel
    let isLeft: Bool

    @State private var blinkOn = false
    private let timer = Timer.publish(every: 0.45, on: .main, in: .common).autoconnect()

    private var isActive: Bool { isLeft ? viewModel.data.leftBlinker : viewModel.data.rightBlinker }

    var body: some View {
        Image(systemName: isLeft ? "arrowtriangle.left.fill" : "arrowtriangle.right.fill")
            .font(.system(size: 30))
            .foregroundColor(isActive && blinkOn ? Color.yellow : Color(white: 0.15))
            .onReceive(timer) { _ in
                blinkOn = isActive ? !blinkOn : false
            }
    }
}

// MARK: - Gear Badge

struct GearBadge: View {
    @EnvironmentObject var viewModel: DashboardViewModel

    var body: some View {
        Text(viewModel.data.gear)
            .font(.system(size: 18, weight: .semibold, design: .monospaced))
            .foregroundColor(gearColor)
            .frame(width: 34, height: 34)
            .background(Color(white: 0.1))
            .cornerRadius(8)
    }

    private var gearColor: Color {
        switch viewModel.data.gear {
        case "R": return Color(red: 1, green: 0.3, blue: 0.3)
        case "D": return Color(red: 0.3, green: 0.8, blue: 1)
        case "P": return Color(red: 1, green: 0.7, blue: 0.2)
        default:  return Color(white: 0.55)
        }
    }
}

// MARK: - Lead Car Info Bar

struct LeadCarInfoBar: View {
    @EnvironmentObject var viewModel: DashboardViewModel

    var body: some View {
        HStack(spacing: 18) {
            HStack(spacing: 6) {
                Image(systemName: "car.fill")
                    .font(.system(size: 13))
                    .foregroundColor(Color(white: 0.55))
                Text(String(format: "%.0f m", viewModel.data.leadDist))
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundColor(.white)
            }

            let rel = viewModel.data.leadRelSpeed
            HStack(spacing: 4) {
                Image(systemName: rel < 0 ? "arrow.down" : "arrow.up")
                    .font(.system(size: 11))
                    .foregroundColor(relColor(rel))
                Text(String(format: "%.0f km/h", abs(rel)))
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundColor(relColor(rel))
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 7)
        .background(Color(white: 0.08))
        .cornerRadius(12)
    }

    private func relColor(_ rel: Double) -> Color {
        if rel < -5 { return Color(red: 1, green: 0.35, blue: 0.35) }
        if rel > 5  { return Color(red: 0.35, green: 1, blue: 0.5) }
        return Color(red: 1, green: 0.82, blue: 0.2)
    }
}
