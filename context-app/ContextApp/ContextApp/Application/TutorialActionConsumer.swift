import Dispatch
import Foundation

struct TutorialGroundingPayload: Codable, Equatable {
    let instruction: String
}

final class TutorialActionConsumer {
    private let groundInstruction: (GroundingInstruction) async -> String

    init(groundInstruction: @escaping (GroundingInstruction) async -> String) {
        self.groundInstruction = groundInstruction
    }

    func consume(step: TutorialStep) async -> String {
        let payload = Self.groundingPayload(for: step)
        let instruction = GroundingInstruction(
            text: payload.instruction,
            referenceImageData: nil,
            imageEncodingConfig: .groundingRequest,
            submittedAtUptimeNanoseconds: DispatchTime.now().uptimeNanoseconds
        )
        return await groundInstruction(instruction)
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
        step.instruction
    }
}
