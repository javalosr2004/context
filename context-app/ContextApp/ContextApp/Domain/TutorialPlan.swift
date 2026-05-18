import Foundation

struct TutorialPlan: Codable, Equatable {
    static let supportedSchemaVersion = "tutorial_plan.v1"

    let schemaVersion: String
    let goal: String
    let summary: String
    let steps: [TutorialStep]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case goal
        case summary
        case steps
    }

    init(
        schemaVersion: String = Self.supportedSchemaVersion,
        goal: String,
        summary: String,
        steps: [TutorialStep]
    ) {
        self.schemaVersion = schemaVersion
        self.goal = goal
        self.summary = summary
        self.steps = steps
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let schemaVersion = try container.decode(String.self, forKey: .schemaVersion)

        guard schemaVersion == Self.supportedSchemaVersion else {
            throw DecodingError.dataCorruptedError(
                forKey: .schemaVersion,
                in: container,
                debugDescription: "Unsupported tutorial plan schema_version '\(schemaVersion)'. Expected '\(Self.supportedSchemaVersion)'."
            )
        }

        self.schemaVersion = schemaVersion
        self.goal = try container.decode(String.self, forKey: .goal)
        self.summary = try container.decode(String.self, forKey: .summary)
        self.steps = try container.decode([TutorialStep].self, forKey: .steps)
    }
}

struct DraftPlan: Codable, Equatable {
    static let supportedSchemaVersion = "draft_plan.v1"

    let schemaVersion: String
    let goal: String
    let steps: [DraftStep]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case goal
        case steps
    }

    init(
        schemaVersion: String = Self.supportedSchemaVersion,
        goal: String,
        steps: [DraftStep]
    ) {
        self.schemaVersion = schemaVersion
        self.goal = goal
        self.steps = steps
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let schemaVersion = try container.decode(String.self, forKey: .schemaVersion)

        guard schemaVersion == Self.supportedSchemaVersion else {
            throw DecodingError.dataCorruptedError(
                forKey: .schemaVersion,
                in: container,
                debugDescription: "Unsupported draft plan schema_version '\(schemaVersion)'. Expected '\(Self.supportedSchemaVersion)'."
            )
        }

        self.schemaVersion = schemaVersion
        self.goal = try container.decode(String.self, forKey: .goal)
        self.steps = try container.decode([DraftStep].self, forKey: .steps)
    }
}

struct DraftStep: Codable, Equatable {
    let instruction: String
    let kind: String
}

struct TutorialStep: Codable, Equatable {
    let stepId: String
    let instruction: String
    let actions: [TutorialAction]
    let confidence: Double

    private enum CodingKeys: String, CodingKey {
        case stepId = "step_id"
        case instruction
        case actions
        case confidence
    }
}

enum TutorialStepJSONFormatter {
    static func displayString(for step: TutorialStep) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]

        guard
            let data = try? encoder.encode(step),
            let json = String(data: data, encoding: .utf8)
        else {
            return "{}"
        }

        return json
    }
}

enum TutorialAction: Codable, Equatable {
    case click(ClickAction)
    case doubleClick(DoubleClickAction)
    case rightClick(RightClickAction)
    case hover(HoverAction)
    case type(TypeAction)
    case pressKey(PressKeyAction)
    case scroll(ScrollAction)
    case drag(DragAction)
    case wait(WaitAction)
    case confirm(ConfirmAction)
    case userChoice(UserChoiceAction)

    var type: String {
        switch self {
        case .click:
            return "click"
        case .doubleClick:
            return "double_click"
        case .rightClick:
            return "right_click"
        case .hover:
            return "hover"
        case .type:
            return "type"
        case .pressKey:
            return "press_key"
        case .scroll:
            return "scroll"
        case .drag:
            return "drag"
        case .wait:
            return "wait"
        case .confirm:
            return "confirm"
        case .userChoice:
            return "user_choice"
        }
    }

    var requiresConfirmation: Bool {
        switch self {
        case .click(let a): return a.requiresConfirmation
        case .doubleClick(let a): return a.requiresConfirmation
        case .rightClick(let a): return a.requiresConfirmation
        case .hover(let a): return a.requiresConfirmation
        case .type(let a): return a.requiresConfirmation
        case .pressKey(let a): return a.requiresConfirmation
        case .scroll(let a): return a.requiresConfirmation
        case .drag(let a): return a.requiresConfirmation
        case .wait(let a): return a.requiresConfirmation
        case .confirm: return true
        case .userChoice(let a): return a.requiresConfirmation
        }
    }

    private enum CodingKeys: String, CodingKey {
        case type
        case target
        case text
        case key
        case direction
        case durationMs = "duration_ms"
        case prompt
        case requiresConfirmation = "requires_confirmation"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)

