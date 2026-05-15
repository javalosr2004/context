import Markdown
import SwiftUI

struct MarkdownTextView: View {
    let text: String

    var body: some View {
        Text(MarkdownTextRenderer.attributedString(from: text))
    }
}

enum MarkdownTextRenderer {
    static func attributedString(from source: String) -> AttributedString {
        let document = Document(parsing: MarkdownNewlineNormalizer.normalize(source))
        var result = AttributedString()

        for child in document.children {
            appendTopLevelBlock(child, to: &result)
        }

        return result
    }

    private static func appendTopLevelBlock(_ markup: Markup, to result: inout AttributedString) {
        if !result.characters.isEmpty {
            result.append(AttributedString("\n\n"))
        }
        result.append(blockText(for: markup, listDepth: 0))
    }

    private static func blockText(for markup: Markup, listDepth: Int) -> AttributedString {
        switch markup {
        case let heading as Heading:
            var headingText = inlineText(for: heading)
            headingText.font = .system(size: 14, weight: .semibold)
            return headingText
        case let paragraph as Paragraph:
            return inlineText(for: paragraph)
        case let list as UnorderedList:
            return listText(for: list, marker: "•", listDepth: listDepth)
        case let list as OrderedList:
            return orderedListText(for: list, listDepth: listDepth)
        case let quote as BlockQuote:
            var quoteText = inlineText(for: quote)
            quoteText.foregroundColor = .secondary
            return quoteText
        case let codeBlock as CodeBlock:
            var codeText = AttributedString(codeBlock.code)
            codeText.font = .system(size: 12, design: .monospaced)
            return codeText
        default:
            return inlineText(for: markup)
        }
    }

    private static func listText(for list: Markup, marker: String, listDepth: Int) -> AttributedString {
        var result = AttributedString()
        for (index, child) in list.children.enumerated() {
            if index > 0 {
                result.append(AttributedString("\n"))
            }
            result.append(listItemText(for: child, marker: marker, listDepth: listDepth))
        }
        return result
    }

    private static func orderedListText(for list: OrderedList, listDepth: Int) -> AttributedString {
        var result = AttributedString()
        for (index, child) in list.children.enumerated() {
            if index > 0 {
                result.append(AttributedString("\n"))
            }
            result.append(listItemText(for: child, marker: "\(index + 1).", listDepth: listDepth))
        }
        return result
    }

    private static func listItemText(for markup: Markup, marker: String, listDepth: Int) -> AttributedString {
        let indentation = String(repeating: "  ", count: listDepth)
        var result = AttributedString("\(indentation)\(marker) ")
        var appendedFirstBlock = false

        for child in markup.children {
            let childText = blockText(for: child, listDepth: listDepth + 1)
            if appendedFirstBlock {
                result.append(AttributedString("\n"))
                if !(child is UnorderedList) && !(child is OrderedList) {
                    result.append(AttributedString(indentation + "  "))
                }
            }
            result.append(childText)
            appendedFirstBlock = true
        }

        if !appendedFirstBlock {
            result.append(inlineText(for: markup))
        }

        return result
    }

    private static func inlineText(for markup: Markup) -> AttributedString {
        switch markup {
        case let text as Markdown.Text:
            return AttributedString(text.string)
        case let strong as Strong:
            var value = inlineChildrenText(for: strong)
            value.inlinePresentationIntent = .stronglyEmphasized
            return value
        case let emphasis as Emphasis:
            var value = inlineChildrenText(for: emphasis)
            value.inlinePresentationIntent = .emphasized
            return value
        case let code as InlineCode:
            var value = AttributedString(code.code)
            value.font = .system(size: 12, design: .monospaced)
            return value
        case is SoftBreak:
            return AttributedString("\n")
        case is LineBreak:
            return AttributedString("\n")
        default:
            return inlineChildrenText(for: markup)
        }
    }

    private static func inlineChildrenText(for markup: Markup) -> AttributedString {
        var result = AttributedString()
        for child in markup.children {
            result.append(inlineText(for: child))
        }
        return result
    }
}

enum MarkdownNewlineNormalizer {
    static func normalize(_ source: String) -> String {
        var result = ""
        var index = source.startIndex

        while index < source.endIndex {
            let character = source[index]

            if character == "\r" {
                let nextIndex = source.index(after: index)
                if nextIndex < source.endIndex, source[nextIndex] == "\n" {
                    index = source.index(after: nextIndex)
                } else {
                    index = nextIndex
                }
                result.append("\n")
                continue
            }

            if character == "\\" {
                var slashEndIndex = index
                while slashEndIndex < source.endIndex, source[slashEndIndex] == "\\" {
                    slashEndIndex = source.index(after: slashEndIndex)
                }

                guard slashEndIndex < source.endIndex else {
                    result.append(contentsOf: source[index..<slashEndIndex])
                    index = slashEndIndex
                    continue
                }

                if source[slashEndIndex] == "n" {
                    result.append("\n")
                    index = source.index(after: slashEndIndex)
                    continue
                }

                if source[slashEndIndex] == "r" {
                    let afterR = source.index(after: slashEndIndex)
                    if escapedNewlineStarts(at: afterR, in: source) {
                        result.append("\n")
                        index = indexAfterEscapedNewlineStarting(at: afterR, in: source)
                    } else {
                        result.append("\n")
                        index = afterR
                    }
                    continue
                }

                result.append(contentsOf: source[index..<slashEndIndex])
                index = slashEndIndex
                continue
            }

            result.append(character)
            index = source.index(after: index)
        }

        return result
    }

    private static func escapedNewlineStarts(at index: String.Index, in source: String) -> Bool {
        guard index < source.endIndex, source[index] == "\\" else { return false }

        var slashEndIndex = index
        while slashEndIndex < source.endIndex, source[slashEndIndex] == "\\" {
            slashEndIndex = source.index(after: slashEndIndex)
        }

        return slashEndIndex < source.endIndex && source[slashEndIndex] == "n"
    }

    private static func indexAfterEscapedNewlineStarting(at index: String.Index, in source: String) -> String.Index {
        var slashEndIndex = index
        while slashEndIndex < source.endIndex, source[slashEndIndex] == "\\" {
            slashEndIndex = source.index(after: slashEndIndex)
        }
        return source.index(after: slashEndIndex)
    }
}
