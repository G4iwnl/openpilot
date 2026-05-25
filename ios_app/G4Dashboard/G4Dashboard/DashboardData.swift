import Foundation

struct DashboardData: Codable {
    var speed: Double = 0
    var setSpeed: Double = 0
    var speedLimit: Int = 0
    var leftBlinker: Bool = false
    var rightBlinker: Bool = false
    var cruiseEnabled: Bool = false
    var cruiseAvailable: Bool = false
    var accel: Double = 0
    var leadDist: Double = 0
    var leadSpeed: Double = 0
    var leadRelSpeed: Double = 0
    var hasLead: Bool = false
    var steeringAngle: Double = 0
    var brakePressed: Bool = false
    var gasPressed: Bool = false
    var gear: String = "N"
    var opEnabled: Bool = false
    var laneLineProbs: [Double] = [0, 0, 0, 0]
    var hasLeadLeft: Bool = false
    var leadLeftDist: Double = 0
    var leadLeftRelSpeed: Double = 0
    var leadLeftDPath: Double = 0
    var hasLeadRight: Bool = false
    var leadRightDist: Double = 0
    var leadRightRelSpeed: Double = 0
    var leadRightDPath: Double = 0
}
