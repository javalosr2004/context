import Dispatch
import Foundation

struct TutorialGroundingPayload: Codable, Equatable {
    let instruction: String
}

final class TutorialActionConsumer {
    private let groundInstruction: (GroundingInstruction) async -> String
    private let presentNonSpatial: (TutorialStep) async -> String

    init(
        groundInstruction: @escaping (GroundingInstruction) async -> String,
        presentNonSpatial: @escaping (TutorialStep) async -> String = { _ in "" }
    ) {
        self.groundInstruction = groundInstruction
        self.presentNonSpatial = presentNonSpatial
    }

    func consume(step: TutorialStep) async -> String {
        if Self.skipsGrounding(action: step.action) {
            return await presentNonSpatial(step)
        }
        let payload = Self.groundingPayload(for: step)
        let instruction = GroundingInstruction(
            text: payload.instruction,
            referenceImageData: nil,
            imageEncodingConfig: .groundingRequest,
            submittedAtUptimeNanoseconds: DispatchTime.now().uptimeNanoseconds,
            tooltip: step.instruction
        )
        return await groundInstruction(instruction)
    }

    static func skipsGrounding(action: TutorialAction) -> Bool {
        switch action {
        case .scroll, .pressKey, .wait, .confirm:
            return true
        case .type(let action):
            return action.target == nil
        case .click, .doubleClick, .rightClick, .hover, .drag:
            return false
        }
    }

    static func groundingPayload(for step: TutorialStep) -> TutorialGroundingPayload {
        TutorialGroundingPayload(instruction: groundingInstructionText(for: step))
    }

    static func groundingPayloadJSONString(for step: TutorialStep) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let payload = groundingPayload(for: step)
        guard
            let data = try? encoder.encode(payload),
            let json = String(data: data, encoding: .utf8)
        else {
            return #"{"instruction":""}"#
        }
        return json
    }

    static func groundingInstructionText(for step: TutorialStep) -> String {
        guard
            let description = targetDescription(for: step.action)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
            !description.isEmpty
        else {
            return step.instruction
        }
        return "\(step.instruction)\n\nTarget: \(description)"
    }

    private static func targetDescription(for action: TutorialAction) -> String? {
        switch action {
        case .click(let action):
            return action.target.description
        case .doubleClick(let action):
            return action.target.description
        case .rightClick(let action):
            return action.target.description
        case .hover(let action):
            return action.target.description
        case .type(let action):
            return action.target?.description
        case .scroll(let action):
            return action.target?.description
        case .drag(let action):
            return action.target.description
        case .pressKey, .wait, .confirm:
            return nil
        }
    }
}
