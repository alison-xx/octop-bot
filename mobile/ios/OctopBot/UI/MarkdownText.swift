import SwiftUI

/// Block-level Markdown for assistant replies: headings, lists, quotes, fenced code, tables, rules.
/// Inline styling (bold, italics, code, links) comes from Foundation's Markdown parser.
struct MarkdownText: View {
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(MarkdownBlock.parse(text).enumerated()), id: \.offset) { _, block in
                view(for: block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
    }

    @ViewBuilder
    private func view(for block: MarkdownBlock) -> some View {
        switch block {
        case .heading(let level, let text):
            Text(Self.inline(text))
                .font(level == 1 ? .title2.bold() : level == 2 ? .title3.bold() : .headline)
                .padding(.top, 4)
        case .paragraph(let text):
            Text(Self.inline(text)).font(.body).lineSpacing(3)
        case .list(let items):
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(item.marker).foregroundStyle(Palette.secondary).monospacedDigit()
                        Text(Self.inline(item.text)).lineSpacing(3)
                    }
                    .padding(.leading, CGFloat(item.indent) * 16)
                }
            }
        case .quote(let text):
            Text(Self.inline(text))
                .foregroundStyle(Palette.secondary)
                .padding(.leading, 12)
                .overlay(alignment: .leading) { Capsule().fill(Palette.hairline).frame(width: 3) }
        case .code(let language, let code):
            CodeBlock(language: language, code: code)
        case .rule:
            Divider()
        case .table(let rows):
            ScrollView(.horizontal, showsIndicators: false) {
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                        GridRow {
                            ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                                Text(Self.inline(cell)).font(index == 0 ? .subheadline.bold() : .subheadline)
                            }
                        }
                        if index == 0 { Divider().gridCellUnsizedAxes(.horizontal) }
                    }
                }
                .padding(12)
                .background(Palette.surface, in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    static func inline(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
    }
}

private struct CodeBlock: View {
    var language: String
    var code: String
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(language.isEmpty ? "code" : language).font(.caption).foregroundStyle(Palette.secondary)
                Spacer()
                Button {
                    UIPasteboard.general.string = code
                    copied = true
                } label: {
                    Label(copied ? "common.copied" : "common.copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                        .font(.caption)
                }
                .foregroundStyle(Palette.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(.footnote, design: .monospaced))
                    .padding(.horizontal, 12)
                    .padding(.bottom, 12)
            }
        }
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

enum MarkdownBlock: Equatable {
    struct Item: Equatable { var marker: String; var text: String; var indent: Int }
    case heading(Int, String)
    case paragraph(String)
    case list([Item])
    case quote(String)
    case code(String, String)
    case table([[String]])
    case rule

    static func parse(_ source: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []
        var items: [Item] = []
        var quote: [String] = []
        var table: [[String]] = []
        var code: (language: String, lines: [String])?

        func flush() {
            if !paragraph.isEmpty { blocks.append(.paragraph(paragraph.joined(separator: "\n"))); paragraph = [] }
            if !items.isEmpty { blocks.append(.list(items)); items = [] }
            if !quote.isEmpty { blocks.append(.quote(quote.joined(separator: "\n"))); quote = [] }
            if !table.isEmpty { blocks.append(.table(table)); table = [] }
        }

        for rawLine in source.components(separatedBy: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if var open = code {
                if line.hasPrefix("```") {
                    blocks.append(.code(open.language, open.lines.joined(separator: "\n")))
                    code = nil
                } else {
                    open.lines.append(rawLine)
                    code = open
                }
                continue
            }
            if line.hasPrefix("```") {
                flush()
                code = (String(line.dropFirst(3)).trimmingCharacters(in: .whitespaces), [])
                continue
            }
            if line.isEmpty { flush(); continue }
            if let level = heading(line) {
                flush()
                blocks.append(.heading(level, String(line.drop(while: { $0 == "#" })).trimmingCharacters(in: .whitespaces)))
                continue
            }
            if line == "---" || line == "***" || line == "___" { flush(); blocks.append(.rule); continue }
            if line.hasPrefix("|") {
                if table.isEmpty { flush() }
                let cells = line.trimmingCharacters(in: CharacterSet(charactersIn: "|"))
                    .components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
                if !cells.allSatisfy({ !$0.isEmpty && $0.allSatisfy { "-:".contains($0) } }) { table.append(cells) }
                continue
            }
            if line.hasPrefix(">") {
                if quote.isEmpty { flush() }
                quote.append(String(line.dropFirst()).trimmingCharacters(in: .whitespaces))
                continue
            }
            if let item = listItem(rawLine) {
                if items.isEmpty { flush() }
                items.append(item)
                continue
            }
            if !items.isEmpty, rawLine.hasPrefix("  ") {
                items[items.count - 1].text += " " + line
                continue
            }
            if !items.isEmpty || !quote.isEmpty || !table.isEmpty { flush() }
            paragraph.append(line)
        }
        if let code { blocks.append(.code(code.language, code.lines.joined(separator: "\n"))) }
        flush()
        return blocks
    }

    private static func heading(_ line: String) -> Int? {
        let hashes = line.prefix { $0 == "#" }.count
        guard (1...6).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return hashes
    }

    private static func listItem(_ raw: String) -> Item? {
        let indent = raw.prefix { $0 == " " }.count / 2
        let line = raw.trimmingCharacters(in: .whitespaces)
        for bullet in ["- ", "* ", "+ "] where line.hasPrefix(bullet) {
            var text = String(line.dropFirst(2))
            var marker = "•"
            if text.hasPrefix("[ ] ") { marker = "☐"; text.removeFirst(4) }
            if text.hasPrefix("[x] ") || text.hasPrefix("[X] ") { marker = "☑"; text.removeFirst(4) }
            return Item(marker: marker, text: text, indent: indent)
        }
        let digits = line.prefix { $0.isNumber }
        if !digits.isEmpty, digits.count <= 3 {
            let rest = line.dropFirst(digits.count)
            if rest.hasPrefix(". ") || rest.hasPrefix(") ") {
                return Item(marker: digits + ".", text: String(rest.dropFirst(2)), indent: indent)
            }
        }
        return nil
    }
}