        switch type {
        case "click":
            self = .click(try ClickAction(from: decoder))
        case "double_click":
            self = .doubleClick(try DoubleClickAction(from: decoder))
        case "right_click":
            self = .rightClick(try RightClickAction(from: decoder))
        case "hover":
            self = .hover(try HoverAction(from: decoder))
        case "type":
            self = .type(try TypeAction(from: decoder))
        case "press_key":
            self = .pressKey(try PressKeyAction(from: decoder))
        case "scroll":
            self = .scroll(try ScrollAction(from: decoder))
        case "drag":
            self = .drag(try DragAction(from: decoder))
        case "wait":
            self = .wait(try WaitAction(from: decoder))
        case "confirm":
            self = .confirm(try ConfirmAction(from: decoder))
        case "user_choice":
            self = .userChoice(try UserChoiceAction(from: decoder))
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .type,
                in: container,
                debugDescription: "Unknown tutorial action type '\(type)'."
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(type, forKey: .type)
        try container.encode(requiresConfirmation, forKey: .requiresConfirmation)

        switch self {
        case .click(let action):
            try container.encode(action.target, forKey: .target)
        case .doubleClick(let action):
            try container.encode(action.target, forKey: .target)
        case .rightClick(let action):
            try container.encode(action.target, forKey: .target)
        case .hover(let action):
            try container.encode(action.target, forKey: .target)
        case .type(let action):
            try container.encodeIfPresent(action.target, forKey: .target)
            try container.encode(action.text, forKey: .text)
        case .pressKey(let action):
            try container.encode(action.key, forKey: .key)
        case .scroll(let action):
            try container.encodeIfPresent(action.target, forKey: .target)
            try container.encode(action.direction, forKey: .direction)
        case .drag(let action):
            try container.encode(action.target, forKey: .target)
            try container.encode(action.direction, forKey: .direction)
        case .wait(let action):
            try container.encode(action.durationMs, forKey: .durationMs)
        case .confirm:
            break
        case .userChoice(let action):
            try container.encode(action.prompt, forKey: .prompt)
        }
    }
}

struct ActionTarget: Codable, Equatable {
    let kind: ActionTargetKind
    let label: String?
    let role: String?
    let description: String?
    let textNearby: [String]?

    private enum CodingKeys: String, CodingKey {
        case kind
        case label
        case role
        case description
        case textNearby = "text_nearby"
    }
}

enum ActionTargetKind: String, Codable, Equatable {
    case element
    case screen
    case window
    case region
}

enum ScrollDirection: String, Codable, Equatable {
    case up
    case down
    case left
    case right
}

private enum _ActionConfirmKey: String, CodingKey {
    case requiresConfirmation = "requires_confirmation"
}

private func _decodeRequiresConfirmation(from decoder: Decoder) throws -> Bool {
    let container = try decoder.container(keyedBy: _ActionConfirmKey.self)
    return try container.decode(Bool.self, forKey: .requiresConfirmation)
}

struct ClickAction: Codable, Equatable {
    let target: ActionTarget
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case target }

    init(target: ActionTarget, requiresConfirmation: Bool) {
        self.target = target
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.target = try container.decode(ActionTarget.self, forKey: .target)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct DoubleClickAction: Codable, Equatable {
    let target: ActionTarget
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case target }

    init(target: ActionTarget, requiresConfirmation: Bool) {
        self.target = target
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.target = try container.decode(ActionTarget.self, forKey: .target)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct RightClickAction: Codable, Equatable {
    let target: ActionTarget
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case target }

    init(target: ActionTarget, requiresConfirmation: Bool) {
        self.target = target
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.target = try container.decode(ActionTarget.self, forKey: .target)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct HoverAction: Codable, Equatable {
    let target: ActionTarget
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case target }

    init(target: ActionTarget, requiresConfirmation: Bool) {
        self.target = target
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.target = try container.decode(ActionTarget.self, forKey: .target)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct TypeAction: Codable, Equatable {
    let target: ActionTarget?
    let text: String
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case target, text }

    init(target: ActionTarget?, text: String, requiresConfirmation: Bool) {
        self.target = target
        self.text = text
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.target = try container.decodeIfPresent(ActionTarget.self, forKey: .target)
        self.text = try container.decode(String.self, forKey: .text)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct PressKeyAction: Codable, Equatable {
    let key: String
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case key }

    init(key: String, requiresConfirmation: Bool) {
        self.key = key
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.key = try container.decode(String.self, forKey: .key)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct ScrollAction: Codable, Equatable {
    let target: ActionTarget?
    let direction: ScrollDirection
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case target, direction }

    init(target: ActionTarget?, direction: ScrollDirection, requiresConfirmation: Bool) {
        self.target = target
        self.direction = direction
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.target = try container.decodeIfPresent(ActionTarget.self, forKey: .target)
        self.direction = try container.decode(ScrollDirection.self, forKey: .direction)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct DragAction: Codable, Equatable {
    let target: ActionTarget
    let direction: ScrollDirection
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case target, direction }

    init(target: ActionTarget, direction: ScrollDirection, requiresConfirmation: Bool) {
        self.target = target
        self.direction = direction
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.target = try container.decode(ActionTarget.self, forKey: .target)
        self.direction = try container.decode(ScrollDirection.self, forKey: .direction)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct WaitAction: Codable, Equatable {
    let durationMs: Int
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey {
        case durationMs = "duration_ms"
    }

    init(durationMs: Int, requiresConfirmation: Bool) {
        self.durationMs = durationMs
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.durationMs = try container.decode(Int.self, forKey: .durationMs)
        self.requiresConfirmation = try _decodeRequiresConfirmation(from: decoder)
    }
}

struct UserChoiceAction: Codable, Equatable {
    let prompt: String
    let requiresConfirmation: Bool

    private enum CodingKeys: String, CodingKey { case prompt }

    init(prompt: String, requiresConfirmation: Bool = true) {
        self.prompt = prompt
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.prompt = try container.decode(String.self, forKey: .prompt)
        self.requiresConfirmation = (try? _decodeRequiresConfirmation(from: decoder)) ?? true
    }
}

struct ConfirmAction: Codable, Equatable {
    let requiresConfirmation: Bool

    init(requiresConfirmation: Bool = true) {
        self.requiresConfirmation = requiresConfirmation
    }

    init(from decoder: Decoder) throws {
        self.requiresConfirmation = (try? _decodeRequiresConfirmation(from: decoder)) ?? true
    }

    func encode(to encoder: Encoder) throws {
        // requires_confirmation for confirm is encoded by TutorialAction.
    }
}
