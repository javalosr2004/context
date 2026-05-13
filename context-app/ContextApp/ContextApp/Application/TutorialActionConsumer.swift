import Foundation

final class TutorialActionConsumer {
    func consume(step: TutorialStep) {
        switch step.action {
        case .click(let action):
            handleClick(action)
        case .doubleClick(let action):
            handleDoubleClick(action)
        case .rightClick(let action):
            handleRightClick(action)
        case .hover(let action):
            handleHover(action)
        case .type(let action):
            handleType(action)
        case .pressKey(let action):
            handlePressKey(action)
        case .scroll(let action):
            handleScroll(action)
        case .drag(let action):
            handleDrag(action)
        case .wait(let action):
            handleWait(action)
        case .confirm(let action):
            handleConfirm(action)
        }
    }

    private func handleClick(_ action: ClickAction) {
        // TODO: Connect target resolution to the overlay highlighter and accessibility click flow.
    }

    private func handleDoubleClick(_ action: DoubleClickAction) {
        // TODO: Connect target resolution to the overlay highlighter and double-click event flow.
    }

    private func handleRightClick(_ action: RightClickAction) {
        // TODO: Connect target resolution to the overlay highlighter and contextual-click event flow.
    }

    private func handleHover(_ action: HoverAction) {
        // TODO: Connect target resolution to pointer positioning and hover preview UI.
    }

    private func handleType(_ action: TypeAction) {
        // TODO: Route text entry through the keyboard event system after confirming the target focus.
    }

    private func handlePressKey(_ action: PressKeyAction) {
        // TODO: Map key names to the app keyboard event system and surface unsupported combinations.
    }

    private func handleScroll(_ action: ScrollAction) {
        // TODO: Connect scroll direction and amount to the overlay guidance or accessibility scroll flow.
    }

    private func handleDrag(_ action: DragAction) {
        // TODO: Resolve the drag target and route direction and amount to pointer gesture handling.
    }

    private func handleWait(_ action: WaitAction) {
        // TODO: Connect wait conditions to screen observation, timeout handling, and progress UI.
    }

    private func handleConfirm(_ action: ConfirmAction) {
        // TODO: Present the confirmation question in the chat or overlay before continuing playback.
    }
}
