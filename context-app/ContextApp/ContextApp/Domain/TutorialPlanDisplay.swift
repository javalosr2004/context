import Foundation

struct TutorialStepDisplayItem: Equatable, Identifiable {
    let step: TutorialStep
    let stepNumber: Int
    let title: String

    var id: String {
        step.stepId
    }
}

struct TutorialPlanDisplay: Equatable {
    let goal: String
    let currentStep: TutorialStepDisplayItem?
    let upcomingSteps: [TutorialStepDisplayItem]
    let totalStepCount: Int

    var progressText: String {
        guard let currentStep else {
            return "No steps"
        }
        return "Step \(currentStep.stepNumber) of \(totalStepCount)"
    }

    static func make(
        from plan: TutorialPlan,
        currentStepID: String?,
        upcomingLimit: Int = 3
    ) -> TutorialPlanDisplay {
        let items = plan.steps.enumerated().map { index, step in
            TutorialStepDisplayItem(
                step: step,
                stepNumber: index + 1,
                title: displayTitle(for: step)
            )
        }
        let currentIndex = currentIndex(in: items, currentStepID: currentStepID)
        let currentStep = currentIndex.map { items[$0] }
        let upcomingSteps = currentIndex
            .map { compactUpcomingSteps(after: $0, in: items, limit: upcomingLimit) } ?? []

        return TutorialPlanDisplay(
            goal: plan.goal.trimmingCharacters(in: .whitespacesAndNewlines),
            currentStep: currentStep,
            upcomingSteps: upcomingSteps,
            totalStepCount: plan.steps.count
        )
    }

    private static func currentIndex(in items: [TutorialStepDisplayItem], currentStepID: String?) -> Int? {
        guard !items.isEmpty else { return nil }
        guard let currentStepID else { return items.startIndex }
        return items.firstIndex { $0.step.stepId == currentStepID } ?? items.startIndex
    }

    private static func compactUpcomingSteps(
        after currentIndex: Int,
        in items: [TutorialStepDisplayItem],
        limit: Int
    ) -> [TutorialStepDisplayItem] {
        guard limit > 0 else { return [] }

        var result: [TutorialStepDisplayItem] = []
        var previousTitle = items[currentIndex].title

        for item in items.dropFirst(currentIndex + 1) where result.count < limit {
            guard !item.title.caseInsensitiveEquals(previousTitle) else { continue }
            result.append(item)
            previousTitle = item.title
        }

        return result
    }

    private static func displayTitle(for step: TutorialStep) -> String {
        let cleanedInstruction = cleanInstruction(step.instruction)
        if let firstAction = step.actions.first,
           let addressBarTitle = addressBarDisplayTitle(for: cleanedInstruction, action: firstAction) {
            return addressBarTitle
        }
        return cleanedInstruction
    }

    private static func cleanInstruction(_ instruction: String) -> String {
        let trimmed = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasSuffix(".") else { return trimmed }
        return String(trimmed.dropLast())
    }

    private static func addressBarDisplayTitle(for instruction: String, action: TutorialAction) -> String? {
        let normalizedInstruction = instruction.lowercased()
        guard normalizedInstruction.contains("address bar") else { return nil }

        switch action {
        case .type:
            return "Enter the Runpod dashboard URL"
        case .pressKey:
            if normalizedInstruction.contains("open") {
                return instruction
            }
            return nil
        default:
            guard
                normalizedInstruction.contains("type")
                    || normalizedInstruction.contains("replace")
                    || normalizedInstruction.contains("enter")
            else {
                return nil
            }
            return "Enter the Runpod dashboard URL"
        }
    }
}

private extension String {
    func caseInsensitiveEquals(_ other: String) -> Bool {
        compare(other, options: [.caseInsensitive, .diacriticInsensitive]) == .orderedSame
    }
}
