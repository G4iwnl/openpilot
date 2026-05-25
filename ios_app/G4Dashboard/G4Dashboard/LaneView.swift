import SwiftUI

struct LaneView: View {
    @EnvironmentObject var viewModel: DashboardViewModel

    var body: some View {
        Canvas { context, size in
            let w = size.width, h = size.height
            let vanishX = w / 2
            let vanishY = h * 0.18
            let baseY = h * 0.97

            drawRoadSurface(context, w, h, vanishX, vanishY, baseY)
            drawLaneLines(context, w, h, vanishX, vanishY, baseY)
            drawPredictedPath(context, w, h, vanishX, vanishY, baseY)
            if viewModel.data.hasLead {
                drawLeadCar(context, w, h, vanishX, vanishY, baseY)
            }
            drawEgoCar(context, w, h)
        }
        .background(Color(red: 0.04, green: 0.04, blue: 0.07))
        .clipped()
    }

    private func drawRoadSurface(_ ctx: GraphicsContext, _ w: CGFloat, _ h: CGFloat,
                                  _ vx: CGFloat, _ vy: CGFloat, _ by: CGFloat) {
        var road = Path()
        road.move(to: CGPoint(x: w * 0.12, y: by))
        road.addLine(to: CGPoint(x: vx - 18, y: vy))
        road.addLine(to: CGPoint(x: vx + 18, y: vy))
        road.addLine(to: CGPoint(x: w * 0.88, y: by))
        road.closeSubpath()
        ctx.fill(road, with: .color(Color(red: 0.09, green: 0.09, blue: 0.11)))
    }

    private func drawLaneLines(_ ctx: GraphicsContext, _ w: CGFloat, _ h: CGFloat,
                                _ vx: CGFloat, _ vy: CGFloat, _ by: CGFloat) {
        let probs = viewModel.data.laneLineProbs

        func prob(_ i: Int) -> Double { i < probs.count ? probs[i] : 0 }

        // Outer left (solid)
        let leftConf = prob(0)
        strokeLine(ctx, from: CGPoint(x: w * 0.12, y: by), to: CGPoint(x: vx - 18, y: vy),
                   color: laneColor(leftConf), width: 3, dashed: false)
        // Inner left (dashed)
        strokeLine(ctx, from: CGPoint(x: w * 0.38, y: by), to: CGPoint(x: vx - 7, y: vy),
                   color: .white.opacity(0.45), width: 2, dashed: true)
        // Inner right (dashed)
        strokeLine(ctx, from: CGPoint(x: w * 0.62, y: by), to: CGPoint(x: vx + 7, y: vy),
                   color: .white.opacity(0.45), width: 2, dashed: true)
        // Outer right (solid)
        let rightConf = prob(3)
        strokeLine(ctx, from: CGPoint(x: w * 0.88, y: by), to: CGPoint(x: vx + 18, y: vy),
                   color: laneColor(rightConf), width: 3, dashed: false)
    }

    private func laneColor(_ prob: Double) -> Color {
        Color(red: 1 - prob, green: prob * 0.85 + 0.1, blue: 0.25)
    }

    private func drawPredictedPath(_ ctx: GraphicsContext, _ w: CGFloat, _ h: CGFloat,
                                    _ vx: CGFloat, _ vy: CGFloat, _ by: CGFloat) {
        let steer = viewModel.data.steeringAngle
        let offset = CGFloat(steer) * 0.28
        var path = Path()
        path.move(to: CGPoint(x: w / 2, y: by - 15))
        path.addQuadCurve(
            to: CGPoint(x: vx + offset, y: vy + 25),
            control: CGPoint(x: w / 2 + offset * 0.35, y: h * 0.58)
        )
        ctx.stroke(path, with: .color(Color(red: 0.25, green: 0.75, blue: 1.0).opacity(0.65)),
                  style: StrokeStyle(lineWidth: 2.5, dash: [9, 5]))
    }

    private func drawLeadCar(_ ctx: GraphicsContext, _ w: CGFloat, _ h: CGFloat,
                              _ vx: CGFloat, _ vy: CGFloat, _ by: CGFloat) {
        let dist = max(1, viewModel.data.leadDist)
        let t = CGFloat(min(dist, 120) / 120)
        let y = by - (by - vy) * (1 - t) - 8
        let scale = 0.25 + 0.75 * (1 - t)
        let carW = 38 * scale, carH = 26 * scale

        var carPath = Path()
        carPath.addRoundedRect(
            in: CGRect(x: vx - carW / 2, y: y - carH, width: carW, height: carH),
            cornerSize: CGSize(width: 4 * scale, height: 4 * scale)
        )

        let rel = viewModel.data.leadRelSpeed
        let carColor: Color = rel < -5
            ? Color(red: 1.0, green: 0.28, blue: 0.28)
            : rel > 5
            ? Color(red: 0.28, green: 1.0, blue: 0.45)
            : Color(red: 1.0, green: 0.82, blue: 0.18)

        ctx.fill(carPath, with: .color(carColor.opacity(0.78)))
        ctx.stroke(carPath, with: .color(carColor), style: StrokeStyle(lineWidth: 1.2))
    }

    private func drawEgoCar(_ ctx: GraphicsContext, _ w: CGFloat, _ h: CGFloat) {
        let cx = w / 2, cy = h * 0.86
        let cw: CGFloat = 38, ch: CGFloat = 52
        var body = Path()
        body.addRoundedRect(in: CGRect(x: cx - cw / 2, y: cy - ch / 2, width: cw, height: ch),
                            cornerSize: CGSize(width: 7, height: 7))
        ctx.fill(body, with: .color(Color(red: 0.18, green: 0.48, blue: 0.98)))
        ctx.stroke(body, with: .color(.white.opacity(0.75)), style: StrokeStyle(lineWidth: 1.5))
    }

    private func strokeLine(_ ctx: GraphicsContext, from: CGPoint, to: CGPoint,
                             color: Color, width: CGFloat, dashed: Bool) {
        var p = Path()
        p.move(to: from)
        p.addLine(to: to)
        let style = dashed
            ? StrokeStyle(lineWidth: width, dash: [11, 7])
            : StrokeStyle(lineWidth: width)
        ctx.stroke(p, with: .color(color), style: style)
    }
}
