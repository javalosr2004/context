import Dispatch
import Foundation

final class TutorialActionConsumer {
    private let groundInstruction: (GroundingInstruction) async -> String

    init(groundInstruction: @escaping (GroundingInstruction) async -> String) {
        self.groundInstruction = groundInstruction
    }

    func consume(step: TutorialStep) async -> String {
        let instruction = GroundingInstruction(
            text: Self.groundingInstructionText(for: step),
            referenceImageData: nil,
            imageEncodingConfig: .groundingRequest,
            submittedAtUptimeNanoseconds: DispatchTime.now().uptimeNanoseconds
        )
        return await groundInstruction(instruction)
    }

    static func groundingInstructionText(for step: TutorialStep) -> String {
        var lines = [step.instruction]
        lines.append(contentsOf: metadataLines(for: step.action))
        return lines.joined(separator: "\n")
    }

    private static func metadataLines(for action: TutorialAction) -> [String] {
        switch action {
        case .click(let action):
            return targetLines(action.target)
        case .doubleClick(let action):
            return targetLines(action.target)
        case .rightClick(let action):
            return targetLines(action.target)
        case .hover(let action):
            return targetLines(action.target)
        case .type(let action):
            return targetLines(action.target) + ["Text to type: \(action.text)"]
        case .pressKey(let action):
            return ["Keys: \(action.keys.joined(separator: " + "))"]
        case .scroll(let action):
            var lines = action.target.map(targetLines) ?? []
            lines.append("Scroll direction: \(action.direction.rawValue)")
            lines.append("Scroll amount: \(action.amount.rawValue)")
            if let until = action.until {
                lines.append("Scroll until: \(until)")
            }
            return lines
        case .drag(let action):
            return targetLines(action.target) + [
                "Drag direction: \(action.direction.rawValue)",
                "Drag amount: \(action.amount.rawValue)"
            ]
        case .wait(let action):
            var lines = ["Wait until: \(action.until)"]
            if let timeoutMs = action.timeoutMs {
                lines.append("Timeout milliseconds: \(timeoutMs)")
            }
            return lines
        case .confirm(let action):
            return [
                "Confirmation question: \(action.question)",
                "Expected screen: \(action.expectedScreen)"
            ]
        }
    }

    private static func targetLines(_ target: ActionTarget) -> [String] {
        var lines: [String] = ["Target kind: \(target.kind.rawValue)"]
        append("Target label", target.label, to: &lines)
        append("Target role", target.role, to: &lines)
        append("Target description", target.description, to: &lines)
        if let textNearby = target.textNearby, !textNearby.isEmpty {
            lines.append("Nearby text: \(textNearby.joined(separator: ", "))")
        }
        return lines
    }

    private static func append(_ label: String, _ value: String?, to lines: inout [String]) {
        guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        lines.append("\(label): \(value)")
    }
}
